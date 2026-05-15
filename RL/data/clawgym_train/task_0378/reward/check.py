import json
import csv
import hashlib
import sys
import re
from pathlib import Path
from urllib.parse import urlparse
from typing import Optional, Tuple, List, Dict, Any


def _read_text_safe(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _load_json_safe(p: Path) -> Optional[dict]:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
        return None
    except Exception:
        return None


def _compute_sha256_hex(p: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _parse_csv_dicts(p: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with p.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None, None
            rows = list(reader)
            return headers, rows
    except Exception:
        return None, None


def _parse_zone1970_tab(p: Path) -> Optional[set]:
    text = _read_text_safe(p)
    if text is None:
        return None
    zones = set()
    try:
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 3:
                tz = parts[2].strip()
                if tz:
                    zones.add(tz)
                continue
            parts = line.split()
            if len(parts) >= 3:
                tz = parts[2].strip()
                if tz:
                    zones.add(tz)
    except Exception:
        return None
    return zones


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float))


def _is_int_like(x: Any) -> bool:
    if isinstance(x, int):
        return True
    if isinstance(x, float) and x.is_integer():
        return True
    return False


def _to_float_or_none(x: Any) -> Optional[float]:
    try:
        if isinstance(x, (int, float)):
            return float(x)
        if isinstance(x, str):
            return float(x.strip())
        return None
    except Exception:
        return None


def _to_int_or_none(x: Any) -> Optional[int]:
    try:
        if isinstance(x, int):
            return x
        if isinstance(x, float) and x.is_integer():
            return int(x)
        if isinstance(x, str):
            s = x.strip()
            if re.fullmatch(r"[+-]?\d+", s):
                return int(s)
        return None
    except Exception:
        return None


def _check_sorted_desc_pairs(rows: List[Dict[str, Any]], primary_key: str, secondary_key: Optional[str] = None,
                             eps: float = 1e-9) -> bool:
    for i in range(len(rows) - 1):
        a = _to_float_or_none(rows[i].get(primary_key))
        b = _to_float_or_none(rows[i + 1].get(primary_key))
        if a is None or b is None:
            return False
        if a < b - eps:
            return False
        if secondary_key is not None and abs(a - b) <= eps:
            sa = _to_float_or_none(rows[i].get(secondary_key))
            sb = _to_float_or_none(rows[i + 1].get(secondary_key))
            if sa is None or sb is None:
                return False
            if sa < sb - eps:
                return False
    return True


def _validate_ranks_sequential(rows: List[Dict[str, Any]], rank_key: str = "rank") -> bool:
    for idx, row in enumerate(rows, start=1):
        r = _to_int_or_none(row.get(rank_key))
        if r != idx:
            return False
    return True


def _url_is_iana_zone1970(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        host = (parsed.hostname or "").lower()
        if not host.endswith("iana.org"):
            return False
        path = (parsed.path or "")
        if not path.lower().endswith("/zone1970.tab") and not path.lower().endswith("zone1970.tab"):
            return False
        return True
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "iana_zone_file_present_and_parseable": 0.0,
        "summary_json_required_fields": 0.0,
        "summary_iana_metadata_consistency": 0.0,
        "summary_source_url_iana_domain_and_filename": 0.0,
        "timezone_recognition_matches_zone_file": 0.0,
        "top_processes_csv_structure_and_sort": 0.0,
        "top_processes_row_count_max_15": 0.0,
        "heavy_processes_filtered_and_sorted": 0.0,
        "nic_rank_csv_structure_and_sort": 0.0,
        "timezone_check_txt_consistency": 0.0,
    }

    iana_path = workspace / "data" / "iana" / "zone1970.tab"
    summary_path = workspace / "outputs" / "system_audit" / "summary.json"
    top_csv_path = workspace / "outputs" / "system_audit" / "top_processes.csv"
    heavy_csv_path = workspace / "outputs" / "system_audit" / "heavy_processes.csv"
    nic_csv_path = workspace / "outputs" / "system_audit" / "nic_rank.csv"
    tz_check_path = workspace / "outputs" / "system_audit" / "timezone_check.txt"

    iana_zones: Optional[set] = None
    iana_size: Optional[int] = None
    iana_sha: Optional[str] = None
    if iana_path.is_file():
        try:
            iana_size = iana_path.stat().st_size
        except Exception:
            iana_size = None
        iana_sha = _compute_sha256_hex(iana_path)
        iana_zones = _parse_zone1970_tab(iana_path)
        if iana_size and iana_size > 0 and iana_sha and iana_zones and len(iana_zones) > 0:
            scores["iana_zone_file_present_and_parseable"] = 1.0

    summary = _load_json_safe(summary_path)

    if summary is not None:
        cpu_logical_cores_ok = _is_int_like(summary.get("cpu_logical_cores"))
        cpu_avg_ok = _is_number(summary.get("cpu_avg_percent_10s"))
        mem_total_ok = _is_number(summary.get("memory_total_mb"))
        mem_avail_ok = _is_number(summary.get("memory_available_mb"))
        disk_total_ok = _is_number(summary.get("disk_root_total_gb"))
        disk_free_ok = _is_number(summary.get("disk_root_free_gb"))
        tz_obj = summary.get("timezone")
        tz_ok = isinstance(tz_obj, dict) and isinstance(tz_obj.get("local_tz"), str) and isinstance(tz_obj.get("recognized_in_iana"), bool)
        if cpu_logical_cores_ok and cpu_avg_ok and mem_total_ok and mem_avail_ok and disk_total_ok and disk_free_ok and tz_ok:
            scores["summary_json_required_fields"] = 1.0

        iana_meta = summary.get("iana_zone_file")
        meta_ok = False
        if isinstance(iana_meta, dict):
            path_str = iana_meta.get("path")
            size_val = iana_meta.get("size_bytes")
            sha_val = iana_meta.get("sha256")
            path_ok = (path_str == "data/iana/zone1970.tab")
            size_ok = (iana_path.is_file() and _to_int_or_none(size_val) == (iana_path.stat().st_size if iana_path.exists() else None))
            sha_ok = (isinstance(sha_val, str) and iana_path.is_file() and _compute_sha256_hex(iana_path) == sha_val)
            if path_ok and size_ok and sha_ok:
                meta_ok = True
        if meta_ok:
            scores["summary_iana_metadata_consistency"] = 1.0

        src_url = summary.get("source_url_used")
        if isinstance(src_url, str) and _url_is_iana_zone1970(src_url):
            scores["summary_source_url_iana_domain_and_filename"] = 1.0

        tz_local = None
        tz_recognized = None
        try:
            tz_local = tz_obj.get("local_tz") if isinstance(tz_obj, dict) else None
            tz_recognized = tz_obj.get("recognized_in_iana") if isinstance(tz_obj, dict) else None
        except Exception:
            tz_local = None
            tz_recognized = None
        if isinstance(tz_local, str) and isinstance(tz_recognized, bool) and isinstance(iana_zones, set):
            in_iana = tz_local in iana_zones
            if in_iana == tz_recognized:
                scores["timezone_recognition_matches_zone_file"] = 1.0

    top_headers, top_rows = _parse_csv_dicts(top_csv_path)
    expected_top_headers = ["rank", "pid", "name", "username", "cpu_percent_avg", "rss_mb"]
    top_struct_ok = False
    if top_headers == expected_top_headers and isinstance(top_rows, list):
        n = len(top_rows)
        if 1 <= n <= 15:
            scores["top_processes_row_count_max_15"] = 1.0
        types_ok = True
        for row in top_rows:
            if _to_int_or_none(row.get("rank")) is None:
                types_ok = False
                break
            if _to_int_or_none(row.get("pid")) is None:
                types_ok = False
                break
            name = row.get("name")
            if not isinstance(name, str) or name.strip() == "":
                types_ok = False
                break
            username = row.get("username")
            if not isinstance(username, str):
                types_ok = False
                break
            if _to_float_or_none(row.get("cpu_percent_avg")) is None:
                types_ok = False
                break
            rss_val = _to_float_or_none(row.get("rss_mb"))
            if rss_val is None or rss_val < 0:
                types_ok = False
                break

        if types_ok and _validate_ranks_sequential(top_rows, "rank") and _check_sorted_desc_pairs(top_rows, "cpu_percent_avg", "rss_mb"):
            top_struct_ok = True

    if top_struct_ok:
        scores["top_processes_csv_structure_and_sort"] = 1.0

    heavy_headers, heavy_rows = _parse_csv_dicts(heavy_csv_path)
    expected_heavy_headers = expected_top_headers
    heavy_ok = False
    if heavy_headers == expected_heavy_headers and isinstance(heavy_rows, list):
        if top_headers == expected_top_headers and isinstance(top_rows, list):
            top_map = {}
            top_filtered_pids = []
            for row in top_rows:
                pid = _to_int_or_none(row.get("pid"))
                cpu = _to_float_or_none(row.get("cpu_percent_avg"))
                rss = _to_float_or_none(row.get("rss_mb"))
                if pid is None or cpu is None or rss is None:
                    top_map = {}
                    break
                top_map[pid] = {
                    "name": row.get("name"),
                    "username": row.get("username"),
                    "cpu": cpu,
                    "rss": rss,
                }
                if cpu >= 1.0 or rss >= 200.0:
                    top_filtered_pids.append(pid)

            if top_map:
                heavy_pids = []
                heavy_types_ok = True
                for row in heavy_rows:
                    pid = _to_int_or_none(row.get("pid"))
                    if pid is None or pid not in top_map:
                        heavy_types_ok = False
                        break
                    cpu = _to_float_or_none(row.get("cpu_percent_avg"))
                    rss = _to_float_or_none(row.get("rss_mb"))
                    if cpu is None or rss is None:
                        heavy_types_ok = False
                        break
                    ref = top_map[pid]
                    if (row.get("name") != ref["name"]) or (row.get("username") != ref["username"]):
                        heavy_types_ok = False
                        break
                    if abs(cpu - ref["cpu"]) > 1e-6 or abs(rss - ref["rss"]) > 1e-6:
                        heavy_types_ok = False
                        break
                    heavy_pids.append(pid)

                if heavy_types_ok:
                    if set(heavy_pids) == set(top_filtered_pids):
                        sorted_ok = _check_sorted_desc_pairs(heavy_rows, "rss_mb", None)
                        rank_ok = _validate_ranks_sequential(heavy_rows, "rank")
                        if sorted_ok and rank_ok:
                            heavy_ok = True
    if heavy_ok:
        scores["heavy_processes_filtered_and_sorted"] = 1.0

    nic_headers, nic_rows = _parse_csv_dicts(nic_csv_path)
    expected_nic_headers = ["rank", "interface_name", "bytes_total", "bytes_sent", "bytes_recv"]
    nic_ok = False
    if nic_headers == expected_nic_headers and isinstance(nic_rows, list) and len(nic_rows) >= 1:
        nic_types_ok = True
        for row in nic_rows:
            if _to_int_or_none(row.get("rank")) is None:
                nic_types_ok = False
                break
            if not isinstance(row.get("interface_name"), str) or row.get("interface_name").strip() == "":
                nic_types_ok = False
                break
            sent = _to_float_or_none(row.get("bytes_sent"))
            recv = _to_float_or_none(row.get("bytes_recv"))
            total = _to_float_or_none(row.get("bytes_total"))
            if sent is None or recv is None or total is None:
                nic_types_ok = False
                break
            if abs((sent + recv) - total) > 0.5:
                nic_types_ok = False
                break
        if nic_types_ok and _validate_ranks_sequential(nic_rows, "rank") and _check_sorted_desc_pairs(nic_rows, "bytes_total", None):
            nic_ok = True
    if nic_ok:
        scores["nic_rank_csv_structure_and_sort"] = 1.0

    tz_check_ok = False
    if summary is not None and tz_check_path.is_file():
        tz_obj = summary.get("timezone") if isinstance(summary, dict) else None
        if isinstance(tz_obj, dict):
            local_tz = tz_obj.get("local_tz")
            recognized = tz_obj.get("recognized_in_iana")
            txt = _read_text_safe(tz_check_path)
            if isinstance(local_tz, str) and isinstance(recognized, bool) and txt:
                txt_lower = txt.lower()
                contains_tz = local_tz in txt
                yes_present = re.search(r"\byes\b", txt_lower) is not None
                no_present = re.search(r"\bno\b", txt_lower) is not None
                yn_ok = (recognized and yes_present and not no_present) or ((not recognized) and no_present and not yes_present)
                extra_ok = True
                if recognized:
                    extra_ok = contains_tz
                else:
                    extra_ok = ("non-iana" in txt_lower) or ("non iana" in txt_lower) or ("not recognized" in txt_lower) or ("unrecognized" in txt_lower) or (("iana" in txt_lower) and ("not" in txt_lower or "non" in txt_lower or "no " in txt_lower))
                if contains_tz and yn_ok and extra_ok:
                    tz_check_ok = True
    if tz_check_ok:
        scores["timezone_check_txt_consistency"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()