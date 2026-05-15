#!/usr/bin/env python3
# NOTE: This is intentionally rough and needs review/refactor.
import sys, csv, os
VERSION = "0.1.0"

def load_species(path):
    # Poorly implemented loader: no error handling, doesn't close file.
    f = open(path)
    reader = csv.DictReader(f)
    data = list(reader)
    if len(data) == 0:
        return None
    return data

def summarize_cmd(args):
    # Uses sys.argv directly and returns success even when arguments are missing.
    if len(sys.argv) < 3:
        print("usage: summarize FILE", file=sys.stderr)
        return  # Should have non-zero exit but returns None instead.
    path = sys.argv[2]
    rows = load_species(path)
    if rows is None:
        print("no rows lol", file=sys.stdout)  # Wrong tone and stream.
        return
    counts = {}
    for r in rows:
        k = r.get("region", "").strip()
        try:
            n = int(r.get("observations", "0"))
        except Exception:
            n = 0
        counts[k] = counts.get(k, 0) + n
    print("summary:" + str(counts))

def help_cmd(args):
    print("Wildlife tool v%s. bad help. do stuff." % VERSION)


def fetch_guidelines_cmd(args):
    # Not implemented. Intended to download an official page and extract headings.
    print("not implemented; google it yourself")


def main():
    if len(sys.argv) < 2:
        print("No command given. bye.", file=sys.stderr)
        return
    cmd = sys.argv[1]
    if cmd == "summarize":
        summarize_cmd(sys.argv[2:])
    elif cmd == "help" or cmd == "--help":
        help_cmd(sys.argv[2:])
    elif cmd == "fetch-guidelines":
        fetch_guidelines_cmd(sys.argv[2:])
    else:
        print("Unknown cmd '%s' - whatever" % cmd)

if __name__ == "__main__":
    main()
