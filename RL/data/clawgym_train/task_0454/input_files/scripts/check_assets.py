#!/usr/bin/env python3
import json
import sys
from typing import Dict, Any

def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <assets_status.json>", file=sys.stderr)
        sys.exit(2)
    path = sys.argv[1]
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data: Dict[str, Any] = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        sys.exit(2)
    except json.JSONDecodeError as e:
        print(f"ERROR: JSON decode error in {path}: {e}", file=sys.stderr)
        sys.exit(2)

    errors = 0
    warnings = 0

    for species, info in data.items():
        has = bool(info.get('has_dorsal_photo'))
        dpi = int(info.get('dpi') or 0)
        credit = (info.get('credit') or '').strip()
        license_ok = bool(info.get('license_approved'))

        if not has:
            print(f"ERROR [{species}] Missing dorsal photo")
            errors += 1
        if not license_ok:
            print(f"ERROR [{species}] License not approved")
            errors += 1
        if has and dpi < 300:
            print(f"WARNING [{species}] DPI below 300: {dpi}")
            warnings += 1
        if has and not credit:
            print(f"WARNING [{species}] Missing credit metadata")
            warnings += 1

    print(f"Summary: {errors} errors, {warnings} warnings")
    sys.exit(1 if errors > 0 else 0)

if __name__ == '__main__':
    main()
