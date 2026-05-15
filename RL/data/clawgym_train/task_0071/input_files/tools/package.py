import argparse
import os
import sys
import zipfile


def package_dir(src_dir, out_zip):
    os.makedirs(os.path.dirname(out_zip), exist_ok=True)
    with zipfile.ZipFile(out_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(src_dir):
            for fn in files:
                fp = os.path.join(root, fn)
                arcname = os.path.relpath(fp, start=src_dir)
                zf.write(fp, arcname)


def main():
    parser = argparse.ArgumentParser(description='Package a source directory into a zip file (offline).')
    parser.add_argument('--src', required=True, help='Source directory to zip (e.g., app)')
    parser.add_argument('--out', required=True, help='Output zip file path (e.g., output/build/package.zip)')
    args = parser.parse_args()

    if not os.path.isdir(args.src):
        print(f"Source directory not found: {args.src}", file=sys.stderr)
        return 2
    package_dir(args.src, args.out)
    print(f"Packaged {args.src} -> {args.out}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
