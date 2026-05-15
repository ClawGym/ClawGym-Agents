import csv
import json
import re
import sys
import ast
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            try:
                sample = f.read(4096)
                f.seek(0)
            except Exception:
                sample = ""
                f.seek(0)
            dialect = csv.excel
            try:
                if sample:
                    dialect = csv.Sniffer().sniff(sample)
            except Exception:
                pass
            reader = csv.DictReader(f, dialect=dialect)
            rows = [dict({k: (v if v is not None else "") for k, v in row.items()}) for row in reader]
            headers = reader.fieldnames or []
            return headers, rows
    except Exception:
        return None, None


def _parse_simple_yaml(yaml_text: str) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    for raw_line in yaml_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        parts_comment = line.split(" #", 1)
        line = parts_comment[0].strip()
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        if val == "":
            data[key] = ""
            continue
        if val.startswith("[") and val.endswith("]"):
            try:
                parsed = ast.literal_eval(val)
                if isinstance(parsed, list):
                    parsed_list = []
                    for item in parsed:
                        if isinstance(item, str):
                            parsed_list.append(item)
                        else:
                            parsed_list.append(str(item))
                    data[key] = parsed_list
                else:
                    data[key] = []
            except Exception:
                data[key] = []
            continue
        low = val.lower()
        if low == "true":
            data[key] = True
            continue
        if low == "false":
            data[key] = False
            continue
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            data[key] = val[1:-1]
        else:
            data[key] = val
    return data


def _normalize_hex_to_int(value: str) -> Optional[int]:
    if value is None:
        return None
    s = value.strip()
    if not s:
        return None
    s_low = s.lower()
    if s_low.startswith("0x"):
        s_low = s_low[2:]
    if re.fullmatch(r"[0-9a-f]+", s_low):
        try:
            return int(s_low, 16)
        except Exception:
            return None
    m2 = re.search(r"0x[0-9a-fA-F]+", s)
    if m2:
        try:
            return int(m2.group(0), 16)
        except Exception:
            return None
    return None


def _find_header_key(fieldnames: List[str], target: str) -> Optional[str]:
    target_lower = target.strip().lower()
    for name in fieldnames:
        if name is None:
            continue
        if name.strip().lower() == target_lower:
            return name
    return None


def _get_case_insensitive_value(row: Dict[str, str], fieldnames: List[str], target: str) -> Optional[str]:
    key = _find_header_key(fieldnames, target)
    if key is None:
        lowered = {k.strip().lower(): k for k in row.keys() if k is not None}
        if target.strip().lower() in lowered:
            key = lowered[target.strip().lower()]
    if key is None:
        return None
    return row.get(key, "")


def _is_recommended_flag(val: Optional[str]) -> bool:
    if val is None:
        return False
    s = str(val).strip().lower()
    return s in {"y", "yes"}


def _normalized_name(desc: Optional[str]) -> str:
    if not desc:
        return ""
    s = desc.lower()
    s_ascii = "".join(ch if ord(ch) < 128 else " " for ch in s)
    s_hy = re.sub(r"[^a-z0-9]+", "-", s_ascii)
    s_hy = re.sub(r"-{2,}", "-", s_hy).strip("-")
    return s_hy


def _parse_iana_registry(path: Path) -> Tuple[bool, Dict[int, Dict[str, str]]]:
    headers, rows = _load_csv_dicts(path)
    if headers is None or rows is None:
        return False, {}
    has_value = any((h or "").strip().lower() == "value" for h in headers)
    has_desc = any((h or "").strip().lower() == "description" for h in headers)
    has_rec = any((h or "").strip().lower() == "recommended" for h in headers)
    if not (has_value and has_desc and has_rec):
        return False, {}
    mapping: Dict[int, Dict[str, str]] = {}
    for row in rows:
        value_str = _get_case_insensitive_value(row, headers, "Value")
        desc = _get_case_insensitive_value(row, headers, "Description") or ""
        rec = _get_case_insensitive_value(row, headers, "Recommended") or ""
        val_int = _normalize_hex_to_int(value_str or "")
        if val_int is None:
            continue
        if val_int not in mapping:
            mapping[val_int] = {"Description": desc, "Recommended": rec}
    return True, mapping


def _load_input_suites(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    headers, rows = _load_csv_dicts(path)
    if headers is None or rows is None:
        return None, None
    header_map = {h.strip().lower(): h for h in headers if h is not None}
    if not all(col in header_map for col in ["hex_value", "note"]):
        return None, None
    ordered_rows = []
    ordered_hexes = []
    for r in rows:
        hex_val = r.get(header_map["hex_value"], "")
        note = r.get(header_map["note"], "")
        ordered_rows.append({"hex_value": hex_val, "note": note})
        ordered_hexes.append(hex_val)
    return ordered_rows, ordered_hexes


def _load_yaml_config(path: Path) -> Optional[Dict[str, Any]]:
    text = _read_text(path)
    if text is None:
        return None
    try:
        return _parse_simple_yaml(text)
    except Exception:
        return None


def _compute_expected_enriched(input_rows: List[Dict[str, str]], iana_map: Dict[int, Dict[str, str]]) -> List[Dict[str, str]]:
    enriched = []
    for r in input_rows:
        hex_value = r.get("hex_value", "")
        note = r.get("note", "")
        val_int = _normalize_hex_to_int(hex_value)
        desc = ""
        rec = ""
        if val_int is not None and val_int in iana_map:
            desc = iana_map[val_int].get("Description", "") or ""
            rec = iana_map[val_int].get("Recommended", "") or ""
        norm_name = _normalized_name(desc)
        enriched.append({
            "hex_value": hex_value,
            "iana_description": desc,
            "iana_recommended": rec,
            "note": note,
            "normalized_name": norm_name,
        })
    return enriched


def _parse_csv_to_rows_by_header(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    return _load_csv_dicts(path)


def _rows_index_by_hex(rows: List[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    idx: Dict[str, Dict[str, str]] = {}
    for r in rows:
        hv = r.get("hex_value", "")
        idx[hv.strip().lower()] = r
    return idx


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "registry_csv_valid": 0.0,
        "enriched_csv_columns_order": 0.0,
        "enriched_rows_match_join": 0.0,
        "normalized_name_correct": 0.0,
        "config_sibling_name_set": 0.0,
        "config_output_fields_exact": 0.0,
        "config_include_recommended_only_retained": 0.0,
        "config_highlight_keywords_unchanged": 0.0,
        "recommended_csv_columns_match_config": 0.0,
        "recommended_filtering_correct": 0.0,
        "email_greeting_includes_name": 0.0,
        "email_sentence_count_valid": 0.0,
        "email_references_output_paths": 0.0,
        "email_bullet_list_covers_recommended": 0.0,
    }

    registry_path = workspace / "downloads" / "iana_tls_cipher_suites.csv"
    input_path = workspace / "input" / "tls_suites.csv"
    enriched_path = workspace / "out" / "tls_suites_enriched.csv"
    recommended_path = workspace / "out" / "tls_suites_recommended.csv"
    email_path = workspace / "out" / "email_to_sibling.txt"
    config_path = workspace / "config" / "filters.yaml"

    # Load registry
    registry_ok, iana_map = _parse_iana_registry(registry_path)
    if registry_ok:
        scores["registry_csv_valid"] = 1.0

    # Load input
    input_rows, input_hexes = _load_input_suites(input_path)

    # Compute expected enriched
    expected_enriched: List[Dict[str, str]] = []
    if input_rows is not None and registry_ok:
        expected_enriched = _compute_expected_enriched(input_rows, iana_map)

    # Verify enriched CSV
    enriched_headers, enriched_rows = _parse_csv_to_rows_by_header(enriched_path)
    required_enriched_columns = ["hex_value", "iana_description", "iana_recommended", "note", "normalized_name"]
    if enriched_headers is not None and enriched_rows is not None:
        if enriched_headers == required_enriched_columns:
            scores["enriched_csv_columns_order"] = 1.0

        if expected_enriched:
            actual_idx = _rows_index_by_hex(enriched_rows)
            expected_hex_set = {e["hex_value"].strip().lower() for e in expected_enriched}
            actual_hex_set = {r.get("hex_value", "").strip().lower() for r in enriched_rows}
            join_match = (expected_hex_set == actual_hex_set)
            fields_match = True
            norm_match = True
            if join_match:
                for exp in expected_enriched:
                    key = exp["hex_value"].strip().lower()
                    act = actual_idx.get(key)
                    if act is None:
                        fields_match = False
                        norm_match = False
                        break
                    if (act.get("iana_description", "") != exp["iana_description"] or
                        act.get("iana_recommended", "") != exp["iana_recommended"] or
                        act.get("note", "") != exp["note"]):
                        fields_match = False
                    if (act.get("normalized_name", "") != exp["normalized_name"]):
                        norm_match = False
            else:
                fields_match = False
                norm_match = False

            if fields_match and join_match:
                scores["enriched_rows_match_join"] = 1.0
            if norm_match and join_match:
                scores["normalized_name_correct"] = 1.0

    # Load and validate config
    cfg = _load_yaml_config(config_path)
    sibling_ok = False
    fields_ok = False
    if cfg is not None:
        if str(cfg.get("sibling_name", "")).strip() == "Riley":
            scores["config_sibling_name_set"] = 1.0
            sibling_ok = True

        output_fields = cfg.get("output_fields", None)
        if isinstance(output_fields, list) and output_fields == ["hex_value", "iana_description", "iana_recommended", "note"]:
            scores["config_output_fields_exact"] = 1.0
            fields_ok = True

        if sibling_ok and fields_ok:
            if cfg.get("include_recommended_only", None) is True:
                scores["config_include_recommended_only_retained"] = 1.0
            hk = cfg.get("highlight_keywords", None)
            if isinstance(hk, list) and hk == ["AES", "CHACHA20", "GCM"]:
                scores["config_highlight_keywords_unchanged"] = 1.0

    # Verify recommended CSV structure matches config and filtering correctness
    rec_headers, rec_rows = _parse_csv_to_rows_by_header(recommended_path)
    if cfg is not None and isinstance(cfg.get("output_fields", None), list) and rec_headers is not None:
        if rec_headers == cfg["output_fields"]:
            scores["recommended_csv_columns_match_config"] = 1.0

    if expected_enriched:
        expected_recommended = [e for e in expected_enriched if _is_recommended_flag(e.get("iana_recommended", ""))]
        cols_for_recommended = None
        if cfg is not None and isinstance(cfg.get("output_fields", None), list) and cfg["output_fields"]:
            cols_for_recommended = cfg["output_fields"]
        else:
            cols_for_recommended = ["hex_value", "iana_description", "iana_recommended", "note"]

        expected_set = set()
        for e in expected_recommended:
            tup = tuple(e.get(c, "") for c in cols_for_recommended)
            expected_set.add(tup)

        if rec_rows is not None and rec_headers is not None and rec_headers == cols_for_recommended:
            actual_set = set()
            for r in rec_rows:
                tup = tuple(r.get(c, "") for c in cols_for_recommended)
                actual_set.add(tup)
            if expected_set == actual_set:
                scores["recommended_filtering_correct"] = 1.0

    # Email checks
    email_text = _read_text(email_path)
    if email_text is not None and cfg is not None:
        sibling_name = str(cfg.get("sibling_name", "")).strip()
        lines = [ln.rstrip("\n\r") for ln in email_text.splitlines()]
        first_nonempty_idx = None
        for i, ln in enumerate(lines):
            if ln.strip():
                first_nonempty_idx = i
                break
        greeting_ok = False
        if first_nonempty_idx is not None:
            first_line = lines[first_nonempty_idx]
            if sibling_name and sibling_name in first_line:
                greeting_ok = True
        if greeting_ok:
            scores["email_greeting_includes_name"] = 1.0

        non_bullet_text_parts = []
        for ln in lines:
            if re.match(r"^\s*[-*\u2022]\s+", ln):
                continue
            non_bullet_text_parts.append(ln)
        non_bullet_text = " ".join(non_bullet_text_parts)
        sentence_candidates = re.split(r"[.!?]+", non_bullet_text)
        sentences = [s.strip() for s in sentence_candidates if s.strip()]
        if 3 <= len(sentences) <= 6:
            scores["email_sentence_count_valid"] = 1.0

        refs_ok = ("out/tls_suites_enriched.csv" in email_text) and ("out/tls_suites_recommended.csv" in email_text)
        if refs_ok:
            scores["email_references_output_paths"] = 1.0

        bullet_lines = [ln for ln in lines if re.match(r"^\s*[-*\u2022]\s+", ln)]
        bullet_ok = False
        if expected_enriched:
            rec_items = [e for e in expected_enriched if _is_recommended_flag(e.get("iana_recommended", ""))]
            if not rec_items:
                bullet_ok = True
            else:
                def line_hex_ints(ln: str) -> List[int]:
                    ints = []
                    for m in re.finditer(r"0x[0-9a-fA-F]+", ln):
                        try:
                            ints.append(int(m.group(0), 16))
                        except Exception:
                            pass
                    return ints

                covered = 0
                for e in rec_items:
                    hex_str = e.get("hex_value", "")
                    val_int = _normalize_hex_to_int(hex_str)
                    name1 = e.get("normalized_name", "")
                    name2 = e.get("iana_description", "")
                    found = False
                    for bl in bullet_lines:
                        ints_in_line = line_hex_ints(bl)
                        if val_int is not None and val_int in ints_in_line:
                            if (name1 and name1.lower() in bl.lower()) or (name2 and name2.lower() in bl.lower()):
                                found = True
                                break
                    if found:
                        covered += 1
                bullet_ok = (covered == len(rec_items))
        if bullet_ok:
            scores["email_bullet_list_covers_recommended"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()