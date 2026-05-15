import sys
import argparse
import base64


def main():
    parser = argparse.ArgumentParser(
        prog="encrypt.py",
        description="Toy encoder to simulate an encryption step"
    )
    parser.add_argument("--in", dest="infile", required=True, help="Path to input file")
    parser.add_argument("--out", dest="outfile", required=True, help="Path to output file")
    args = parser.parse_args()

    with open(args.infile, "rb") as f:
        data = f.read()
    out = base64.b64encode(data)
    with open(args.outfile, "wb") as g:
        g.write(out)
    print(f"Wrote encoded data to {args.outfile}")


if __name__ == "__main__":
    try:
        main()
    except FileNotFoundError as e:
            sys.stderr.write(f"ERROR: {e}\n")
            sys.exit(1)
