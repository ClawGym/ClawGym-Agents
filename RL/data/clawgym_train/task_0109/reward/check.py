import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text)
    except Exception:
        return None


def _compute_md5(path: Path) -> Optional[str]:
    try:
        h = hashlib.md5()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _is_iso8601(s: Any) -> bool:
    if not isinstance(s, str) or not s:
        return False
    val = s.strip()
    # allow 'Z' timezone by replacing with +00:00 for parsing
    val = val.replace("Z", "+00:00")
    try:
        datetime.fromisoformat(val)
        return True
    except Exception:
        return False


def _parse_config_yaml(path: Path) -> Tuple[Optional[List[int]], Optional[str], bool]:
    """
    Minimal, safe parser for the expected YAML structure:
    openml:
      dataset_ids: [61, 1461, 40945]
      output_root: workspace
    Also supports block list:
      dataset_ids:
        - 61
        - 1461
        - 40945
    Returns (dataset_ids, output_root, has_urls_literal_in_config_text)
    """
    text = _read_text(path)
    if text is None:
        return None, None, False
    has_urls = ("http://" in text) or ("https://" in text)

    lines = text.splitlines()
    # Find "openml:" top-level
    openml_idx = None
    for i, line in enumerate(lines):
        if re.match(r'^\s*openml\s*:\s*$', line):
            openml_idx = i
            break
    if openml_idx is None:
        return None, None, has_urls

    # Determine indentation for child keys
    def indent_of(s: str) -> int:
        return len(s) - len(s.lstrip(" "))

    base_indent = indent_of(lines[openml_idx])
    child_indent = None
    dataset_ids: Optional[List[int]] = None
    output_root: Optional[str] = None

    i = openml_idx + 1
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        ind = indent_of(line)
        if ind <= base_indent:
            # end of openml section
            break
        # set child indent if not set
        if child_indent is None:
            child_indent = ind
        # only parse immediate children and their nested values
        if ind != child_indent and (dataset_ids is None or output_root is None):
            # Might be nested under a key like dataset_ids:
            pass

        # Parse output_root
        m_out = re.match(r'^\s*output_root\s*:\s*([^\n#]+)', line)
        if m_out:
            val = m_out.group(1).strip()
            val = val.strip().strip('"').strip("'")
            output_root = val

        # Parse dataset_ids (inline or start of block)
        m_ids_inline = re.match(r'^\s*dataset_ids\s*:\s*\[(.*)\]\s*(?:#.*)?$', line)
        if m_ids_inline:
            content = m_ids_inline.group(1).strip()
            ids: List[int] = []
            if content:
                parts = [p.strip() for p in content.split(",")]
                for p in parts:
                    p_clean = p.strip().strip('"').strip("'")
                    if p_clean == "":
                        continue
                    try:
                        ids.append(int(p_clean))
                    except Exception:
                        return None, output_root, has_urls
            dataset_ids = ids
            i += 1
            continue

        m_ids_block = re.match(r'^\s*dataset_ids\s*:\s*$', line)
        if m_ids_block:
            # Read subsequent lines with greater indent that start with '-'
            ids: List[int] = []
            j = i + 1
            while j < len(lines):
                l2 = lines[j]
                if not l2.strip():
                    j += 1
                    continue
                ind2 = indent_of(l2)
                if ind2 <= indent_of(line):
                    break
                m_item = re.match(r'^\s*-\s*([^\n#]+)', l2)
                if m_item:
                    val = m_item.group(1).strip()
                    val = val.strip().strip('"').strip("'")
                    try:
                        ids.append(int(val))
                    except Exception:
                        return None, output_root, has_urls
                j += 1
            dataset_ids = ids
            i = j
            continue

        i += 1

    return dataset_ids, output_root, has_urls


def _safe_read_csv_dicts(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = [row for row in reader]
            return header, rows
    except Exception:
        return None, None


def _list_all_files_recursive(base: Path) -> List[Path]:
    if not base.exists():
        return []
    try:
        return [p for p in base.rglob("*") if p.is_file()]
    except Exception:
        return []


def _find_file_by_name(base: Path, filename: str) -> Optional[Path]:
    for p in _list_all_files_recursive(base):
        if p.name == filename:
            return p
    return None


def _sum_raw_bytes_under_dataset_dir(dataset_dir: Path) -> int:
    total = 0
    for p in _list_all_files_recursive(dataset_dir):
        if p.name == "download_manifest.json":
            continue
        try:
            total += p.stat().st_size
        except Exception:
            return -1
    return total


def _parse_int(s: Any) -> Optional[int]:
    try:
        if s is None:
            return None
        if isinstance(s, int):
            return s
        return int(str(s))
    except Exception:
        return None


def _parse_float(s: Any) -> Optional[float]:
    try:
        if s is None:
            return None
        if isinstance(s, float):
            return s
        return float(str(s))
    except Exception:
        return None


def _validate_manifest(manifest_path: Path, dataset_dir: Path, expected_id: int) -> bool:
    data = _safe_load_json(manifest_path)
    if not isinstance(data, dict):
        return False
    # Required fields
    if data.get("source_id") != expected_id:
        return False
    dataset_name = data.get("dataset_name")
    if not isinstance(dataset_name, str) or not dataset_name.strip():
        return False
    retrieval_time = data.get("retrieval_time")
    if not _is_iso8601(retrieval_time):
        return False
    files = data.get("files")
    if not isinstance(files, list) or len(files) == 0:
        return False
    # Validate files entries and match to real files
    for entry in files:
        if not isinstance(entry, dict):
            return False
        fn = entry.get("filename")
        sz = entry.get("size_bytes")
        md5 = entry.get("md5")
        if not isinstance(fn, str) or not fn:
            return False
        if not isinstance(sz, int) or sz < 0:
            return False
        if not isinstance(md5, str) or not md5:
            return False
        file_path = _find_file_by_name(dataset_dir, fn)
        if file_path is None or not file_path.exists():
            return False
        try:
            actual_size = file_path.stat().st_size
        except Exception:
            return False
        if actual_size != sz:
            return False
        actual_md5 = _compute_md5(file_path)
        if actual_md5 is None or actual_md5.lower() != md5.lower():
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    expected_ids = [61, 1461, 40945]
    expected_ids_set = set(expected_ids)
    expected_header = [
        "source_id",
        "name",
        "n_rows",
        "n_columns",
        "n_numeric",
        "n_categorical",
        "pct_missing",
        "target_name",
        "n_classes",
        "raw_bytes_total",
    ]

    scores: Dict[str, float] = {
        "config_ids_correct": 0.0,
        "config_output_root_workspace": 0.0,
        "config_no_urls_in_config": 0.0,
        "script_uses_official_openml": 0.0,
        "manifest_valid_61": 0.0,
        "manifest_valid_1461": 0.0,
        "manifest_valid_40945": 0.0,
        "summary_structure": 0.0,
        "summary_unique_rows": 0.0,
        "summary_ids_subset_of_config": 0.0,
        "summary_rows_for_manifests": 0.0,
        "summary_raw_bytes_match": 0.0,
        "summary_manifest_name_matches": 0.0,
        "top_datasets_structure": 0.0,
        "top_datasets_max_5_rows": 0.0,
        "top_datasets_filter_and_ranking": 0.0,
        "logs_start_done": 0.0,
    }

    # Parse config
    config_path = workspace / "config" / "sources.yaml"
    dataset_ids, output_root, has_urls = _parse_config_yaml(config_path)

    # Config: dataset IDs must be exactly the required set (order-insensitive)
    if isinstance(dataset_ids, list) and len(dataset_ids) == 3 and set(dataset_ids) == expected_ids_set:
        scores["config_ids_correct"] = 1.0

    # Config: output_root must be "workspace" but only score if IDs are correct (avoid baseline credit)
    if scores["config_ids_correct"] == 1.0 and isinstance(output_root, str) and output_root.strip() == "workspace":
        scores["config_output_root_workspace"] = 1.0

    # Config: no URLs present, score only if IDs are correct (avoid baseline credit)
    if scores["config_ids_correct"] == 1.0 and config_path.exists():
        scores["config_no_urls_in_config"] = 1.0 if not has_urls else 0.0

    # Script: evidence of using official OpenML domain/API (avoid awarding for skeleton)
    script_path = workspace / "scripts" / "fetch_openml.py"
    if script_path.exists():
        text = _read_text(script_path) or ""
        uses_openml_client = ("import openml" in text) and ("openml." in text)
        uses_openml_domain = (
            "openml.org" in text or "https://api.openml.org" in text or "https://www.openml.org" in text
        )
        if uses_openml_client or uses_openml_domain:
            scores["script_uses_official_openml"] = 1.0

    # Determine output root for artifacts
    out_root_str = output_root if isinstance(output_root, str) and output_root.strip() else "workspace"
    out_root = (workspace / out_root_str).resolve()

    # Validate manifests for each expected dataset ID
    manifest_success_flags: Dict[int, bool] = {}
    manifests: Dict[int, dict] = {}
    for did in expected_ids:
        dataset_dir = out_root / "raw" / "openml" / str(did)
        manifest_path = dataset_dir / "download_manifest.json"
        valid = False
        if manifest_path.exists() and dataset_dir.exists():
            valid = _validate_manifest(manifest_path, dataset_dir, did)
        manifest_success_flags[did] = valid
        if valid:
            data = _safe_load_json(manifest_path)
            manifests[did] = data if isinstance(data, dict) else {}
        scores[f"manifest_valid_{did}"] = 1.0 if valid else 0.0

    # Summary CSV checks
    summary_path = out_root / "derived" / "openml_summary.csv"
    header, rows = _safe_read_csv_dicts(summary_path)

    # Structure check: exact header in exact order
    if header == expected_header and rows is not None:
        scores["summary_structure"] = 1.0

    # Unique rows by source_id
    if rows is not None and header == expected_header:
        ids_seen = []
        ok = True
        for r in rows:
            sid = _parse_int(r.get("source_id"))
            if sid is None:
                ok = False
                break
            ids_seen.append(sid)
        if ok and len(ids_seen) == len(set(ids_seen)) == len(rows):
            scores["summary_unique_rows"] = 1.0

    # Summary IDs should be a subset of configured IDs (if config parsed)
    if rows is not None and isinstance(dataset_ids, list) and header == expected_header:
        all_sids = set()
        ok = True
        for r in rows:
            sid = _parse_int(r.get("source_id"))
            if sid is None:
                ok = False
                break
            all_sids.add(sid)
        if ok and all_sids.issubset(set(dataset_ids)):
            scores["summary_ids_subset_of_config"] = 1.0

    # Summary rows corresponding to successful manifests, and raw_bytes_total sanity
    considered_ids = [did for did, ok in manifest_success_flags.items() if ok]
    have_summary = 0
    bytes_match = 0
    names_match = 0
    denom = len(considered_ids)
    if rows is not None and header == expected_header and denom > 0:
        rows_by_id: Dict[int, Dict[str, str]] = {}
        for r in rows:
            sid = _parse_int(r.get("source_id"))
            if sid is not None and sid not in rows_by_id:
                rows_by_id[sid] = r
        for did in considered_ids:
            r = rows_by_id.get(did)
            if r is not None:
                have_summary += 1
                # raw bytes
                dataset_dir = out_root / "raw" / "openml" / str(did)
                sum_bytes = _sum_raw_bytes_under_dataset_dir(dataset_dir)
                csv_val = _parse_int(r.get("raw_bytes_total"))
                n_rows_val = _parse_int(r.get("n_rows"))
                n_cols_val = _parse_int(r.get("n_columns"))
                n_num_val = _parse_int(r.get("n_numeric"))
                n_cat_val = _parse_int(r.get("n_categorical"))
                pct_miss_val = _parse_float(r.get("pct_missing"))
                numeric_ok = (
                    isinstance(csv_val, int)
                    and isinstance(n_rows_val, int)
                    and isinstance(n_cols_val, int)
                    and isinstance(n_num_val, int)
                    and isinstance(n_cat_val, int)
                    and isinstance(pct_miss_val, float)
                    and 0.0 <= pct_miss_val <= 1.0
                    and n_rows_val >= 0
                    and n_cols_val >= 0
                    and n_num_val >= 0
                    and n_cat_val >= 0
                    and n_num_val + n_cat_val <= n_cols_val
                )
                if sum_bytes >= 0 and csv_val is not None and numeric_ok and csv_val == sum_bytes:
                    bytes_match += 1
                # name consistency with manifest
                manifest = manifests.get(did, {})
                m_name = manifest.get("dataset_name")
                s_name = r.get("name")
                if isinstance(m_name, str) and isinstance(s_name, str) and m_name.strip() == s_name.strip():
                    names_match += 1
        scores["summary_rows_for_manifests"] = have_summary / denom if denom > 0 else 0.0
        scores["summary_raw_bytes_match"] = bytes_match / denom if denom > 0 else 0.0
        scores["summary_manifest_name_matches"] = names_match / denom if denom > 0 else 0.0

    # Top datasets checks
    top_path = out_root / "derived" / "top_datasets.csv"
    top_header, top_rows = _safe_read_csv_dicts(top_path)
    if top_header == expected_header and top_rows is not None:
        scores["top_datasets_structure"] = 1.0

    # Max 5 rows
    if top_rows is not None:
        scores["top_datasets_max_5_rows"] = 1.0 if len(top_rows) <= 5 else 0.0

    # Filter and ranking: rows must be those from summary with n_rows >= 1000, ordered by pct_missing desc then n_rows desc (ties allowed)
    if rows is not None and top_rows is not None and header == expected_header and top_header == expected_header:
        # Compute expected candidate set
        filtered = []
        for r in rows:
            n_rows_val = _parse_int(r.get("n_rows"))
            pct_miss_val = _parse_float(r.get("pct_missing"))
            sid = _parse_int(r.get("source_id"))
            if n_rows_val is None or pct_miss_val is None or sid is None:
                continue
            if n_rows_val >= 1000:
                filtered.append((sid, pct_miss_val, n_rows_val))
        # Sort to define the expected top set (IDs), taking top 5
        filtered_sorted = sorted(filtered, key=lambda x: (-x[1], -x[2], x[0]))
        expected_top_ids = [sid for sid, _, _ in filtered_sorted[: len(top_rows)]]

        # Extract actual top rows IDs and values
        actual_ids: List[int] = []
        actual_values: List[Tuple[float, int]] = []
        only_eligible = True
        monotonic_ok = True
        for r in top_rows:
            sid = _parse_int(r.get("source_id"))
            n_rows_val = _parse_int(r.get("n_rows"))
            pct_miss_val = _parse_float(r.get("pct_missing"))
            if sid is None or n_rows_val is None or pct_miss_val is None:
                only_eligible = False
                break
            if n_rows_val < 1000:
                only_eligible = False
                break
            actual_ids.append(sid)
            actual_values.append((pct_miss_val, n_rows_val))
        # Check non-increasing ordering by pct_missing, then by n_rows
        for i in range(len(actual_values) - 1):
            pm1, nr1 = actual_values[i]
            pm2, nr2 = actual_values[i + 1]
            if pm1 < pm2:
                monotonic_ok = False
                break
            if pm1 == pm2 and nr1 < nr2:
                monotonic_ok = False
                break
        # Set equality with expected top set (ignoring tie order)
        set_ok = set(actual_ids) == set(expected_top_ids)
        if only_eligible and monotonic_ok and set_ok:
            scores["top_datasets_filter_and_ranking"] = 1.0

    # Logs check: START <id> and DONE <id> or ERROR <id> per dataset
    log_path = out_root / "logs" / "fetch.log"
    log_text = _read_text(log_path) or ""
    if log_text:
        hits = 0
        for did in expected_ids:
            has_start = f"START {did}" in log_text
            has_done = f"DONE {did}" in log_text
            has_error = (f"ERROR {did}" in log_text) or (re.search(rf"ERROR.*\b{did}\b", log_text) is not None)
            if has_start and (has_done or has_error):
                hits += 1
        scores["logs_start_done"] = hits / len(expected_ids)

    return scores


def main() -> None:
    parser = argparse.ArgumentParser(description="Grader for OpenML fetch-and-summarize workflow.")
    parser.add_argument("workspace", nargs="?", default=".", help="Path to the workspace (default: current directory)")
    args = parser.parse_args()
    result = grade([], args.workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()