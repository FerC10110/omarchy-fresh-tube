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


# --- state -------------------------------------------------------------------

DEFAULT_PREFS = {"width": 420, "height": 520, "pinned": False}
PREF_LIMITS = {"width": (300, 4000), "height": (220, 4000)}
WATCH_URL = "https://www.youtube.com/watch?v={}"


def empty_state():
    return {"version": STATE_VERSION, "seen": [], "feeds": {}, "fetchedAt": "", "prefs": dict(DEFAULT_PREFS)}


def _valid_pref(key, value):
    """Check if a saved pref value is valid; return True to keep it, False to use the default."""
    if key in PREF_LIMITS:
        # width and height: must be int (not bool, which is a subclass of int) within limits.
        if isinstance(value, bool) or not isinstance(value, int):
            return False
        low, high = PREF_LIMITS[key]
        return low <= value <= high
    elif key == "pinned":
        # pinned: must be a real bool.
        return isinstance(value, bool)
    return False


def load_state():
    data = read_json(state_path(), None)
    state = empty_state()
    if data is None:
        return state
    if isinstance(data.get("seen"), list):
        state["seen"] = [str(s) for s in data["seen"]]
    if isinstance(data.get("feeds"), dict):
        state["feeds"] = data["feeds"]
    if isinstance(data.get("fetchedAt"), str):
        state["fetchedAt"] = data["fetchedAt"]
    prefs = data.get("prefs")
    if isinstance(prefs, dict):
        for key in DEFAULT_PREFS:
            if key in prefs and _valid_pref(key, prefs[key]):
                state["prefs"][key] = prefs[key]
    return state


def save_state(state):
    write_json(state_path(), state)


def set_pref(state, key, value):
    if key in PREF_LIMITS:
        low, high = PREF_LIMITS[key]
        try:
            number = int(str(value).strip())
        except ValueError:
            raise FreshTubeError(f"{key} must be a whole number", USAGE)
        if not low <= number <= high:
            raise FreshTubeError(f"{key} must be between {low} and {high}", USAGE)
        state["prefs"][key] = number
    elif key == "pinned":
        text = str(value).strip().lower()
        if text not in ("true", "false"):
            raise FreshTubeError("pinned must be true or false", USAGE)
        state["prefs"]["pinned"] = text == "true"
    else:
        raise FreshTubeError(f"Unknown preference: {key}", USAGE)
    return state["prefs"]


def mark_seen(state, video_id):
    if video_id not in state["seen"]:
        state["seen"].append(video_id)


def prune_seen(state):
    """Forget seen ids that no cached feed lists any more; they can never show up again."""
    keep = set()
    for feed in state["feeds"].values():
        keep.update(feed.get("recent") or [])
    state["seen"] = [s for s in state["seen"] if s in keep]


def update_feed(state, channel_id, parsed, fetched_at):
    state["feeds"][channel_id] = {"fetchedAt": fetched_at, "lastError": "",
                                  "latest": parsed.get("latest"), "recent": list(parsed.get("recent") or [])}


def set_feed_error(state, channel_id, message):
    """Remember why a channel failed while keeping whatever it had cached."""
    feed = state["feeds"].setdefault(channel_id, {"fetchedAt": "", "lastError": "", "latest": None, "recent": []})
    feed["lastError"] = message


def drop_feed(state, channel_id):
    state["feeds"].pop(channel_id, None)


def unseen_videos(state, channels):
    """The newest video of every channel whose newest video was not seen, newest first."""
    seen = set(state["seen"])
    videos = []
    for channel in channels:
        feed = state["feeds"].get(channel["id"]) or {}
        latest = feed.get("latest")
        if not latest or latest.get("videoId") in seen:
            continue
        videos.append({"videoId": latest["videoId"], "title": latest.get("title", ""),
                       "channelId": channel["id"], "channel": channel.get("name", ""),
                       "published": latest.get("published", ""), "thumbnail": latest.get("thumbnail", ""),
                       "url": WATCH_URL.format(latest["videoId"])})
    videos.sort(key=lambda v: v["published"], reverse=True)
    return videos
