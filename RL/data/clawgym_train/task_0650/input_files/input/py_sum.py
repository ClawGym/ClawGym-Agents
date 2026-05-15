#!/usr/bin/env python3
"""
py_sum.py — Sums integers from 0 to N-1 using an explicit Python loop.
Designed for micro-benchmarking against sum(range(N)).

Default N is chosen to produce a stable, short-running benchmark on most systems.
"""

import sys

def main():
    # Allow optional N via CLI: python3 py_sum.py [N]
    try:
        N = int(sys.argv[1]) if len(sys.argv) > 1 else 1500000
    except ValueError:
        print("Usage: python3 py_sum.py [N]", file=sys.stderr)
        sys.exit(1)

    total = 0
    for i in range(N):
        total += i

    # Print to avoid being optimized away and to keep behavior consistent
    # (stdout is captured by the benchmarking tool).
    print(total)

if __name__ == "__main__":
    main()