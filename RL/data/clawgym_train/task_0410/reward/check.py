import csv
import json
import sys
from pathlib import Path
from typing import Dict, Any, Tuple, List, Optional


def _safe_read_csv_indexed(path: Path, key_field: str) -> Optional[Dict[str, Dict[str, str]]]:
    try:
        with path.open(newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            rows = {}
            for row in reader:
                if key_field not in row:
                    return None
                key = str(row[key_field])
                rows[key] = {k: ("" if v is None else str(v)) for k, v in row.items()}
            return rows
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        with path.open('r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_discrepancies_csv(path: Path) -> Tuple[bool, Optional[List[Dict[str, str]]]]:
    expected_header = ["OrderID", "field", "legacy_transformed", "pilot_value", "rule"]
    try:
        with path.open(newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None or header != expected_header:
                return False, None
            rows = []
            for parts in reader:
                if len(parts) != len(expected_header):
                    return False, None
                row = dict(zip(expected_header, parts))
                rows.append(row)
            return True, rows
    except Exception:
        return False, None


def _count_leading_spaces(s: str) -> int:
    n = 0
    for ch in s:
        if ch == ' ':
            n += 1
        else:
            break
    return n


def _safe_load_simple_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Loads a very small subset of YAML used by provided business_rules.yaml:
    - mappings with string keys and string values
    - nested mappings based on indentation
    - no lists or complex types
    """
    try:
        with path.open('r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception:
        return None

    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Dict[str, Any]]] = [(-1, root)]

    try:
        for raw_line in lines:
            line = raw_line.rstrip('\n')
            if not line.strip():
                continue
            if line.lstrip().startswith("#"):
                continue
            indent = _count_leading_spaces(line)
            content = line.strip()
            if ':' not in content:
                return None
            key_part, value_part = content.split(':', 1)
            key = key_part.strip()
            value = value_part.strip()

            while stack and indent <= stack[-1][0]:
                stack.pop()
            parent = stack[-1][1] if stack else root

            if value == "":
                new_dict: Dict[str, Any] = {}
                parent[key] = new_dict
                stack.append((indent, new_dict))
            else:
                parent[key] = value
        return root
    except Exception:
        return None


def _apply_transform(field_rules: Dict[str, Any], value: str) -> Any:
    if 'transform_map' in field_rules and isinstance(field_rules['transform_map'], dict):
        mapped = field_rules['transform_map'].get(value, None)
        if mapped is not None:
            return mapped
    transform = field_rules.get('transform')
    if transform == 'upper':
        return (value or "").upper()
    if transform == 'to_int':
        try:
            return int(value)
        except Exception:
            return value
    if transform == 'yyyymmdd_to_iso':
        v = value or ""
        if len(v) == 8 and v.isdigit():
            return f"{v[0:4]}-{v[4:6]}-{v[6:8]}"
        return v
    if transform == 'lstrip_zeros':
        return (value or "").lstrip('0')
    if transform == 'rstrip_spaces':
        return (value or "").rstrip()
    return value


def _compare_values(compare_mode: str, transformed: Any, pilot_value: str) -> bool:
    if compare_mode == 'equal_int':
        try:
            t = int(transformed)
            p = int(pilot_value)
            return t == p
        except Exception:
            return False
    return str(transformed) == str(pilot_value)


def _coerce_int(val: Any) -> Optional[int]:
    try:
        return int(val)
    except Exception:
        return None


def _compute_expected(legacy_path: Path, pilot_path: Path, rules_path: Path) -> Optional[Dict[str, Any]]:
    rules = _safe_load_simple_yaml(rules_path)
    if not rules or 'primary_key' not in rules or 'fields' not in rules:
        return None

    primary_key = str(rules['primary_key'])
    fields_rules = rules['fields']
    if not isinstance(fields_rules, dict) or primary_key not in fields_rules:
        return None

    # Normalize transform_map entries (they are parsed as scalars under the nested dict)
    for field_name, rule in list(fields_rules.items()):
        if isinstance(rule, dict) and 'transform_map' in rule and isinstance(rule['transform_map'], dict):
            # ensure all keys/values are strings as parsed
            tm = rule['transform_map']
            fields_rules[field_name]['transform_map'] = {str(k): str(v) for k, v in tm.items()}

    legacy_rows = _safe_read_csv_indexed(legacy_path, primary_key)
    pilot_rows = _safe_read_csv_indexed(pilot_path, primary_key)
    if legacy_rows is None or pilot_rows is None:
        return None

    legacy_keys = set(legacy_rows.keys())
    pilot_keys = set(pilot_rows.keys())
    matched_keys = sorted(list(legacy_keys & pilot_keys))
    missing_in_pilot = sorted(list(legacy_keys - pilot_keys), key=lambda x: x)
    extra_in_pilot = sorted(list(pilot_keys - legacy_keys), key=lambda x: x)

    compared_fields = [f for f in fields_rules.keys() if f != primary_key]

    mismatches = []
    by_rule = {f: {"checks": 0, "fails": 0} for f in compared_fields}

    for k in matched_keys:
        lrec = legacy_rows[k]
        prec = pilot_rows[k]
        for field in compared_fields:
            fr = fields_rules.get(field, {})
            compare_mode = fr.get('compare', 'exact_string')
            by_rule[field]["checks"] += 1
            legacy_val = lrec.get(field, "")
            pilot_val = prec.get(field, "")
            # If transform_map present in YAML string parser, values are strings
            transformed = _apply_transform(fr, legacy_val)
            ok = _compare_values(compare_mode, transformed, pilot_val)
            if not ok:
                by_rule[field]["fails"] += 1
                mismatches.append({
                    "OrderID": str(k),
                    "field": field,
                    "legacy_transformed": str(transformed),
                    "pilot_value": str(pilot_val),
                    "rule": str(compare_mode)
                })

    expected = {
        "legacy_rows": len(legacy_rows),
        "pilot_rows": len(pilot_rows),
        "matched_keys": len(matched_keys),
        "missing_in_pilot": missing_in_pilot,
        "extra_in_pilot": extra_in_pilot,
        "total_field_checks": len(matched_keys) * len(compared_fields),
        "failed_field_checks": len(mismatches),
        "by_rule": by_rule,
        "mismatches": mismatches,
        "compared_fields": compared_fields,
    }
    return expected


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "report_json_exists_and_parseable": 0.0,
        "report_summary_correct": 0.0,
        "report_by_rule_correct": 0.0,
        "report_mismatches_correct": 0.0,
        "discrepancies_csv_exists_and_parseable": 0.0,
        "discrepancies_rows_correct": 0.0,
        "outputs_cross_consistent": 0.0,
    }

    legacy_path = workspace / "input" / "legacy_orders.csv"
    pilot_path = workspace / "input" / "pilot_orders.csv"
    rules_path = workspace / "input" / "business_rules.yaml"

    expected = _compute_expected(legacy_path, pilot_path, rules_path)
    if expected is None:
        return scores

    report_path = workspace / "output" / "report.json"
    discrepancies_path = workspace / "output" / "discrepancies.csv"

    report = _safe_load_json(report_path)
    if isinstance(report, dict):
        scores["report_json_exists_and_parseable"] = 1.0

    if isinstance(report, dict) and "summary" in report and isinstance(report["summary"], dict):
        summary = report["summary"]
        try:
            legacy_rows = _coerce_int(summary.get("legacy_rows"))
            pilot_rows = _coerce_int(summary.get("pilot_rows"))
            matched_keys = _coerce_int(summary.get("matched_keys"))
            total_field_checks = _coerce_int(summary.get("total_field_checks"))
            failed_field_checks = _coerce_int(summary.get("failed_field_checks"))
            missing_in_pilot = summary.get("missing_in_pilot")
            extra_in_pilot = summary.get("extra_in_pilot")

            if isinstance(missing_in_pilot, list):
                missing_set = set(str(x) for x in missing_in_pilot)
            else:
                missing_set = None

            if isinstance(extra_in_pilot, list):
                extra_set = set(str(x) for x in extra_in_pilot)
            else:
                extra_set = None

            conds = [
                legacy_rows == expected["legacy_rows"],
                pilot_rows == expected["pilot_rows"],
                matched_keys == expected["matched_keys"],
                total_field_checks == expected["total_field_checks"],
                failed_field_checks == expected["failed_field_checks"],
                missing_set == set(expected["missing_in_pilot"]) if missing_set is not None else False,
                extra_set == set(expected["extra_in_pilot"]) if extra_set is not None else False,
            ]
            if all(conds):
                scores["report_summary_correct"] = 1.0
        except Exception:
            pass

    if isinstance(report, dict) and "by_rule" in report and isinstance(report["by_rule"], dict):
        by_rule = report["by_rule"]
        ok = True
        for field, exp in expected["by_rule"].items():
            if field not in by_rule or not isinstance(by_rule[field], dict):
                ok = False
                break
            checks = _coerce_int(by_rule[field].get("checks"))
            fails = _coerce_int(by_rule[field].get("fails"))
            if checks != exp["checks"] or fails != exp["fails"]:
                ok = False
                break
        if ok:
            scores["report_by_rule_correct"] = 1.0

    if isinstance(report, dict) and "mismatches" in report and isinstance(report["mismatches"], list):
        rep_mismatches = report["mismatches"]
        try:
            def to_tuple_list(items):
                tset = set()
                for it in items:
                    oid = str(it.get("OrderID"))
                    field = str(it.get("field"))
                    legacy_t = str(it.get("legacy_transformed"))
                    pilot_v = str(it.get("pilot_value"))
                    rule = str(it.get("rule"))
                    tset.add((oid, field, legacy_t, pilot_v, rule))
                return tset

            expected_tuples = to_tuple_list(expected["mismatches"])
            report_tuples = to_tuple_list(rep_mismatches)
            if report_tuples == expected_tuples and len(rep_mismatches) == len(expected["mismatches"]):
                scores["report_mismatches_correct"] = 1.0
        except Exception:
            pass

    ok_csv, rows = _safe_read_discrepancies_csv(discrepancies_path)
    if ok_csv and rows is not None:
        scores["discrepancies_csv_exists_and_parseable"] = 1.0
        try:
            csv_tuples = set()
            for r in rows:
                csv_tuples.add((str(r.get("OrderID", "")),
                                str(r.get("field", "")),
                                str(r.get("legacy_transformed", "")),
                                str(r.get("pilot_value", "")),
                                str(r.get("rule", ""))))
            expected_tuples = set((m["OrderID"], m["field"], m["legacy_transformed"], m["pilot_value"], m["rule"])
                                  for m in expected["mismatches"])
            if csv_tuples == expected_tuples and len(rows) == len(expected["mismatches"]):
                scores["discrepancies_rows_correct"] = 1.0
        except Exception:
            pass

    if scores["report_mismatches_correct"] == 1.0 and scores["discrepancies_rows_correct"] == 1.0:
        scores["outputs_cross_consistent"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()