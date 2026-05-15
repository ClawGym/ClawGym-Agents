#!/usr/bin/env python3
import os
import sys
import json

def main():
    # Load config
    cfg_path = os.path.join('config', 'backup_config.json')
    try:
        with open(cfg_path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
    except Exception as e:
        print(f"ERROR file_path={cfg_path} type=CONFIG_LOAD_FAILED detail={e}", file=sys.stderr)
        return 2

    input_dir = cfg.get('input_dir', 'data/stories')
    allowed_ext = cfg.get('allowed_extension', '.json').lower()
    required_fields = cfg.get('required_fields', [])

    if not os.path.isdir(input_dir):
        print(f"ERROR file_path={input_dir} type=INPUT_DIR_MISSING detail=directory not found", file=sys.stderr)
        return 2

    scanned = 0
    ok = 0
    errors = []  # list of tuples (rel, type, detail)

    try:
        entries = sorted(os.listdir(input_dir))
    except Exception as e:
        print(f"ERROR file_path={input_dir} type=LIST_FAILED detail={e}", file=sys.stderr)
        return 2

    for name in entries:
        path = os.path.join(input_dir, name)
        if not os.path.isfile(path):
            continue
        scanned += 1
        rel = name
        ext = os.path.splitext(name)[1].lower()
        if ext != allowed_ext:
            msg = f"unsupported extension {ext}; expected {allowed_ext}"
            print(f"ERROR file_path={rel} type=UNSUPPORTED_EXTENSION detail={msg}", file=sys.stderr)
            errors.append((rel, 'UNSUPPORTED_EXTENSION', msg))
            continue
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            msg = f"invalid JSON at line {e.lineno} col {e.colno}"
            print(f"ERROR file_path={rel} type=INVALID_JSON detail={msg}", file=sys.stderr)
            errors.append((rel, 'INVALID_JSON', msg))
            continue
        except Exception as e:
            msg = str(e)
            print(f"ERROR file_path={rel} type=READ_FAILED detail={msg}", file=sys.stderr)
            errors.append((rel, 'READ_FAILED', msg))
            continue
        missing = [k for k in required_fields if k not in data]
        if missing:
            msg = "missing fields: " + ",".join(missing)
            print(f"ERROR file_path={rel} type=MISSING_FIELDS detail={msg}", file=sys.stderr)
            errors.append((rel, 'MISSING_FIELDS', msg))
            continue
        ok += 1

    print(f"INFO input_dir={input_dir}")
    print(f"INFO scanned={scanned} ok={ok} errors={len(errors)}")
    print(f"SUMMARY scanned={scanned} ok={ok} errors={len(errors)}")

    return 1 if errors else 0

if __name__ == '__main__':
    rc = main()
    sys.exit(rc)
