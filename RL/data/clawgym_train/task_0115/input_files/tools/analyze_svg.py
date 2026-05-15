#!/usr/bin/env python3
import os
import sys
import json
import re
import argparse
import xml.etree.ElementTree as ET

HEX_RE = re.compile(r'#(?:[0-9a-fA-F]{6})')


def analyze_svg(path):
    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except Exception as e:
        sys.stderr.write(f"ERROR {path}: {e}\n")
        sys.stderr.flush()
        return None
    colors = set()
    stroke_widths = set()
    for elem in root.iter():
        # Colors from fill and stroke
        for attr in ("fill", "stroke"):
            v = elem.attrib.get(attr)
            if v:
                m = HEX_RE.search(v)
                if m:
                    colors.add(m.group(0).upper())
        # Stroke widths as-is (string)
        sw = elem.attrib.get("stroke-width")
        if sw:
            stroke_widths.add(sw.strip())
    return {
        "file": path.replace(os.sep, "/"),
        "colors": sorted(colors),
        "stroke_widths": sorted(stroke_widths),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("directory", help="Directory to scan for .svg files")
    args = ap.parse_args()
    base = os.path.abspath(args.directory)
    if not os.path.isdir(base):
        sys.stderr.write(f"ERROR: Not a directory: {args.directory}\n")
        sys.exit(2)
    svg_files = []
    for root, _dirs, files in os.walk(base):
        for f in files:
            if f.lower().endswith(".svg"):
                svg_files.append(os.path.join(root, f))
    svg_files.sort()
    for p in svg_files:
        result = analyze_svg(p)
        if result is not None:
            sys.stdout.write(json.dumps(result) + "\n")
    sys.stdout.flush()

if __name__ == "__main__":
    main()
