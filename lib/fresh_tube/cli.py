"""fresh-tube: the latest unseen video of the YouTube channels you pick."""
import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor

from . import feed, resolve, store, ytdlp
from .errors import DUPLICATE, GENERAL, UNKNOWN, USAGE, FreshTubeError


def emit(data):
    print(json.dumps(data, ensure_ascii=False))


def channel_payload(channel, state):
    feed_state = state["feeds"].get(channel["id"]) or {}
    return dict(channel, lastError=feed_state.get("lastError", ""), source=feed_state.get("source", ""))


def cmd_add(args):
    channel_id = resolve.resolve_channel_id(args.url)
    if store.find_channel(store.load_channels(), channel_id):
        raise FreshTubeError("Already added", DUPLICATE)
    # Network first, files last: the fetch can take seconds and the panel may
    # write state (a seen video, a preference) in the meantime.
    parsed, source, error = fetch_one({"id": channel_id})
    channels = store.load_channels()
    name = (parsed or {}).get("name") or ""
    if name:
        channel = store.add_channel(channels, channel_id, name)
    else:
        # Kept anyway: the channel is real, only today's sources are silent.
        channel = store.add_channel(channels, channel_id, resolve.handle_of(args.url) or channel_id,
                                    name_pending=True)
    store.save_channels(channels)
    state = store.load_state()
    if parsed is not None:
        store.update_feed(state, channel_id, parsed, store.now_iso(), source)
    else:
        store.set_feed_error(state, channel_id, error)
    store.save_state(state)
    emit(channel_payload(channel, state))
    return 0


def cmd_remove(args):
    channels = store.load_channels()
    store.remove_channel(channels, args.channel_id)
    store.save_channels(channels)
    state = store.load_state()
    store.drop_feed(state, args.channel_id)
    store.prune_seen(state)
    store.save_state(state)
    emit({"removed": args.channel_id})
    return 0


def cmd_channels(args):
    state = store.load_state()
    payload = {"channels": [channel_payload(c, state) for c in store.load_channels()]}
    if args.json:
        emit(payload)
        return 0
    for c in payload["channels"]:
        line = f"{c['id']}  {c['name']}"
        if c["lastError"]:
            line += f"  ({c['lastError']})"
        print(line)
    return 0


MAX_PARALLEL_FETCHES = 6


def _failure(e):
    return str(e) if isinstance(e, FreshTubeError) else f"{type(e).__name__}: {e}"


def fetch_one(channel):
    """(parsed, source, error): the RSS feed, then yt-dlp when the feed fails, else why both failed."""
    try:
        return feed.fetch_feed(channel["id"]), "feed", ""
    except Exception as e:
        feed_error = _failure(e)
    try:
        return ytdlp.fetch_via_ytdlp(channel["id"]), "yt-dlp", ""
    except Exception as e:
        return None, "", f"feed: {feed_error}; yt-dlp: {_failure(e)}"


def refresh_all(channels, cached):
    results = []
    if channels and not cached:
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_FETCHES) as pool:
            results = list(pool.map(fetch_one, channels))
    # Load the state only now: the fetches took a while and the panel may have
    # saved a preference or a seen video in the meantime.
    state = store.load_state()
    if channels and not cached:
        now = store.now_iso()
        any_ok = False
        names = {}
        for channel, (parsed, source, error) in zip(channels, results):
            if parsed is not None:
                store.update_feed(state, channel["id"], parsed, now, source)
                names[channel["id"]] = parsed.get("name") or ""
                any_ok = True
            else:
                store.set_feed_error(state, channel["id"], error)
        if any_ok:
            state["fetchedAt"] = now
        store.prune_seen(state)
        store.save_state(state)
        if store.fill_pending_names(channels, names):
            store.save_channels(channels)
        offline = not any_ok
    else:
        offline = cached and bool(channels)
    errors = []
    for channel in channels:
        message = (state["feeds"].get(channel["id"]) or {}).get("lastError", "")
        if message:
            errors.append({"channelId": channel["id"], "channel": channel.get("name", ""), "message": message})
    return {"videos": store.unseen_videos(state, channels), "pinned": store.pinned_videos(state),
            "fetchedAt": state["fetchedAt"], "offline": offline, "channelCount": len(channels),
            "errors": errors}


def cmd_refresh(args):
    payload = refresh_all(store.load_channels(), args.cached)
    if args.json:
        emit(payload)
        return 0
    for v in payload["videos"]:
        print(f"{v['channel']}: {v['title']}  {v['url']}")
    return 0


def cmd_seen(args):
    state = store.load_state()
    store.mark_seen(state, args.video_id)
    store.save_state(state)
    emit({"seen": args.video_id})
    return 0


def cmd_pin(args):
    channels = store.load_channels()
    state = store.load_state()
    video = store.find_latest(state, channels, args.video_id)
    if video is None:
        # Re-pinning something already pinned must work even after its channel moved on.
        already = [p for p in state["pins"] if p["videoId"] == args.video_id]
        if not already:
            raise FreshTubeError("No such video", UNKNOWN)
        video = already[0]
    store.pin_video(state, video)
    store.save_state(state)
    emit({"pinned": store.pinned_videos(state)})
    return 0


def cmd_unpin(args):
    state = store.load_state()
    store.unpin_video(state, args.video_id)
    store.save_state(state)
    emit({"pinned": store.pinned_videos(state)})
    return 0


def cmd_prefs(args):
    state = store.load_state()
    if args.action == "set":
        if args.key is None or args.value is None:
            raise FreshTubeError("prefs set needs a key and a value", USAGE)
        store.set_pref(state, args.key, args.value)
        store.save_state(state)
    emit(state["prefs"])
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="fresh-tube", description=__doc__)
    sub = parser.add_subparsers(dest="command", metavar="command")
    sub.required = True

    p = sub.add_parser("add", help="add a channel by URL, @handle or id")
    p.add_argument("url")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("remove", help="remove a channel by id")
    p.add_argument("channel_id")
    p.set_defaults(func=cmd_remove)

    p = sub.add_parser("channels", help="list the channels")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_channels)

    p = sub.add_parser("refresh", help="fetch every channel's feed and list the unseen videos")
    p.add_argument("--json", action="store_true")
    p.add_argument("--cached", action="store_true", help="only what is already on disk, no network")
    p.set_defaults(func=cmd_refresh)

    p = sub.add_parser("seen", help="mark a video as seen")
    p.add_argument("video_id")
    p.set_defaults(func=cmd_seen)

    p = sub.add_parser("pin", help="keep a video listed even after watching it (at most 3)")
    p.add_argument("video_id")
    p.set_defaults(func=cmd_pin)

    p = sub.add_parser("unpin", help="stop keeping a video pinned")
    p.add_argument("video_id")
    p.set_defaults(func=cmd_unpin)

    p = sub.add_parser("prefs", help="read or change the popup preferences (width, height, pinned)")
    p.add_argument("action", choices=["get", "set"])
    p.add_argument("key", nargs="?")
    p.add_argument("value", nargs="?")
    p.set_defaults(func=cmd_prefs)

    return parser, sub


def main(argv=None):
    parser, _ = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except FreshTubeError as e:
        print(f"fresh-tube: {e}", file=sys.stderr)
        return e.code
    except Exception as e:
        print(f"fresh-tube: {type(e).__name__}: {e}", file=sys.stderr)
        return GENERAL
