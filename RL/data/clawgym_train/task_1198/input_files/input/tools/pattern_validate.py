#!/usr/bin/env python3
import argparse
import json
import sys
from typing import List, Dict, Any

"""
pattern_validate.py

Validates a catalog of costume pattern specs from a JSON file.

Usage:
  python3 input/tools/pattern_validate.py --catalog input/patterns/catalog.json

Output format to stdout (examples):
  OK Pattern 'Mirrorball Catsuit' (P-001)
  WARN W101 Pattern 'Sequin Bodysuit' (P-004): high piece count on sequin may be difficult to stitch
  ERROR E002 Pattern 'Disco Jacket' (P-003): max_panel_width_cm 160 exceeds 150 cm fabric roll width

At the end, prints a one-line summary to stderr:
  SUMMARY total=6 valid=2 invalid=4 warnings=2

Exit code is 0 if invalid == 0, else 2.
"""

ALLOWED_FABRICS = {"spandex", "satin", "leatherette", "sequin"}

E_PIECE_MIN = ("E001", "piece_count must be >= 1")
E_WIDTH_EXCEEDS = ("E002", "max_panel_width_cm {width} exceeds 150 cm fabric roll width")
E_FABRIC_UNSUPPORTED = ("E003", "fabric '{fabric}' is not supported; choose from spandex, satin, leatherette, sequin")
E_FIELD_MISSING = ("E004", "field '{field}' is required")

W_SEQUIN_COMPLEXITY = ("W101", "high piece count on sequin may be difficult to stitch")
W_GLITTER_NOTE = ("W102", "notes contain 'glitter'; be cautious of glitter shedding")


def load_catalog(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("Catalog JSON must be a list of pattern objects")
    return data


def validate_pattern(p: Dict[str, Any]) -> Dict[str, Any]:
    pid = str(p.get("id", "?"))
    name = p.get("name")
    errors = []
    warnings = []

    # Required fields
    if not name:
        code, msg_t = E_FIELD_MISSING
        errors.append(("ERROR", code, msg_t.format(field="name")))
        name_disp = "(missing name)"
    else:
        name_disp = str(name)

    if "piece_count" not in p or not isinstance(p.get("piece_count"), int) or p.get("piece_count", 0) < 1:
        code, msg_t = E_PIECE_MIN
        errors.append(("ERROR", code, msg_t))

    max_w = p.get("max_panel_width_cm")
    if max_w is None:
        code, msg_t = E_FIELD_MISSING
        errors.append(("ERROR", code, msg_t.format(field="max_panel_width_cm")))
    else:
        try:
            w = float(max_w)
            if w > 150:
                code, msg_t = E_WIDTH_EXCEEDS
                errors.append(("ERROR", code, msg_t.format(width=int(w) if float(int(w)) == w else w)))
        except (TypeError, ValueError):
            code, msg_t = E_FIELD_MISSING
            errors.append(("ERROR", code, msg_t.format(field="max_panel_width_cm")))

    fabric = p.get("fabric")
    if not fabric or str(fabric) not in ALLOWED_FABRICS:
        code, msg_t = E_FABRIC_UNSUPPORTED
        errors.append(("ERROR", code, msg_t.format(fabric=fabric)))

    # Warnings
    try:
        if str(fabric) == "sequin" and int(p.get("piece_count", 0)) > 20:
            warnings.append(("WARN", W_SEQUIN_COMPLEXITY[0], W_SEQUIN_COMPLEXITY[1]))
    except Exception:
        pass

    notes = str(p.get("notes", ""))
    if "glitter" in notes.lower():
        warnings.append(("WARN", W_GLITTER_NOTE[0], W_GLITTER_NOTE[1]))

    return {
        "id": pid,
        "name": name_disp,
        "errors": errors,
        "warnings": warnings,
    }


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True, help="Path to catalog.json")
    args = ap.parse_args(argv)

    try:
        catalog = load_catalog(args.catalog)
    except Exception as e:
        print(f"ERROR E900 General: failed to load catalog: {e}", file=sys.stdout)
        print("SUMMARY total=0 valid=0 invalid=1 warnings=0", file=sys.stderr)
        return 2

    total = 0
    valid = 0
    invalid = 0
    warn_count = 0

    for p in catalog:
        total += 1
        result = validate_pattern(p)
        pid = result["id"]
        name = result["name"]
        errs = result["errors"]
        warns = result["warnings"]

        for level, code, msg in errs:
            print(f"{level} {code} Pattern '{name}' ({pid}): {msg}")
        for level, code, msg in warns:
            print(f"{level} {code} Pattern '{name}' ({pid}): {msg}")
        warn_count += len(warns)

        if errs:
            invalid += 1
        else:
            valid += 1
            print(f"OK Pattern '{name}' ({pid})")

    print(f"SUMMARY total={total} valid={valid} invalid={invalid} warnings={warn_count}", file=sys.stderr)
    return 0 if invalid == 0 else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
