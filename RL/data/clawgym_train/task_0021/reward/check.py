import csv
import json
import hashlib;
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
import zipfile
from typing import Dict, Tuple, List, Optional


def read_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = [dict(row) for row in reader]
            return header, rows
    except Exception:
        return None, None


def compute_sha256(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_gazetteer_mapping(text_path: Path) -> Optional[Dict[str, Tuple[float, float]]]:
    # Expect a tab-delimited text with headers including ZCTA5, INTPTLAT, INTPTLONG
    try:
        with text_path.open("r", encoding="utf-8") as f:
            first_line = f.readline()
            if not first_line:
                return None
            # Detect delimiter: prioritize tab, otherwise split on whitespace
            if "\t" in first_line:
                headers = [h.strip() for h in first_line.rstrip("\n\r").split("\t")]
                delimiter = "\t"
            else:
                headers = [h.strip() for h in first_line.strip().split()]
                delimiter = None  # fallback split
            # Find required columns
            try:
                zcta_idx = headers.index("ZCTA5")
                lat_idx = headers.index("INTPTLAT")
                lon_idx = headers.index("INTPTLONG")
            except ValueError:
                return None
            mapping: Dict[str, Tuple[float, float]] = {}
            for line in f:
                line = line.rstrip("\n\r")
                if not line:
                    continue
                parts = line.split("\t") if delimiter == "\t" else line.split()
                if max(zcta_idx, lat_idx, lon_idx) >= len(parts):
                    return None
                zcta = parts[zcta_idx].strip()
                lat_s = parts[lat_idx].strip()
                lon_s = parts[lon_idx].strip()
                try:
                    lat = float(lat_s)
                    lon = float(lon_s)
                except Exception:
                    return None
                # Normalize ZIP as 5-digit string
                zcta_norm = normalize_zip(zcta)
                if zcta_norm is None:
                    continue
                mapping[zcta_norm] = (lat, lon)
            return mapping
    except Exception:
        return None


def normalize_zip(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) >= 5:
        return digits[:5]
    if 0 < len(digits) < 5:
        return digits.zfill(5)
    return None


def parse_jsonl(path: Path) -> List[dict]:
    entries: List[dict] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        entries.append(obj)
                except Exception:
                    continue
    except Exception:
        return []
    return entries


def is_iso8601_utc(s: str) -> bool:
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            return False
        offset = dt.utcoffset()
        return offset == timedelta(0)
    except Exception:
        return False


def endswith_path(path_str: str, expected_rel: str) -> bool:
    try:
        p = Path(path_str)
        return p.as_posix().endswith(Path(expected_rel).as_posix())
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    inbound_file = workspace / "inbound" / "deliveries_2026-04-15.csv"
    out_file = workspace / "out" / "deliveries_2026-04-15_geocoded.csv"
    cache_zip = workspace / "cache" / "2020_Gaz_zcta_national.zip"
    cache_txt = workspace / "cache" / "2020_Gaz_zcta_national.txt"
    cache_sha = workspace / "cache" / "2020_gaz_source_sha256.txt"
    log_file = workspace / "logs" / "processed.jsonl"

    scores = {
        "cache_zip_present": 0.0,
        "cache_zip_contains_expected_text": 0.0,
        "cache_txt_present": 0.0,
        "cache_sha256_file_correct": 0.0,
        "output_file_present": 0.0,
        "output_header_appended_columns": 0.0,
        "output_row_count_matches_input": 0.0,
        "output_geo_values_match_cache": 0.0,
        "log_entry_for_input_present": 0.0,
        "log_input_output_paths_correct": 0.0,
        "log_processed_at_is_iso8601_utc": 0.0,
        "log_input_rows_correct": 0.0,
        "log_matched_rows_correct": 0.0,
        "log_sha256_matches_cache": 0.0,
    }

    if cache_zip.exists() and cache_zip.is_file():
        scores["cache_zip_present"] = 1.0
        try:
            if zipfile.is_zipfile(cache_zip):
                with zipfile.ZipFile(cache_zip, "r") as zf:
                    names = [n for n in zf.namelist()]
                    if "2020_Gaz_zcta_national.txt" in names:
                        scores["cache_zip_contains_expected_text"] = 1.0
        except Exception:
            pass

    if cache_txt.exists() and cache_txt.is_file():
        scores["cache_txt_present"] = 1.0

    sha_ok = False
    cache_txt_sha = compute_sha256(cache_txt) if cache_txt.exists() else None
    sha_file_text = safe_read_text(cache_sha)
    if cache_txt_sha is not None and sha_file_text is not None:
        content = sha_file_text.strip()
        if len(content) == 64:
            try:
                int(content, 16)
                if content.lower() == cache_txt_sha.lower():
                    sha_ok = True
            except Exception:
                sha_ok = False
    scores["cache_sha256_file_correct"] = 1.0 if sha_ok else 0.0

    in_header, in_rows = read_csv(inbound_file)
    out_header, out_rows = read_csv(out_file)

    if out_file.exists() and out_file.is_file():
        scores["output_file_present"] = 1.0

    header_ok = False
    if in_header is not None and out_header is not None:
        expected_header = list(in_header) + ["zip_lat", "zip_lon"]
        if out_header == expected_header:
            header_ok = True
    scores["output_header_appended_columns"] = 1.0 if header_ok else 0.0

    row_count_ok = False
    if in_rows is not None and out_rows is not None:
        if len(in_rows) == len(out_rows):
            row_count_ok = True
    scores["output_row_count_matches_input"] = 1.0 if row_count_ok else 0.0

    mapping = load_gazetteer_mapping(cache_txt) if cache_txt.exists() else None

    geo_ok = False
    matched_rows_count: Optional[int] = None
    if mapping is not None and out_rows is not None and out_header is not None:
        tol = 1e-6
        all_ok = True
        matched = 0
        for row in out_rows:
            zip_val = normalize_zip(row.get("zip", ""))
            lat_s = (row.get("zip_lat", "") or "").strip()
            lon_s = (row.get("zip_lon", "") or "").strip()
            if zip_val in mapping:
                try:
                    lat_f = float(lat_s)
                    lon_f = float(lon_s)
                except Exception:
                    all_ok = False
                    break
                lat_m, lon_m = mapping[zip_val]
                if abs(lat_f - lat_m) <= tol and abs(lon_f - lon_m) <= tol:
                    matched += 1
                else:
                    all_ok = False
                    break
            else:
                if lat_s != "" or lon_s != "":
                    all_ok = False
                    break
        if all_ok:
            geo_ok = True
            matched_rows_count = matched
    scores["output_geo_values_match_cache"] = 1.0 if geo_ok else 0.0

    logs = parse_jsonl(log_file)
    target_input_rel = "inbound/deliveries_2026-04-15.csv"
    matching_entries = [e for e in logs if isinstance(e, dict) and isinstance(e.get("input_file"), str) and endswith_path(e["input_file"], target_input_rel)]
    log_entry = matching_entries[-1] if matching_entries else None
    scores["log_entry_for_input_present"] = 1.0 if log_entry is not None else 0.0

    if log_entry is not None:
        in_path_ok = endswith_path(log_entry.get("input_file", ""), target_input_rel)
        out_path_ok = endswith_path(log_entry.get("output_file", ""), "out/deliveries_2026-04-15_geocoded.csv")
        scores["log_input_output_paths_correct"] = 1.0 if (in_path_ok and out_path_ok) else 0.0
    else:
        scores["log_input_output_paths_correct"] = 0.0

    if log_entry is not None:
        processed_at = log_entry.get("processed_at")
        if isinstance(processed_at, str) and is_iso8601_utc(processed_at):
            scores["log_processed_at_is_iso8601_utc"] = 1.0
        else:
            scores["log_processed_at_is_iso8601_utc"] = 0.0
    else:
        scores["log_processed_at_is_iso8601_utc"] = 0.0

    if log_entry is not None and in_rows is not None:
        input_rows_logged = log_entry.get("input_rows")
        if isinstance(input_rows_logged, int) and input_rows_logged == len(in_rows):
            scores["log_input_rows_correct"] = 1.0
        else:
            scores["log_input_rows_correct"] = 0.0
    else:
        scores["log_input_rows_correct"] = 0.0

    if log_entry is not None and matched_rows_count is not None:
        matched_logged = log_entry.get("matched_rows")
        if isinstance(matched_logged, int) and matched_logged == matched_rows_count:
            scores["log_matched_rows_correct"] = 1.0
        else:
            scores["log_matched_rows_correct"] = 0.0
    else:
        scores["log_matched_rows_correct"] = 0.0

    if log_entry is not None and cache_txt_sha is not None:
        sha_logged = log_entry.get("source_file_sha256")
        if isinstance(sha_logged, str) and sha_logged.lower() == cache_txt_sha.lower():
            scores["log_sha256_matches_cache"] = 1.0
        else:
            scores["log_sha256_matches_cache"] = 0.0
    else:
        scores["log_sha256_matches_cache"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()