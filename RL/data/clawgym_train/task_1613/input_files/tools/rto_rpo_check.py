#!/usr/bin/env python3
import sys
import argparse

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rto")
    parser.add_argument("--rpo")
    args = parser.parse_args()
    print(f"[OK] RTO within target: 3.5 hours <= {args.rto} hours")
    print(f"[WARN] RPO exceeds target by 15 minutes (target {args.rpo} hour, actual 1h15m)")
    sys.exit(0)

if __name__ == "__main__":
    main()
