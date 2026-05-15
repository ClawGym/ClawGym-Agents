import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zipfile import ZipFile, BadZipFile


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_json_load(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _is_iso8601(dt: Any) -> bool:
    if not isinstance(dt, str):
        return False
    s = dt.strip()
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        datetime.fromisoformat(s2)
        return True
    except Exception:
        pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$"
        return re.match(pattern, s) is not None


def _count_leading_spaces(s: str) -> int:
    return len(s) - len(s.lstrip(' '))


def _parse_scalar(value: str) -> Any:
    v = value.strip()
    if (len(v) >= 2 and ((v[0] == '"' and v[-1] == '"') or (v[0] == "'" and v[-1] == "'"))):
        v = v[1:-1]
    try:
        if re.fullmatch(r"[+-]?\d+", v):
            return int(v)
        if re.fullmatch(r"[+-]?\d*\.\d+(?:[eE][+-]?\d+)?", v) or re.fullmatch(r"[+-]?\d+\.(?:[eE][+-]?\d+)?", v) or re.fullmatch(r"[+-]?\d+(?:[eE][+-]?\d+)", v):
            return float(v)
    except Exception:
        pass
    return v


def _load_simple_yaml(path: Path) -> Optional[dict]:
    text = _read_text(path)
    if text is None:
        return None
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    raw_lines = text.splitlines()
    lines = []
    for ln in raw_lines:
        if ln.strip().startswith("#"):
            continue
        lines.append(ln.rstrip("\n\r"))
    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Any]] = [(-1, root)]
    i = 0

    def peek_next(idx: int) -> Optional[Tuple[int, str]]:
        j = idx + 1
        while j < len(lines):
            l2 = lines[j]
            if l2.strip() == "" or l2.strip().startswith("#"):
                j += 1
                continue
            ind2 = _count_leading_spaces(l2)
            return ind2, l2[ind2:]
        return None

    while i < len(lines):
        raw = lines[i]
        if raw.strip() == "" or raw.strip().startswith("#"):
            i += 1
            continue
        indent = _count_leading_spaces(raw)
        content = raw[indent:]

        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            return None
        parent = stack[-1][1]

        if content.startswith("- "):
            if not isinstance(parent, list):
                return None
            value_str = content[2:].strip()
            if value_str == "":
                parent.append(None)
            else:
                parent.append(_parse_scalar(value_str))
            i += 1
            continue

        if ":" in content:
            key, rest = content.split(":", 1)
            key = key.strip()
            rest = rest.lstrip()
            if rest == "":
                peek = peek_next(i)
                if peek is not None:
                    next_indent, next_content = peek
                    if next_indent > indent and next_content.startswith("- "):
                        new_cont: Any = []
                    else:
                        new_cont = {}
                else:
                    new_cont = {}
                if isinstance(parent, dict):
                    parent[key] = new_cont
                else:
                    return None
                stack.append((indent, new_cont))
                i += 1
                continue
            else:
                val = _parse_scalar(rest)
                if isinstance(parent, dict):
                    parent[key] = val
                else:
                    return None
                i += 1
                continue
        else:
            return None

    return root


def _read_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            first_line = f.readline()
            if first_line == "":
                return None, None
            f.seek(0)
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return None, None
            f.seek(0)
            dr = csv.DictReader(f)
            rows = [row for row in dr]
            return header, rows
    except Exception:
        return None, None


def _to_float(x: Any) -> Optional[float]:
    try:
        if isinstance(x, (int, float)):
            return float(x)
        if isinstance(x, str):
            xs = x.strip()
            if xs == "":
                return None
            return float(xs)
    except Exception:
        return None
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores: Dict[str, float] = {
        "raw_zip_exists_and_valid_zip": 0.0,
        "extracted_shapefile_components_present": 0.0,
        "country_density_csv_exists_and_columns": 0.0,
        "csv_row_count_positive": 0.0,
        "csv_column_types_valid": 0.0,
        "continents_allowed_values": 0.0,
        "required_iso_a3_present": 0.0,
        "numeric_constraints_satisfied": 0.0,
        "density_values_within_tolerance": 0.0,
        "metadata_json_exists_and_keys": 0.0,
        "metadata_values_correct": 0.0,
        "metadata_record_count_matches": 0.0,
        "validation_script_exists": 0.0,
        "validation_report_exists_and_successful": 0.0,
    }

    zip_path = workspace / "data" / "raw" / "ne_110m_admin_0_countries.zip"
    extracted_dir = workspace / "data" / "extracted"
    csv_path = workspace / "output" / "country_density.csv"
    metadata_path = workspace / "output" / "metadata.json"
    validator_path = workspace / "tests" / "validate_output.py"
    report_path = workspace / "output" / "validation_report.txt"
    yaml_path = workspace / "input" / "validation.yaml"

    cfg = _load_simple_yaml(yaml_path)

    zip_ok = False
    if zip_path.exists() and zip_path.is_file():
        try:
            with ZipFile(zip_path, "r") as zf:
                names = zf.namelist()
                prefix = "ne_110m_admin_0_countries"
                required_exts = {".shp", ".shx", ".dbf", ".prj"}
                found_exts = set()
                for n in names:
                    base = Path(n).name
                    if base.startswith(prefix):
                        ext = Path(base).suffix.lower()
                        if ext in required_exts:
                            found_exts.add(ext)
                if required_exts.issubset(found_exts):
                    zip_ok = True
        except (BadZipFile, Exception):
            zip_ok = False
    scores["raw_zip_exists_and_valid_zip"] = 1.0 if zip_ok else 0.0

    extracted_ok = False
    if extracted_dir.exists() and extracted_dir.is_dir():
        prefix = "ne_110m_admin_0_countries"
        required_exts = {".shp", ".shx", ".dbf", ".prj"}
        present_exts = set()
        try:
            for p in extracted_dir.rglob("*"):
                if p.is_file() and p.name.startswith(prefix) and p.suffix.lower() in required_exts:
                    present_exts.add(p.suffix.lower())
            if required_exts.issubset(present_exts):
                extracted_ok = True
        except Exception:
            extracted_ok = False
    scores["extracted_shapefile_components_present"] = 1.0 if extracted_ok else 0.0

    header, rows = _read_csv(csv_path)
    required_columns: List[str] = []
    column_types: Dict[str, str] = {}
    allowed_continents: List[str] = []
    required_iso_a3: List[str] = []
    density_tolerance: Optional[float] = None
    numeric_constraints: Dict[str, Dict[str, Any]] = {}

    if cfg is not None:
        try:
            required_columns = list(cfg.get("required_columns", []))
            column_types = dict(cfg.get("column_types", {}))
            allowed_continents = list(cfg.get("allowed_continents", []))
            required_iso_a3 = list(cfg.get("required_iso_a3", []))
            density_tolerance = _to_float(cfg.get("density_tolerance"))
            numeric_constraints = dict(cfg.get("numeric_constraints", {}))
        except Exception:
            pass

    csv_columns_ok = False
    if header is not None:
        try:
            csv_columns_ok = (required_columns and header == required_columns)
        except Exception:
            csv_columns_ok = False
    scores["country_density_csv_exists_and_columns"] = 1.0 if csv_columns_ok else 0.0

    row_count_ok = False
    if rows is not None:
        try:
            row_count_ok = len(rows) > 0
        except Exception:
            row_count_ok = False
    scores["csv_row_count_positive"] = 1.0 if row_count_ok else 0.0

    col_types_ok = False
    if rows is not None and header is not None and column_types:
        try:
            def row_types_ok(row: Dict[str, str]) -> bool:
                for col, typ in column_types.items():
                    if col not in row:
                        return False
                    val = row[col]
                    if typ == "number":
                        if _to_float(val) is None:
                            return False
                    elif typ == "str":
                        if not isinstance(val, str):
                            return False
                    else:
                        return False
                return True

            col_types_ok = all(row_types_ok(r) for r in rows)
        except Exception:
            col_types_ok = False
    scores["csv_column_types_valid"] = 1.0 if col_types_ok else 0.0

    continents_ok = False
    if rows is not None and allowed_continents and "continent" in (header or []):
        try:
            continents_ok = all((r.get("continent") in allowed_continents) for r in rows)
        except Exception:
            continents_ok = False
    scores["continents_allowed_values"] = 1.0 if continents_ok else 0.0

    iso_ok = False
    if rows is not None and required_iso_a3 and "iso_a3" in (header or []):
        try:
            present = {r.get("iso_a3") for r in rows}
            iso_ok = all(code in present for code in required_iso_a3)
        except Exception:
            iso_ok = False
    scores["required_iso_a3_present"] = 1.0 if iso_ok else 0.0

    numeric_ok = False
    if rows is not None and numeric_constraints:
        try:
            def check_constraint(value: Optional[float], rules: Dict[str, Any]) -> bool:
                if value is None:
                    return False
                for k, v in rules.items():
                    num = _to_float(v)
                    if num is None:
                        return False
                    if k == "gt":
                        if not (value > num):
                            return False
                    elif k == "gte":
                        if not (value >= num):
                            return False
                    elif k == "lt":
                        if not (value < num):
                            return False
                    elif k == "lte":
                        if not (value <= num):
                            return False
                    else:
                        return False
                return True

            numeric_ok = True
            for r in rows:
                for col, rules in numeric_constraints.items():
                    v = _to_float(r.get(col))
                    if not check_constraint(v, rules):
                        numeric_ok = False
                        break
                if not numeric_ok:
                    break
        except Exception:
            numeric_ok = False
    scores["numeric_constraints_satisfied"] = 1.0 if numeric_ok else 0.0

    density_ok = False
    if rows is not None and density_tolerance is not None:
        try:
            density_ok = True
            for r in rows:
                a = _to_float(r.get("area_km2"))
                p = _to_float(r.get("pop_est"))
                d = _to_float(r.get("pop_density_per_km2"))
                if a is None or p is None or d is None:
                    density_ok = False
                    break
                if a == 0.0:
                    density_ok = False
                    break
                calc = p / a
                if abs(calc - d) > density_tolerance:
                    density_ok = False
                    break
        except Exception:
            density_ok = False
    scores["density_values_within_tolerance"] = 1.0 if density_ok else 0.0

    metadata = _safe_json_load(metadata_path)
    meta_keys_ok = False
    meta_values_ok = False
    meta_count_ok = False
    if cfg is not None:
        try:
            meta_req = cfg.get("metadata_requirements", {})
            must_have_keys = list(meta_req.get("must_have_keys", []))
            required_source_name = meta_req.get("source_name")
            required_data_scale = meta_req.get("data_scale")
        except Exception:
            must_have_keys = []
            required_source_name = None
            required_data_scale = None
    else:
        must_have_keys = []
        required_source_name = None
        required_data_scale = None

    if metadata is not None and isinstance(metadata, dict):
        required_keys = {"source_name", "data_scale"}
        required_keys.update(set(must_have_keys))
        meta_keys_ok = all(k in metadata for k in required_keys)
        if meta_keys_ok:
            if required_source_name is None or required_data_scale is None:
                meta_values_ok = False
            else:
                ok = True
                ok = ok and (metadata.get("source_name") == required_source_name)
                ok = ok and (str(metadata.get("data_scale")) == str(required_data_scale))
                expected_filename = "ne_110m_admin_0_countries.zip"
                file_name_val = metadata.get("file_name")
                ok = ok and (isinstance(file_name_val, str) and file_name_val == expected_filename)
                ok = ok and _is_iso8601(metadata.get("downloaded_at"))
                meta_values_ok = bool(ok)
            if rows is not None:
                rec = metadata.get("record_count")
                try:
                    rec_int = int(rec)
                    meta_count_ok = (rec_int == len(rows))
                except Exception:
                    meta_count_ok = False
            else:
                meta_count_ok = False
        else:
            meta_values_ok = False
            meta_count_ok = False
    else:
        meta_keys_ok = False
        meta_values_ok = False
        meta_count_ok = False

    scores["metadata_json_exists_and_keys"] = 1.0 if meta_keys_ok else 0.0
    scores["metadata_values_correct"] = 1.0 if meta_values_ok else 0.0
    scores["metadata_record_count_matches"] = 1.0 if meta_count_ok else 0.0

    validation_script_ok = validator_path.exists() and validator_path.is_file()
    scores["validation_script_exists"] = 1.0 if validation_script_ok else 0.0

    report_ok = False
    if report_path.exists() and report_path.is_file():
        txt = _read_text(report_path) or ""
        if txt.strip():
            low = txt.lower()
            has_success_word = ("success" in low) or ("passed" in low)
            has_fail_word = ("fail" in low) or ("error" in low) or ("traceback" in low)
            report_ok = has_success_word and not has_fail_word
    scores["validation_report_exists_and_successful"] = 1.0 if report_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()