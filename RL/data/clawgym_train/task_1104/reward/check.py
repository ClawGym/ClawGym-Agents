import json
import re
import sys
import csv
from pathlib import Path
from typing import Optional, List, Dict, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_array_safe(path: Path) -> Optional[List[Dict]]:
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        if isinstance(data, list):
            return data
        return None
    except Exception:
        return None


def _load_csv_as_dicts_safe(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({k: (v if v is not None else "") for k, v in row.items()})
            return rows
    except Exception:
        return None


def _parse_config_yaml_simple(path: Path) -> Optional[Dict]:
    """
    Minimal parser for the expected YAML structure:
    data_dir: <str>
    default_region: <str>
    allowed_program_types:
      - item1
      - item2
    output:
      json: <str>
      csv: <str>
    """
    text = _read_text_safe(path)
    if text is None:
        return None

    data: Dict[str, object] = {}
    lines = text.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        line = line.rstrip()
        if "#" in line:
            pre, _, _ = line.partition("#")
            line = pre.rstrip()
        if not line.strip():
            i += 1
            continue
        if not line.startswith(" "):
            if line.endswith(":"):
                key = line[:-1].strip()
                if key == "allowed_program_types":
                    items: List[str] = []
                    j = i + 1
                    while j < n:
                        ln = lines[j].rstrip()
                        if "#" in ln:
                            pre, _, _ = ln.partition("#")
                            ln = pre.rstrip()
                        if not ln.strip():
                            j += 1
                            continue
                        if ln.startswith("  - "):
                            items.append(ln.strip()[3:].strip())
                            j += 1
                            continue
                        if not ln.startswith(" "):
                            break
                        else:
                            break
                    data[key] = items
                    i = j
                    continue
                elif key == "output":
                    out: Dict[str, str] = {}
                    j = i + 1
                    while j < n:
                        ln = lines[j].rstrip()
                        if "#" in ln:
                            pre, _, _ = ln.partition("#")
                            ln = pre.rstrip()
                        if not ln.strip():
                            j += 1
                            continue
                        if not ln.startswith("  "):
                            break
                        if ":" in ln:
                            subk, _, subv = ln.strip().partition(":")
                            out[subk.strip()] = subv.strip()
                        j += 1
                    data[key] = out
                    i = j
                    continue
                else:
                    j = i + 1
                    while j < n:
                        ln = lines[j].rstrip()
                        if not ln.strip():
                            j += 1
                            continue
                        if not ln.startswith(" "):
                            break
                        j += 1
                    i = j
                    continue
            else:
                if ":" in line:
                    k, _, v = line.partition(":")
                    data[k.strip()] = v.strip()
                i += 1
                continue
        else:
            i += 1
            continue
    return data


def _parse_html_programs_from_file(path: Path) -> List[Dict[str, Optional[str]]]:
    text = _read_text_safe(path)
    if text is None:
        return []
    programs: List[Dict[str, Optional[str]]] = []
    blocks = re.findall(r'<div class="program">(.*?)</div>', text, flags=re.S)
    for b in blocks:
        name_m = re.search(r'<h2>([^<]+)</h2>', b)
        type_m = re.search(r'class="type">Type:\s*([^<]+)</p>', b)
        sponsor_m = re.search(r'class="sponsor">([^<]+)</p>', b)
        desc_m = re.search(r'class="desc">([^<]+)</p>', b)
        region_m = re.search(r'class="region">Eligible region:\s*([^<]+)</p>', b)
        if not name_m:
            continue
        program = {
            "program_name": name_m.group(1).strip(),
            "sponsor": sponsor_m.group(1).strip() if sponsor_m else "",
            "program_type": type_m.group(1).strip() if type_m else "",
            "description": desc_m.group(1).strip() if desc_m else "",
            "region": region_m.group(1).strip() if region_m else None,
            "source_file": path.name,
        }
        programs.append(program)
    return programs


def _expected_records(workspace: Path, fallback_region: str) -> List[Dict[str, str]]:
    data_dir = workspace / "data" / "pages"
    programs: List[Dict[str, str]] = []
    allowed = {"rebate", "grant", "voucher"}
    if not data_dir.exists():
        return programs
    for fp in sorted(data_dir.iterdir()):
        if fp.is_file() and fp.suffix.lower() == ".html":
            for rec in _parse_html_programs_from_file(fp):
                ptype_raw = rec.get("program_type", "")
                ptype_norm = (ptype_raw or "").strip().lower()
                if ptype_norm in allowed:
                    region_val = rec.get("region")
                    if not region_val:
                        region_val = fallback_region
                    programs.append({
                        "program_name": rec.get("program_name", ""),
                        "sponsor": rec.get("sponsor", ""),
                        "program_type": ptype_raw,
                        "description": rec.get("description", ""),
                        "region": region_val,
                        "source_file": rec.get("source_file", ""),
                    })
    return programs


def _normalize_record_tuple(rec: Dict[str, str]) -> Tuple[str, str, str, str, str, str]:
    return (
        rec.get("program_name", "").strip(),
        rec.get("sponsor", "").strip(),
        rec.get("program_type", "").strip(),
        rec.get("description", "").strip(),
        rec.get("region", "").strip(),
        rec.get("source_file", "").strip(),
    )


def _records_set(records: List[Dict[str, str]]) -> set:
    return {_normalize_record_tuple(r) for r in records}


def _json_has_required_fields(records: List[Dict]) -> bool:
    required = {"program_name", "sponsor", "program_type", "description", "region", "source_file"}
    for rec in records:
        if not isinstance(rec, dict):
            return False
        keys = set(rec.keys())
        if keys != required:
            return False
        for k in required:
            v = rec.get(k)
            if not isinstance(v, str):
                return False
            if not v.strip():
                return False
    return True


def _evaluate_code_review(path: Path) -> bool:
    text = _read_text_safe(path)
    if text is None:
        return False
    lines = [ln.strip().lower() for ln in text.splitlines()]
    bullet_count = sum(1 for ln in lines if ln.startswith("- ") or ln.startswith("* ") or re.match(r"^\d+\.", ln))
    keywords = ["hardcoded", "case", "filter", "path", "csv", "source_file", "config", "allowed", "region", "safe", "brittle", "yaml"]
    found_keywords = set()
    for kw in keywords:
        if kw in text.lower():
            found_keywords.add(kw)
    mentions_refactor = ("refactor" in text.lower()) or ("refactoring" in text.lower()) or ("configuration" in text.lower())
    return (bullet_count >= 3 or len(found_keywords) >= 3) and mentions_refactor


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_allowed_types_updated": 0.0,
        "outputs_exist": 0.0,
        "json_has_required_fields": 0.0,
        "extracted_records_match_expected": 0.0,
        "csv_matches_json": 0.0,
        "script_no_hardcoded_constants": 0.0,
        "script_reads_config": 0.0,
        "code_review_covers_issues": 0.0,
    }

    cfg_path = workspace / "config" / "config.yaml"
    cfg = _parse_config_yaml_simple(cfg_path) if cfg_path.exists() else None
    if isinstance(cfg, dict):
        allowed_cfg = cfg.get("allowed_program_types")
        if isinstance(allowed_cfg, list):
            normalized = sorted([str(x).strip().lower() for x in allowed_cfg])
            if set(normalized) == {"rebate", "grant", "voucher"} and len(normalized) == 3:
                scores["config_allowed_types_updated"] = 1.0

    json_path = workspace / "workspace" / "output" / "programs.json"
    csv_path = workspace / "workspace" / "output" / "programs.csv"
    code_review_path = workspace / "workspace" / "output" / "CODE_REVIEW.md"
    if json_path.exists() and csv_path.exists():
        scores["outputs_exist"] = 1.0

    json_records = _load_json_array_safe(json_path) if json_path.exists() else None
    if isinstance(json_records, list) and json_records:
        if _json_has_required_fields(json_records):
            scores["json_has_required_fields"] = 1.0

    fallback_region = "Greenfield County"
    if isinstance(cfg, dict):
        dr = cfg.get("default_region")
        if isinstance(dr, str) and dr.strip():
            fallback_region = dr.strip()
    expected = _expected_records(workspace, fallback_region)
    if isinstance(json_records, list) and expected:
        set_json = _records_set(json_records)
        set_expected = _records_set(expected)
        if set_json == set_expected:
            scores["extracted_records_match_expected"] = 1.0

    csv_records = _load_csv_as_dicts_safe(csv_path) if csv_path.exists() else None
    if isinstance(csv_records, list) and isinstance(json_records, list) and json_records:
        required_cols = {"program_name", "sponsor", "program_type", "description", "region", "source_file"}
        if csv_records:
            header_cols = set(csv_records[0].keys())
            if header_cols == required_cols:
                set_csv = _records_set(csv_records)
                set_json = _records_set(json_records)
                if set_csv == set_json:
                    scores["csv_matches_json"] = 1.0

    script_path = workspace / "scripts" / "extract.py"
    script_text = _read_text_safe(script_path) if script_path.exists() else None
    if isinstance(script_text, str):
        has_constants = bool(re.search(r"^\s*(DATA_DIR|KEYWORDS|REGION)\s*=", script_text, flags=re.M))
        refers_build = ("build/programs.json" in script_text) or ('os.makedirs("build"' in script_text) or ("build/" in script_text)
        unsafe_html_filter = ('.html" in fn' in script_text) or ('".html" in fn' in script_text)
        if not has_constants and not refers_build and not unsafe_html_filter:
            scores["script_no_hardcoded_constants"] = 1.0
        reads_config = ("config.yaml" in script_text) or ("config/config.yaml" in script_text)
        if reads_config:
            scores["script_reads_config"] = 1.0

    if code_review_path.exists() and _evaluate_code_review(code_review_path):
        scores["code_review_covers_issues"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()