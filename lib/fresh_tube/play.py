"""Launch the player for one video and, under Hyprland, put its window below the bar."""
import json
import os
import shlex
import subprocess
import time

from .errors import GENERAL, FreshTubeError
from .videos import WATCH_URL

DEFAULT_SIZE = (860, 484)
WINDOW_WAIT_SECONDS = 10
WINDOW_POLL_SECONDS = 0.1
HYPRCTL_TIMEOUT = 5
PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT_PATH = os.path.join(PLUGIN_DIR, "mpv", "fresh-tube.lua")
BIN_PATH = os.path.join(PLUGIN_DIR, "bin", "fresh-tube")

# Module-level so tests can replace them.
popen = subprocess.Popen
sleep = time.sleep
monotonic = time.monotonic


def player_argv(player_command):
    return shlex.split(player_command or "") or ["mpv"]


def is_mpv(argv):
    return os.path.basename(argv[0]) == "mpv"


def build_argv(player_command, video_id, size):
    """The full command line: mpv gets the companion script, the size and resume; others only the URL."""
    argv = player_argv(player_command)
    if is_mpv(argv):
        argv += ["--save-position-on-quit", "--force-window=immediate",
                 f"--geometry={size[0]}x{size[1]}", f"--script={SCRIPT_PATH}",
                 f"--script-opts=fresh_tube-id={video_id},fresh_tube-bin={BIN_PATH}"]
    return argv + [WATCH_URL.format(video_id)]


def default_size(monitors):
    """A quarter of the focused monitor's logical width, 16:9; DEFAULT_SIZE when that cannot be known."""
    if not monitors:
        return DEFAULT_SIZE
    focused = next((m for m in monitors if isinstance(m, dict) and m.get("focused")), None)
    monitor = focused or (monitors[0] if isinstance(monitors[0], dict) else None)
    if not monitor:
        return DEFAULT_SIZE
    try:
        scale = float(monitor.get("scale") or 1) or 1.0
        width = int(round(int(monitor.get("width")) / scale / 4))
    except (TypeError, ValueError):
        return DEFAULT_SIZE
    if width <= 0:
        return DEFAULT_SIZE
    return width, int(round(width * 9 / 16))


def launch(argv):
    """Start the player in its own session, or say why it could not start."""
    try:
        return popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    except OSError as e:
        reason = e.strerror or str(e)
        raise FreshTubeError(f"Could not start {os.path.basename(argv[0])}: {reason}", GENERAL)


def start(player_command, video_id, size):
    """Launch the player, then a detached helper that places its window; returns the player's pid."""
    process = launch(build_argv(player_command, video_id, size))
    try:
        popen([BIN_PATH, "place-window", str(process.pid)], stdin=subprocess.DEVNULL,
              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass  # the video plays anyway, just not placed
    return process.pid


# --- Hyprland ------------------------------------------------------------------

def hyprctl(what):
    """Parsed `hyprctl <what> -j`, or None when hyprctl is missing, fails or prints no JSON."""
    try:
        done = subprocess.run(["hyprctl", what, "-j"], capture_output=True, text=True, timeout=HYPRCTL_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0:
        return None
    try:
        return json.loads(done.stdout)
    except ValueError:
        return None


def dispatch(*args):
    try:
        subprocess.run(["hyprctl", "dispatch", *args], capture_output=True, text=True, timeout=HYPRCTL_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        pass


def pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def find_window(pid):
    """The hyprctl client of `pid`, waiting up to WINDOW_WAIT_SECONDS; None without Hyprland or a window."""
    deadline = monotonic() + WINDOW_WAIT_SECONDS
    while True:
        clients = hyprctl("clients")
        if clients is None:
            return None
        for client in clients:
            if isinstance(client, dict) and client.get("pid") == pid:
                return client
        if not pid_alive(pid) or monotonic() >= deadline:
            return None
        sleep(WINDOW_POLL_SECONDS)


def place_window(client):
    """Float the window if needed and move it to the top-left of its monitor's usable area."""
    monitors = hyprctl("monitors") or []
    monitor = next((m for m in monitors if isinstance(m, dict) and m.get("id") == client.get("monitor")), None)
    if monitor is None:
        return
    reserved = monitor.get("reserved") or [0, 0, 0, 0]
    try:
        x = int(monitor.get("x", 0)) + int(reserved[0])
        y = int(monitor.get("y", 0)) + int(reserved[1])
    except (TypeError, ValueError, IndexError):
        return
    target = f"address:{client.get('address')}"
    if not client.get("floating"):
        dispatch("setfloating", target)
    dispatch("movewindowpixel", f"exact {x} {y},{target}")
