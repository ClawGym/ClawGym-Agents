import sys
import argparse

# Simple, deterministic simulator for packaging runs.
# Prints several OK metric lines to stdout.
# If --test is provided, also prints an ERROR to stderr and exits with code 1.

OK_LINES = [
    "OK: shift=A, units=1250, rejects=18, uptime=97.8",
    "OK: shift=B, units=1310, rejects=22, uptime=98.1",
    "OK: shift=C, units=1195, rejects=20, uptime=96.9",
]

ERROR_LINE = "ERROR: sealing_jam count=1 station=heat_sealer shift=B"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Emit an error to stderr and exit non-zero")
    args = parser.parse_args()

    for line in OK_LINES:
        print(line)

    if args.test:
        print(ERROR_LINE, file=sys.stderr)
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()
