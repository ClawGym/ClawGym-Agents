#!/usr/bin/env python3
import sys
import re

def main():
    if len(sys.argv) != 2:
        sys.stderr.write("Usage: python quote_extractor.py <path_to_markdown>\n")
        sys.exit(2)
    path = sys.argv[1]
    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except OSError as e:
        sys.stderr.write(f"Error opening file: {e}\n")
        sys.exit(1)

    count = 0
    print(f"Quoted segments from {path}:")
    for i, line in enumerate(lines, start=1):
        segments = re.findall(r'"([^"]+)"', line)
        for seg in segments:
            count += 1
            print(f'Line {i}: "{seg}"')
    print(f"Found {count} quoted segment(s).")

if __name__ == '__main__':
    main()
