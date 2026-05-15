#!/usr/bin/env python3
import sys
import argparse

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--region")
    args = parser.parse_args()
    print(f"Starting failover simulation for region {args.region}")
    sys.stderr.write("[ERROR] Failover failed: DNS propagation timeout after 120s\n")
    sys.stderr.write("Trace: simulated connection refused\n")
    print("Partial progress: database replica promoted")
    sys.exit(1)

if __name__ == "__main__":
    main()
