"""fresh-tube: the latest unseen video of the YouTube channels you pick."""
import argparse
import json
import sys

from .errors import FreshTubeError


def emit(data):
    print(json.dumps(data, ensure_ascii=False))


def build_parser():
    parser = argparse.ArgumentParser(prog="fresh-tube", description=__doc__)
    sub = parser.add_subparsers(dest="command", metavar="command")
    sub.required = True
    return parser, sub


def main(argv=None):
    parser, _ = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except FreshTubeError as e:
        print(f"fresh-tube: {e}", file=sys.stderr)
        return e.code
