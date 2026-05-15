#!/usr/bin/env python3
"""
py_genexpr.py — Sums integers from 0 to N-1 using built-in sum(range(N)).
Designed for micro-benchmarking against an explicit Python loop.

Default N is chosen to produce a stable, short-running benchmark on most systems.
"""

import sys

def main():
    # Allow optional N via CLI: python3 py_genexpr.py [N]
    try:
        N = int(sys.argv[1]) if len(sys.argv) > 1 else 1500000
    except ValueError:
        print("Usage: python3 py_genexpr.py [N]", file=sys.stderr)
        sys.exit(1)

    total = sum(range(N))
    print(total)

if __name__ == "__main__":
    main()