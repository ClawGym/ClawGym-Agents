#!/usr/bin/env python3
import sys
import argparse

def main():
    parser = argparse.ArgumentParser(description="Simulated encoder capability probe")
    parser.add_argument("--query", "-q", required=True, help="Encoder name to query (h264_nvenc|hevc_nvenc|prores_ks)")
    args = parser.parse_args()
    name = args.query.strip().lower()
    if name == "h264_nvenc":
        sys.stdout.write("ENCODER: h264_nvenc OK max_streams=4 max_bitrate_mbps=200\n")
        return 0
    elif name == "hevc_nvenc":
        sys.stderr.write("ERROR: encoder hevc_nvenc not found\n")
        return 3
    elif name == "prores_ks":
        sys.stdout.write("ENCODER: prores_ks OK_SW_ONLY max_streams=2 max_bitrate_mbps=800\n")
        return 0
    else:
        sys.stderr.write(f"ERROR: unknown encoder '{args.query}'\n")
        return 2

if __name__ == "__main__":
    sys.exit(main())
