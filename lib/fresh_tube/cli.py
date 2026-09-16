"""fresh-tube: the latest unseen video of the YouTube channels you pick."""
import argparse
import json
import sys

from . import feed, resolve, store
from .errors import DUPLICATE, FreshTubeError


def emit(data):
    print(json.dumps(data, ensure_ascii=False))


def channel_payload(channel, state):
    feed_state = state["feeds"].get(channel["id"]) or {}
    return dict(channel, lastError=feed_state.get("lastError", ""))


def cmd_add(args):
    channel_id = resolve.resolve_channel_id(args.url)
    if store.find_channel(store.load_channels(), channel_id):
        raise FreshTubeError("Already added", DUPLICATE)
    # Network first, files last: the fetch can take seconds and the panel may
    # write state (a seen video, a preference) in the meantime.
    parsed = feed.fetch_feed(channel_id)
    channels = store.load_channels()
    channel = store.add_channel(channels, channel_id, parsed["name"] or channel_id)
    store.save_channels(channels)
    state = store.load_state()
    store.update_feed(state, channel_id, parsed, store.now_iso())
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

    return parser, sub


def main(argv=None):
    parser, _ = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except FreshTubeError as e:
        print(f"fresh-tube: {e}", file=sys.stderr)
        return e.code
