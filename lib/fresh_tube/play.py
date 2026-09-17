"""Launch the player for one video and, under Hyprland, put its window below the bar."""
import json
import os
import shlex
import socket
import subprocess
import time

from .errors import GENERAL, USAGE, FreshTubeError
from .page import EMBED_URL
from .store import state_dir
from .videos import WATCH_URL

DEFAULT_SIZE = (860, 484)
WINDOW_WAIT_SECONDS = 30  # a browser's cold start can be slow; the wait ends early when the player dies
WINDOW_POLL_SECONDS = 0.1
WATCH_POLL_SECONDS = 1
HYPRCTL_TIMEOUT = 5
PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT_PATH = os.path.join(PLUGIN_DIR, "mpv", "fresh-tube.lua")
BIN_PATH = os.path.join(PLUGIN_DIR, "bin", "fresh-tube")
# Chromium-family browsers that accept --app and --user-data-dir.
BROWSERS = frozenset(["chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "brave", "brave-browser",
                      "vivaldi", "vivaldi-stable", "microsoft-edge", "microsoft-edge-stable", "helium", "opera"])
PAGE_URL = "http://127.0.0.1:{}/"
YOUTUBE_URL = "https://www.youtube.com/"

# Module-level so tests can replace them.
popen = subprocess.Popen
sleep = time.sleep
monotonic = time.monotonic


def player_argv(player_command):
    try:
        return shlex.split(player_command or "") or ["mpv"]
    except ValueError as e:
        raise FreshTubeError(f"Could not start the player: {e}", USAGE)


def is_mpv(argv):
    return os.path.basename(argv[0]) == "mpv"


def is_browser(argv):
    return os.path.basename(argv[0]) in BROWSERS


def browser_flags():
    """A profile of our own: a separate browser process (so its window can be found by pid) that keeps its own login."""
    return [f"--user-data-dir={os.path.join(state_dir(), 'browser')}", "--no-first-run", "--no-default-browser-check"]


def build_argv(player_command, video_id, size, fallback=None, port=None):
    """The full command line: mpv gets the companion script, the size and resume; a browser gets app mode on the
    page served at `port` (the embed itself without one); others only the URL."""
    argv = player_argv(player_command)
    if is_mpv(argv):
        argv += ["--save-position-on-quit", "--force-window=immediate",
                 f"--geometry={size[0]}x{size[1]}", f"--script={SCRIPT_PATH}",
                 f"--script-opt=fresh_tube-id={video_id}", f"--script-opt=fresh_tube-bin={BIN_PATH}"]
        if fallback:
            argv.append(f"--script-opt=fresh_tube-fallback={fallback}")
        return argv + [WATCH_URL.format(video_id)]
    if is_browser(argv):
        page = PAGE_URL.format(port) if port else EMBED_URL.format(video_id)
        return argv + browser_flags() + ["--autoplay-policy=no-user-gesture-required",
                                         f"--window-size={size[0]},{size[1]}", f"--app={page}"]
    return argv + [WATCH_URL.format(video_id)]


def login_argv(player_command):
    """A normal browser window on YouTube, in our profile, so the user can sign in there."""
    argv = player_argv(player_command)
    if not is_browser(argv):
        raise FreshTubeError(f"{os.path.basename(argv[0])} is not a browser I know how to open", USAGE)
    return argv + browser_flags() + [YOUTUBE_URL]


def _monitor_width(monitors, logical):
    """The focused (else first) monitor's width, in logical pixels when asked; None when it cannot be known."""
    if not monitors:
        return None
    focused = next((m for m in monitors if isinstance(m, dict) and m.get("focused")), None)
    monitor = focused or (monitors[0] if isinstance(monitors[0], dict) else None)
    if not monitor:
        return None
    try:
        width = float(int(monitor.get("width")))
        if logical:
            width = width / (float(monitor.get("scale") or 1) or 1.0)
    except (TypeError, ValueError):
        return None
    return width if width > 0 else None


def _quarter(width):
    """A quarter of `width`, 16:9; DEFAULT_SIZE without a usable width."""
    if width is None:
        return DEFAULT_SIZE
    quarter = int(round(width / 4))
    if quarter <= 0:
        return DEFAULT_SIZE
    return quarter, int(round(quarter * 9 / 16))


def default_size(monitors):
    """mpv's first-run size: mpv measures --geometry in physical pixels."""
    return _quarter(_monitor_width(monitors, logical=False))


def default_logical_size(monitors):
    """A browser's first-run size: browsers measure --window-size in logical pixels."""
    return _quarter(_monitor_width(monitors, logical=True))


def size_for(player_command, prefs):
    """The remembered size for this kind of player, else a quarter of the focused monitor."""
    if is_browser(player_argv(player_command)):
        keys, measure = ("browserWidth", "browserHeight"), default_logical_size
    else:
        keys, measure = ("playerWidth", "playerHeight"), default_size
    if all(key in prefs for key in keys):
        return prefs[keys[0]], prefs[keys[1]]
    return measure(hyprctl("monitors"))


def launch(argv):
    """Start the player in its own session, or say why it could not start."""
    try:
        return popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    except OSError as e:
        reason = e.strerror or str(e)
        raise FreshTubeError(f"Could not start {os.path.basename(argv[0])}: {reason}", GENERAL)


def open_port():
    """A listening socket on a free loopback port for the page that embeds the player; None if none can be had."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        sock.listen(8)
        return sock
    except OSError:
        return None


def start(player_command, video_id, size, fallback=None):
    """Launch the player, then a detached helper that places its window; returns the player's pid."""
    browser = is_browser(player_argv(player_command))
    sock = open_port() if browser else None
    try:
        argv = build_argv(player_command, video_id, size, fallback, sock.getsockname()[1] if sock else None)
        process = launch(argv)
        helper = [BIN_PATH, "place-window", str(process.pid)]
        options = {}
        if browser:
            # Browsers do not keep --window-size once floated, and have no script to remember their size.
            helper += ["--resize", f"{size[0]}x{size[1]}", "--watch"]
        if sock:
            # The helper serves the page on this socket for as long as the window lives.
            helper += ["--serve", str(sock.fileno()), "--video", video_id]
            options["pass_fds"] = (sock.fileno(),)
        try:
            popen(helper, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                  start_new_session=True, **options)
        except OSError:
            pass  # the video plays anyway, just not placed
    finally:
        if sock:
            sock.close()
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
            if isinstance(client, dict) and client.get("pid") == pid and client.get("mapped", True):
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


def resize_window(client, size):
    dispatch("resizewindowpixel", f"exact {size[0]} {size[1]},address:{client.get('address')}")


def window_size(client):
    """The client's (width, height) when hyprctl reports a usable one."""
    size = client.get("size")
    try:
        width, height = int(size[0]), int(size[1])
    except (TypeError, ValueError, IndexError):
        return None
    return (width, height) if width > 0 and height > 0 else None


def watch_window(client, pid):
    """Follow the window until it closes or its process dies; the last size seen after placement, or None."""
    address = client.get("address")
    last = None
    while True:
        sleep(WATCH_POLL_SECONDS)
        clients = hyprctl("clients")
        if clients is None:
            return last
        current = next((c for c in clients if isinstance(c, dict) and c.get("address") == address), None)
        if current is None:
            return last
        # A fullscreen window reports the monitor's size; that is not the size the user chose.
        if not current.get("fullscreen"):
            last = window_size(current) or last
        if not pid_alive(pid):
            return last
