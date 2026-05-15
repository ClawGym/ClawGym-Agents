import json
import csv
import sys
import hashlib
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any
from datetime import datetime


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            header = reader.fieldnames
            return rows, header
    except Exception:
        return None, None


def _compute_sha256(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _list_input_files(workspace: Path) -> List[Path]:
    input_dir = workspace / "input"
    if not input_dir.exists() or not input_dir.is_dir():
        return []
    # Recursively list files
    return [p for p in input_dir.rglob("*") if p.is_file()]


def _to_posix_relative(path: Path, root: Path) -> str:
    rel = path.relative_to(root)
    return rel.as_posix()


def _is_hex_sha256(s: str) -> bool:
    if not isinstance(s, str):
        return False
    if len(s) != 64:
        return False
    try:
        int(s, 16)
        return True
    except Exception:
        return False


def _is_iso8601(s: Any) -> bool:
    if not isinstance(s, str) or not s:
        return False
    # Accept basic ISO 8601, allow Z suffix
    t = s
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        datetime.fromisoformat(t)
        return True
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "input_inventory_exists_and_readable": 0.0,
        "input_inventory_columns_and_format": 0.0,
        "input_inventory_paths_cover_input": 0.0,
        "input_inventory_sizes_and_hashes_correct": 0.0,
        "input_inventory_text_and_preview_rules": 0.0,
        "web_snapshot_files_exist": 0.0,
        "web_snapshot_metadata_fields_and_types": 0.0,
        "web_snapshot_size_and_hash_consistency": 0.0,
        "system_report_exists_and_readable": 0.0,
        "system_report_required_fields_and_types": 0.0,
        "system_report_paths_and_values_valid": 0.0,
        "system_report_counts_and_csv_crosscheck": 0.0,
        "system_report_web_snapshot_consistency": 0.0,
        "timestamps_valid_iso8601": 0.0,
    }

    # Paths
    inv_csv_path = workspace / "outputs" / "input_inventory.csv"
    web_html_path = workspace / "outputs" / "web_snapshot" / "who_homepage.html"
    web_meta_path = workspace / "outputs" / "web_snapshot" / "metadata.json"
    sys_report_path = workspace / "outputs" / "system_report.json"

    # Gather actual input files
    input_files = _list_input_files(workspace)
    expected_input_rel_paths = {_to_posix_relative(p, workspace) for p in input_files}

    # 1) Check input_inventory.csv exists and readable
    inv_rows, inv_header = _safe_read_csv(inv_csv_path)
    if inv_rows is not None and inv_header is not None:
        scores["input_inventory_exists_and_readable"] = 1.0

        # Check columns and format (order should match exactly as specified)
        required_header = ["path", "size_bytes", "sha256", "is_text", "first_80_chars"]
        header_ok = inv_header == required_header
        # Validate fields basic types and formats
        format_ok = header_ok
        if format_ok:
            for row in inv_rows:
                # presence of required keys
                if any(k not in row for k in required_header):
                    format_ok = False
                    break
                # 'path' should be relative and use forward slashes and start with "input/"
                path_str = row["path"]
                if not isinstance(path_str, str) or not path_str or "\\" in path_str:
                    format_ok = False
                    break
                # Should not be absolute
                if path_str.startswith("/") or path_str.startswith("\\"):
                    format_ok = False
                    break
                if not path_str.startswith("input/"):
                    format_ok = False
                    break
                # size_bytes should be an integer
                try:
                    int(row["size_bytes"])
                except Exception:
                    format_ok = False
                    break
                # sha256 hex
                if not _is_hex_sha256(row["sha256"]):
                    format_ok = False
                    break
                # is_text should be exactly 'true' or 'false'
                if row["is_text"] not in ("true", "false"):
                    format_ok = False
                    break
                # first_80_chars must be a string (csv gives string)
                if not isinstance(row["first_80_chars"], str):
                    format_ok = False
                    break
        if format_ok:
            scores["input_inventory_columns_and_format"] = 1.0

        # Check that paths listed cover exactly the input files, and none outside input/
        if inv_rows is not None:
            csv_paths = [r.get("path", "") for r in inv_rows]
            # All csv paths must start with input/ (already checked in format_ok)
            csv_paths_set = set(csv_paths)
            # Compare with expected set of 'input/...' posix paths
            # expected_input_rel_paths already contains 'input/...'
            if csv_paths_set == expected_input_rel_paths:
                scores["input_inventory_paths_cover_input"] = 1.0

        # Verify size_bytes and sha256 against actual files
        sizes_hashes_ok = True
        if inv_rows is not None:
            for r in inv_rows:
                p_str = r.get("path")
                if not isinstance(p_str, str):
                    sizes_hashes_ok = False
                    break
                fpath = workspace / p_str
                if not fpath.exists() or not fpath.is_file():
                    sizes_hashes_ok = False
                    break
                # size
                try:
                    recorded_size = int(r.get("size_bytes", ""))
                except Exception:
                    sizes_hashes_ok = False
                    break
                actual_size = fpath.stat().st_size
                if recorded_size != actual_size:
                    sizes_hashes_ok = False
                    break
                # sha256
                recorded_hash = r.get("sha256")
                actual_hash = _compute_sha256(fpath)
                if actual_hash is None or recorded_hash != actual_hash:
                    sizes_hashes_ok = False
                    break
        if sizes_hashes_ok and inv_rows is not None:
            scores["input_inventory_sizes_and_hashes_correct"] = 1.0

        # Check is_text and first_80_chars rules (only structure, not content)
        text_preview_ok = True
        if inv_rows is not None:
            for r in inv_rows:
                it = r.get("is_text")
                preview = r.get("first_80_chars")
                if it not in ("true", "false"):
                    text_preview_ok = False
                    break
                if it == "false":
                    # Must be empty
                    if preview != "":
                        text_preview_ok = False
                        break
                else:
                    # length must be <= 80
                    if not isinstance(preview, str) or len(preview) > 80:
                        text_preview_ok = False
                        break
        if text_preview_ok and inv_rows is not None:
            scores["input_inventory_text_and_preview_rules"] = 1.0

    # 2) Web snapshot files exist
    web_files_exist = web_html_path.exists() and web_html_path.is_file() and web_meta_path.exists() and web_meta_path.is_file()
    if web_files_exist:
        scores["web_snapshot_files_exist"] = 1.0

    # 3) Web snapshot metadata fields and types
    web_meta = _safe_load_json(web_meta_path) if web_files_exist else None
    meta_fields_ok = False
    if web_meta is not None and isinstance(web_meta, dict):
        # Required fields
        required_meta_fields = {
            "resolved_url": str,
            "http_status": int,
            "content_length": int,
            "sha256": str,
            "title": (str, type(None)),
            "link_count": int,
            "canonical_href": (str, type(None)),
            "fetched_at_utc": str,
        }
        missing = [k for k in required_meta_fields if k not in web_meta]
        types_ok = True
        if not missing:
            for k, typ in required_meta_fields.items():
                val = web_meta.get(k)
                if isinstance(typ, tuple):
                    if not isinstance(val, typ):
                        types_ok = False
                        break
                else:
                    if not isinstance(val, typ):
                        types_ok = False
                        break
            # sha256 hex format
            if types_ok and not _is_hex_sha256(web_meta.get("sha256", "")):
                types_ok = False
            # fetched_at_utc iso8601 will be checked in timestamps check
        if types_ok and not missing:
            meta_fields_ok = True
            scores["web_snapshot_metadata_fields_and_types"] = 1.0

    # 4) Web snapshot size and hash consistency (metadata.json vs actual HTML, and cross-match within metadata)
    web_consistency_ok = False
    if web_files_exist and meta_fields_ok:
        try:
            actual_html_size = web_html_path.stat().st_size
            actual_html_sha = _compute_sha256(web_html_path)
            content_length_ok = (web_meta.get("content_length") == actual_html_size)
            sha_ok = (web_meta.get("sha256") == actual_html_sha)
            web_consistency_ok = (content_length_ok and sha_ok)
        except Exception:
            web_consistency_ok = False
    if web_consistency_ok:
        scores["web_snapshot_size_and_hash_consistency"] = 1.0

    # 5) System report exists and readable
    sys_report = _safe_load_json(sys_report_path)
    if isinstance(sys_report, dict):
        scores["system_report_exists_and_readable"] = 1.0

        # 6) System report required fields and types
        required_sys_fields = {
            "os_name": str,
            "os_version": str,
            "python_version": str,
            "cpu_count": int,
            "workspace_path": str,
            "disk_total_bytes": int,
            "disk_free_bytes": int,
            "input_dir": str,
            "input_file_count": int,
            "input_total_size_bytes": int,
            "inventory_csv_path": str,
            "generated_at_utc": str,
            "web_snapshot": dict,
        }
        sys_fields_ok = True
        if any(k not in sys_report for k in required_sys_fields):
            sys_fields_ok = False
        else:
            for k, typ in required_sys_fields.items():
                if not isinstance(sys_report.get(k), typ):
                    sys_fields_ok = False
                    break
        # web_snapshot subfields
        if sys_fields_ok and isinstance(sys_report.get("web_snapshot"), dict):
            ws = sys_report["web_snapshot"]
            ws_required = {
                "resolved_url": (str,),
                "http_status": (int,),
                "content_length": (int,),
                "sha256": (str,),
                "title": (str, type(None)),
                "link_count": (int,),
                "canonical_href": (str, type(None)),
            }
            for k, typs in ws_required.items():
                if k not in ws or not isinstance(ws.get(k), typs):
                    sys_fields_ok = False
                    break
            if sys_fields_ok and not _is_hex_sha256(ws.get("sha256", "")):
                sys_fields_ok = False
        if sys_fields_ok:
            scores["system_report_required_fields_and_types"] = 1.0

        # 7) System report paths and values validity
        paths_values_ok = False
        try:
            # workspace_path should be absolute and equal to current workspace absolute path
            expected_abs = str(workspace.resolve())
            ws_path_str = sys_report.get("workspace_path")
            ws_abs_ok = isinstance(ws_path_str, str) and Path(ws_path_str).is_absolute() and ws_path_str == expected_abs

            # input_dir must be "input"
            input_dir_ok = sys_report.get("input_dir") == "input"

            # inventory_csv_path must be relative, use forward slashes, and point to outputs/input_inventory.csv
            inv_rel = sys_report.get("inventory_csv_path")
            inv_rel_ok = False
            if isinstance(inv_rel, str) and inv_rel and "\\" not in inv_rel and not Path(inv_rel).is_absolute():
                inv_expected = "outputs/input_inventory.csv"
                inv_rel_ok = (inv_rel == inv_expected) and (workspace / inv_rel).exists()

            # disk_total_bytes and disk_free_bytes should be non-negative integers (already typed)
            disk_ok = isinstance(sys_report.get("disk_total_bytes"), int) and isinstance(sys_report.get("disk_free_bytes"), int)
            if disk_ok:
                disk_ok = sys_report["disk_total_bytes"] >= 0 and sys_report["disk_free_bytes"] >= 0

            paths_values_ok = ws_abs_ok and input_dir_ok and inv_rel_ok and disk_ok
        except Exception:
            paths_values_ok = False
        if paths_values_ok:
            scores["system_report_paths_and_values_valid"] = 1.0

        # 8) System report counts and CSV cross-checks
        counts_ok = False
        try:
            # Compute actual counts and total size of files under input/
            actual_files = input_files
            actual_count = len(actual_files)
            actual_total_size = 0
            for f in actual_files:
                try:
                    actual_total_size += f.stat().st_size
                except Exception:
                    # If stat fails, treat as mismatch
                    actual_total_size = -1
                    break

            # Values in system_report
            sr_count = sys_report.get("input_file_count")
            sr_total = sys_report.get("input_total_size_bytes")

            # From CSV: sum of size_bytes
            csv_rows = inv_rows if inv_rows is not None else []
            sum_csv_sizes = None
            try:
                sum_csv_sizes = sum(int(r.get("size_bytes", "0")) for r in csv_rows)
            except Exception:
                sum_csv_sizes = None

            # Check: sr_total equals sum of CSV size_bytes and equals actual_total_size; sr_count equals actual_count and equals number of CSV rows
            csv_count = len(csv_rows)
            if (
                isinstance(sr_count, int)
                and isinstance(sr_total, int)
                and sum_csv_sizes is not None
                and sr_count == actual_count == csv_count
                and sr_total == actual_total_size == sum_csv_sizes
            ):
                counts_ok = True
        except Exception:
            counts_ok = False
        if counts_ok:
            scores["system_report_counts_and_csv_crosscheck"] = 1.0

        # 9) System report web_snapshot consistency with metadata.json and actual HTML file
        wsnap_ok = False
        try:
            wsnap = sys_report.get("web_snapshot")
            if isinstance(wsnap, dict) and isinstance(web_meta, dict) and web_files_exist:
                # Fields to match with metadata.json (subset)
                fields = ["resolved_url", "http_status", "content_length", "sha256", "title", "link_count", "canonical_href"]
                match_meta = all(wsnap.get(k) == web_meta.get(k) for k in fields)
                # sha256 equality with actual HTML file
                actual_sha = _compute_sha256(web_html_path)
                sha_equal = (wsnap.get("sha256") == actual_sha == web_meta.get("sha256"))
                # content_length equality with actual file size
                actual_len = web_html_path.stat().st_size
                len_equal = (wsnap.get("content_length") == actual_len == web_meta.get("content_length"))
                wsnap_ok = match_meta and sha_equal and len_equal
        except Exception:
            wsnap_ok = False
        if wsnap_ok:
            scores["system_report_web_snapshot_consistency"] = 1.0

        # 10) ISO8601 timestamps validity (metadata.fetched_at_utc and system_report.generated_at_utc)
        ts_ok = False
        try:
            ts_ok = _is_iso8601(sys_report.get("generated_at_utc")) and (web_meta is None or _is_iso8601(web_meta.get("fetched_at_utc")))
        except Exception:
            ts_ok = False
        if ts_ok:
            scores["timestamps_valid_iso8601"] = 1.0

    else:
        # If system report not readable, also attempt timestamps_valid_iso8601 via web_meta only
        if web_meta is not None and isinstance(web_meta, dict):
            if _is_iso8601(web_meta.get("fetched_at_utc")):
                # Do not give credit to timestamps_valid_iso8601 here because it requires both; keep as 0.0 per strictness
                pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()