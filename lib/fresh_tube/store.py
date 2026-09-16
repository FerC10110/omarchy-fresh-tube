"""channels.json and state.json: where Fresh Tube keeps what it knows."""
import datetime
import json
import os
import tempfile

from .errors import DUPLICATE, GENERAL, UNKNOWN, USAGE, FreshTubeError

APP = "fresh-tube"
CHANNELS_VERSION = 1
STATE_VERSION = 1
CHANNEL_URL = "https://www.youtube.com/channel/{}"


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _xdg(var, fallback_parts):
    base = os.environ.get(var, "")
    if not base:
        base = os.path.join(os.path.expanduser("~"), *fallback_parts)
    return os.path.join(base, APP)


def config_dir():
    return _xdg("XDG_CONFIG_HOME", [".config"])


def state_dir():
    return _xdg("XDG_STATE_HOME", [".local", "state"])


def channels_path():
    return os.path.join(config_dir(), "channels.json")


def state_path():
    return os.path.join(state_dir(), "state.json")


def read_json(path, empty):
    """The parsed file, `empty` when it does not exist. A file that is not JSON is an error."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return empty
    except (OSError, ValueError) as e:
        raise FreshTubeError(f"Could not read {os.path.basename(path)}: {e}", GENERAL)
    if not isinstance(data, dict):
        raise FreshTubeError(f"Could not read {os.path.basename(path)}: not an object", GENERAL)
    return data


def write_json(path, data):
    """Write through a temp file in the same directory so a crash never leaves half a file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# --- channels ---------------------------------------------------------------

def load_channels():
    data = read_json(channels_path(), {"version": CHANNELS_VERSION, "channels": []})
    channels = data.get("channels")
    if not isinstance(channels, list):
        return []
    return [c for c in channels if isinstance(c, dict) and c.get("id")]


def save_channels(channels):
    write_json(channels_path(), {"version": CHANNELS_VERSION, "channels": channels})


def find_channel(channels, channel_id):
    for c in channels:
        if c.get("id") == channel_id:
            return c
    return None


def add_channel(channels, channel_id, name):
    if find_channel(channels, channel_id):
        raise FreshTubeError("Already added", DUPLICATE)
    channel = {"id": channel_id, "name": name, "url": CHANNEL_URL.format(channel_id), "addedAt": now_iso()}
    channels.append(channel)
    return channel


def remove_channel(channels, channel_id):
    if not find_channel(channels, channel_id):
        raise FreshTubeError("No such channel", UNKNOWN)
    channels[:] = [c for c in channels if c.get("id") != channel_id]
    return channels
