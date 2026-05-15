import json
import sys
import csv
import re
from datetime import date
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import importlib.util
import xml.etree.ElementTree as ET


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _parse_simple_yaml_kv(yaml_path: Path) -> Optional[Dict[str, Any]]:
    """
    Very simple YAML parser for top-level key: value pairs.
    - Ignores comments (# ...) and blank lines.
    - Parses ints and floats; leaves other values as strings (stripping surrounding quotes).
    - Skips section headers like 'columns:'.
    """
    text = _read_text(yaml_path)
    if text is None:
        return None
    result: Dict[str, Any] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # Remove trailing inline comments
        if "#" in line:
            parts = line.split("#", 1)
            line = parts[0].rstrip()
        if not line:
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        # Skip section headers that have empty value e.g., "columns:"
        if val == "":
            continue
        # Strip surrounding quotes for strings
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            sval = val[1:-1]
        else:
            sval = val
        # Try to parse as int or float
        parsed: Any = sval
        if re.fullmatch(r"[-+]?\d+", sval):
            try:
                parsed = int(sval)
            except Exception:
                parsed = sval
        elif re.fullmatch(r"[-+]?\d*\.\d+", sval):
            try:
                parsed = float(sval)
            except Exception:
                parsed = sval
        elif sval.lower() in ("true", "false"):
            parsed = (sval.lower() == "true")
        result[key] = parsed
    return result


def _parse_columns_mapping(yaml_path: Path) -> Optional[Dict[str, str]]:
    """
    Parse a simple mapping under a top-level 'columns:' key, e.g.:
    columns:
      Full Name: name
      Email: email
    Returns dict mapping source column to normalized key.
    """
    text = _read_text(yaml_path)
    if text is None:
        return None
    lines = text.splitlines()
    mapping: Dict[str, str] = {}
    in_columns = False
    base_indent = None
    for raw_line in lines:
        if not in_columns:
            stripped = raw_line.strip()
            if stripped.startswith("#") or stripped == "":
                continue
            if re.match(r"^\s*columns\s*:\s*$", raw_line):
                in_columns = True
                base_indent = len(raw_line) - len(raw_line.lstrip(" "))
                continue
        else:
            if raw_line.strip() == "" or raw_line.strip().startswith("#"):
                continue
            current_indent = len(raw_line) - len(raw_line.lstrip(" "))
            if base_indent is not None and current_indent <= base_indent:
                break
            line = raw_line.strip()
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            mapping[key] = val
    if not in_columns:
        return None
    return mapping


def _import_module_from_path(mod_name: str, file_path: Path):
    try:
        spec = importlib.util.spec_from_file_location(mod_name, str(file_path))
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[attr-defined]
        return module
    except Exception:
        return None


def _safe_parse_iso_date(s: str) -> Optional[date]:
    try:
        s2 = (s or "").strip()
        if not s2:
            return None
        return date.fromisoformat(s2)
    except Exception:
        return None


def _read_roster_with_mapping(csv_path: Path, fieldmap_path: Path, parse_date_func) -> Optional[List[Dict[str, Any]]]:
    mapping = _parse_columns_mapping(fieldmap_path)
    if mapping is None:
        return None
    try:
        with csv_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            records: List[Dict[str, Any]] = []
            for row in reader:
                rec: Dict[str, Any] = {}
                for src_col, norm_key in mapping.items():
                    raw = (row.get(src_col) or "").strip()
                    if norm_key == "hours_q1":
                        try:
                            rec[norm_key] = float(raw)
                        except Exception:
                            rec[norm_key] = 0.0
                    elif norm_key == "bg_check_date":
                        rec[norm_key] = parse_date_func(raw)
                    else:
                        rec[norm_key] = raw
                # Ensure all expected keys exist even if missing in CSV
                for k in ["name", "email", "unit", "rank", "hours_q1", "bg_check_date"]:
                    if k not in rec:
                        if k == "hours_q1":
                            rec[k] = 0.0
                        elif k == "bg_check_date":
                            rec[k] = None
                        else:
                            rec[k] = ""
                records.append(rec)
            return records
    except Exception:
        return None


def _parse_junit_xml(path: Path) -> Tuple[int, int, int]:
    """
    Return (tests, failures, errors). If parsing fails, return (0, 1, 1) to reflect a failing status.
    """
    try:
        tree = ET.parse(str(path))
        root = tree.getroot()
        total_tests = 0
        total_failures = 0
        total_errors = 0
        if root.tag == "testsuite":
            tests = int(root.attrib.get("tests", "0"))
            failures = int(root.attrib.get("failures", "0"))
            errors = int(root.attrib.get("errors", "0"))
            total_tests += tests
            total_failures += failures
            total_errors += errors
        elif root.tag == "testsuites":
            for ts in root.findall("testsuite"):
                tests = int(ts.attrib.get("tests", "0"))
                failures = int(ts.attrib.get("failures", "0"))
                errors = int(ts.attrib.get("errors", "0"))
                total_tests += tests
                total_failures += failures
                total_errors += errors
        else:
            return (0, 1, 1)
        return (total_tests, total_failures, total_errors)
    except Exception:
        return (0, 1, 1)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    # Paths
    eligibility_py = workspace / "src" / "eligibility.py"
    roster_csv = workspace / "data" / "roster.csv"
    fieldmap_yaml = workspace / "config" / "fieldmap.yaml"
    eligibility_yaml = workspace / "config" / "eligibility.yaml"
    tests_file = workspace / "tests" / "test_eligibility.py"
    junit_xml = workspace / "output" / "test_results.xml"

    scores: Dict[str, float] = {
        "config_reference_date_set": 0.0,
        "config_min_hours_preserved": 0.0,
        "config_bg_years_preserved": 0.0,
        "tests_file_present": 0.0,
        "tests_use_real_files_and_functions": 0.0,
        "tests_include_reference_date_literal": 0.0,
        "tests_cover_all_names": 0.0,
        "tests_cover_all_reasons": 0.0,
        "tests_assert_records_count": 0.0,
        "junit_report_created_and_passing": 0.0,
        "classification_expected_outcomes": 0.0,
    }

    # Load and check config/eligibility.yaml
    cfg = _parse_simple_yaml_kv(eligibility_yaml)
    ref_is_set = False
    if isinstance(cfg, dict):
        # reference_date must be exactly "2022-04-01"
        ref_val = cfg.get("reference_date")
        if isinstance(ref_val, str) and ref_val.strip() == "2022-04-01":
            ref_is_set = True
            scores["config_reference_date_set"] = 1.0
        # Only award preservation checks when reference_date is correctly set (prevents awarding in scaffold)
        if ref_is_set:
            mh = cfg.get("min_hours")
            try:
                if isinstance(mh, (int, float)) and float(mh) == 10.0:
                    scores["config_min_hours_preserved"] = 1.0
            except Exception:
                pass
            by = cfg.get("bg_check_valid_years")
            try:
                if isinstance(by, (int, float)) and int(by) == 2:
                    scores["config_bg_years_preserved"] = 1.0
            except Exception:
                pass

    # Tests file presence and content checks
    tests_content = _read_text(tests_file)
    if tests_content is not None:
        scores["tests_file_present"] = 1.0

        # Ensure tests use local files and core functions
        uses_data = "data/roster.csv" in tests_content
        uses_fieldmap = "config/fieldmap.yaml" in tests_content
        uses_rules = "config/eligibility.yaml" in tests_content
        calls_parse = "parse_roster(" in tests_content
        calls_classify = "classify(" in tests_content
        calls_load_rules = "load_rules(" in tests_content
        if uses_data and uses_fieldmap and uses_rules and calls_parse and calls_classify and calls_load_rules:
            scores["tests_use_real_files_and_functions"] = 1.0

        # Check reference date literal in tests for determinism assertion
        if "2022-04-01" in tests_content:
            scores["tests_include_reference_date_literal"] = 1.0

        # Names coverage
        names = ["Sgt. Alex Rivera", "Jamie Lee", "Morgan Patel", "Taylor Kim", "Jordan Smith"]
        if all(name in tests_content for name in names):
            scores["tests_cover_all_names"] = 1.0

        # Reasons coverage
        reasons = ["low_hours", "missing_email", "expired_bg_check", "invalid_email"]
        if all(reason in tests_content for reason in reasons):
            scores["tests_cover_all_reasons"] = 1.0

        # Assert records count heuristic
        if "== 5" in tests_content or "assert len(" in tests_content and "5" in tests_content:
            scores["tests_assert_records_count"] = 1.0

    # JUnit report checks
    if junit_xml.exists() and junit_xml.is_file():
        tests_count, failures, errors = _parse_junit_xml(junit_xml)
        if tests_count > 0 and failures == 0 and errors == 0:
            scores["junit_report_created_and_passing"] = 1.0

    # Classification outcomes using project code where possible
    # Require that config has the deterministic reference_date set; otherwise do not award this check
    if ref_is_set and eligibility_py.exists() and roster_csv.exists() and fieldmap_yaml.exists() and eligibility_yaml.exists():
        elig_mod = _import_module_from_path("eligibility_mod", eligibility_py)
        if elig_mod is not None:
            parse_date_func = getattr(elig_mod, "_parse_date", _safe_parse_iso_date)
            records = _read_roster_with_mapping(roster_csv, fieldmap_yaml, parse_date_func)
            rules_cfg = _parse_simple_yaml_kv(eligibility_yaml)

            if isinstance(records, list) and isinstance(rules_cfg, dict):
                # Prepare rules for classify
                rules: Dict[str, Any] = {}
                for k in ("min_hours", "bg_check_valid_years", "reference_date"):
                    if k in rules_cfg:
                        rules[k] = rules_cfg[k]
                expected: Dict[str, Tuple[bool, List[str]]] = {
                    "Sgt. Alex Rivera": (True, []),
                    "Jamie Lee": (False, ["low_hours"]),
                    "Morgan Patel": (False, ["expired_bg_check", "missing_email"]),
                    "Taylor Kim": (False, ["expired_bg_check"]),
                    "Jordan Smith": (False, ["invalid_email"]),
                }
                got: Dict[str, Tuple[bool, List[str]]] = {}
                classify_fn = getattr(elig_mod, "classify", None)
                if callable(classify_fn):
                    try:
                        for rec in records:
                            name = rec.get("name", "")
                            active, reasons = classify_fn(rec, rules)
                            got[name] = (bool(active), sorted(list(set(reasons))))
                        names_ok = set(expected.keys()) == set(got.keys())
                        per_name_ok = True
                        for n, (exp_active, exp_reasons) in expected.items():
                            if n not in got:
                                per_name_ok = False
                                break
                            g_active, g_reasons = got[n]
                            if g_active != exp_active:
                                per_name_ok = False
                                break
                            if sorted(exp_reasons) != sorted(g_reasons):
                                per_name_ok = False
                                break
                        active_names = [n for n, (a, _) in got.items() if a]
                        active_one_ok = (len(active_names) == 1 and active_names[0] == "Sgt. Alex Rivera")
                        if names_ok and per_name_ok and active_one_ok:
                            scores["classification_expected_outcomes"] = 1.0
                    except Exception:
                        pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()