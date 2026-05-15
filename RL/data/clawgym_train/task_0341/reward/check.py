import csv
import json
import math
import re
import sys
import hashlib
from datetime import datetime
from pathlib import Path


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        try:
            return path.read_text(encoding="latin-1", errors="ignore")
        except Exception:
            return ""


def _load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _compute_sha256(path: Path) -> str:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _is_iso8601(s: str) -> bool:
    if not isinstance(s, str) or not s.strip():
        return False
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        datetime.fromisoformat(s2)
        return True
    except Exception:
        return False


def _safe_float(x):
    try:
        if x is None:
            return None
        if isinstance(x, float):
            return x
        s = str(x).strip()
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def _load_csv_rows(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return reader.fieldnames or [], rows
    except Exception:
        return [], []


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0088
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2.0) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def _find_parsed_count_in_log(text: str) -> bool:
    if not text:
        return False
    patterns = [
        r"parsed\s+(\d+)",
        r"(\d+)\s+parsed",
        r"records\s*[:\-]\s*(\d+)",
        r"lines\s*[:\-]\s*(\d+)",
        r"rows\s*[:\-]\s*(\d+)",
    ]
    for pat in patterns:
        if re.search(pat, text, flags=re.IGNORECASE):
            return True
    return False


def _count_action_items(text: str) -> int:
    count = 0
    for line in text.splitlines():
        if ":" in line:
            if re.search(r"^\s*[\-\*\d\)\.]*\s*[A-Za-z][A-Za-z0-9 /&\-]+:\s+\S+", line):
                count += 1
    return count


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "raw_file_present": 0.0,
        "metadata_manifest_valid": 0.0,
        "logs_download_provenance": 0.0,
        "processed_csv_structure_valid": 0.0,
        "processed_csv_numeric_and_trimmed": 0.0,
        "logs_parse_summary_present": 0.0,
        "nearest_output_structure_valid": 0.0,
        "nearest_output_projects_covered_once": 0.0,
        "nearest_output_distances_correct_vs_stations": 0.0,
        "qa_report_content": 0.0,
        "meeting_notes_content": 0.0,
    }

    raw_txt = workspace / "data" / "raw" / "ghcnd-stations.txt"
    metadata_json = workspace / "data" / "raw" / "ghcnd-stations.metadata.json"
    logs_file = workspace / "logs" / "command_log.txt"
    stations_csv = workspace / "data" / "processed" / "stations.csv"
    nearest_csv = workspace / "outputs" / "nearest_weather_stations.csv"
    qa_md = workspace / "reports" / "qa_report.md"
    notes_md = workspace / "reports" / "meeting_notes.md"
    input_sites = workspace / "input" / "project_sites.csv"

    if raw_txt.exists() and raw_txt.is_file():
        try:
            size = raw_txt.stat().st_size
            if size > 0:
                scores["raw_file_present"] = 1.0
        except Exception:
            scores["raw_file_present"] = 0.0

    meta_ok = 0.0
    if metadata_json.exists():
        meta = _load_json(metadata_json)
        if isinstance(meta, dict):
            required_fields = [
                "source_organization",
                "resource_name",
                "file_name",
                "retrieved_at",
                "file_size_bytes",
                "sha256",
            ]
            has_all = all(k in meta for k in required_fields)
            if has_all and raw_txt.exists():
                rn_ok = str(meta.get("resource_name")) == "GHCN-Daily station list"
                fn_ok = str(meta.get("file_name")) == "ghcnd-stations.txt"
                ra_ok = _is_iso8601(str(meta.get("retrieved_at")))
                try:
                    actual_size = raw_txt.stat().st_size
                    fsb_ok = int(meta.get("file_size_bytes")) == actual_size
                except Exception:
                    fsb_ok = False
                sha_ok = str(meta.get("sha256")) == _compute_sha256(raw_txt)
                so = meta.get("source_organization")
                so_ok = isinstance(so, str) and so.strip() != ""
                if all([rn_ok, fn_ok, ra_ok, fsb_ok, sha_ok, so_ok]):
                    meta_ok = 1.0
    scores["metadata_manifest_valid"] = meta_ok

    log_score = 0.0
    if logs_file.exists() and logs_file.is_file():
        text = _read_text(logs_file)
        if text.strip():
            has_http = ("http://" in text) or ("https://" in text)
            mentions_resource = ("ghcnd-stations" in text.lower()) or ("ghcnd" in text.lower())
            if has_http and mentions_resource:
                log_score = 1.0
            elif has_http or mentions_resource:
                log_score = 0.5
            else:
                log_score = 0.0
    scores["logs_download_provenance"] = log_score

    struct_score = 0.0
    numeric_trim_score = 0.0
    fieldnames = []
    rows = []
    if stations_csv.exists() and stations_csv.is_file():
        fieldnames, rows = _load_csv_rows(stations_csv)
        required_cols = ["station_id", "latitude", "longitude", "elevation_m", "name", "state_or_country"]
        if all(col in fieldnames for col in required_cols):
            struct_score = 1.0

        all_lat_lon_numeric = True
        elev_numeric_if_present = True
        trimmed_ok = True
        for r in rows:
            lat = _safe_float(r.get("latitude"))
            lon = _safe_float(r.get("longitude"))
            if lat is None or lon is None:
                all_lat_lon_numeric = False
                break
            ev_raw = r.get("elevation_m")
            if ev_raw is not None and str(ev_raw).strip() != "":
                if _safe_float(ev_raw) is None:
                    elev_numeric_if_present = False
                    break
            sid = r.get("station_id")
            name = r.get("name")
            if isinstance(sid, str) and sid != sid.strip():
                trimmed_ok = False
                break
            if isinstance(name, str) and name != name.strip():
                trimmed_ok = False
                break

        part_numeric = 1.0 if (all_lat_lon_numeric and elev_numeric_if_present) else 0.0
        part_trim = 1.0 if trimmed_ok else 0.0
        numeric_trim_score = 0.5 * part_numeric + 0.5 * part_trim

    scores["processed_csv_structure_valid"] = struct_score
    scores["processed_csv_numeric_and_trimmed"] = numeric_trim_score

    parse_summary_score = 0.0
    if logs_file.exists() and logs_file.is_file():
        text = _read_text(logs_file)
        if _find_parsed_count_in_log(text):
            parse_summary_score = 1.0
    scores["logs_parse_summary_present"] = parse_summary_score

    nearest_struct_score = 0.0
    nearest_coverage_score = 0.0
    nearest_distance_correct_score = 0.0

    nearest_fns = []
    nearest_rows = []
    if nearest_csv.exists() and nearest_csv.is_file():
        nearest_fns, nearest_rows = _load_csv_rows(nearest_csv)
        required_nearest_cols = [
            "project",
            "site_latitude",
            "site_longitude",
            "station_id",
            "station_name",
            "station_latitude",
            "station_longitude",
            "distance_km",
        ]
        if all(c in nearest_fns for c in required_nearest_cols):
            numeric_ok = True
            for r in nearest_rows:
                if _safe_float(r.get("site_latitude")) is None:
                    numeric_ok = False
                    break
                if _safe_float(r.get("site_longitude")) is None:
                    numeric_ok = False
                    break
                if _safe_float(r.get("station_latitude")) is None:
                    numeric_ok = False
                    break
                if _safe_float(r.get("station_longitude")) is None:
                    numeric_ok = False
                    break
                if _safe_float(r.get("distance_km")) is None:
                    numeric_ok = False
                    break
            if numeric_ok:
                nearest_struct_score = 1.0

    if input_sites.exists() and input_sites.is_file():
        in_fns, in_rows = _load_csv_rows(input_sites)
        if all(x in in_fns for x in ["project", "latitude", "longitude"]):
            projects_in = [r.get("project") for r in in_rows if r.get("project") is not None]
            expected_set = set(projects_in)
            if nearest_rows:
                nearest_projects = [r.get("project") for r in nearest_rows if r.get("project") is not None]
                nearest_set = set(nearest_projects)
                unique_once = (len(nearest_projects) == len(set(nearest_projects)))
                same_set = (nearest_set == expected_set)
                nearest_coverage_score = 1.0 if (unique_once and same_set) else 0.0

    scores["nearest_output_structure_valid"] = nearest_struct_score
    scores["nearest_output_projects_covered_once"] = nearest_coverage_score

    if stations_csv.exists() and nearest_rows and input_sites.exists():
        fieldnames_st, rows_st = fieldnames, rows
        if not rows_st:
            fieldnames_st, rows_st = _load_csv_rows(stations_csv)
        stations_list = []
        if rows_st:
            for r in rows_st:
                sid = r.get("station_id")
                slat = _safe_float(r.get("latitude"))
                slon = _safe_float(r.get("longitude"))
                sname = r.get("name")
                if sid is None or sname is None:
                    continue
                if slat is None or slon is None:
                    continue
                stations_list.append((sid, sname, slat, slon))
        in_fns, in_rows = _load_csv_rows(input_sites)
        if stations_list and in_rows and all(k in in_fns for k in ["project", "latitude", "longitude"]):
            ok_all = True
            nearest_by_proj = {r.get("project"): r for r in nearest_rows if r.get("project") is not None}
            for site in in_rows:
                proj = site.get("project")
                slat = _safe_float(site.get("latitude"))
                slon = _safe_float(site.get("longitude"))
                if proj is None or slat is None or slon is None:
                    ok_all = False
                    break
                best = None
                best_dist = None
                for sid, sname, stlat, stlon in stations_list:
                    d = _haversine_km(slat, slon, stlat, stlon)
                    if best_dist is None or d < best_dist - 1e-12 or (abs(d - best_dist) <= 1e-12 and sid < best[0]):
                        best = (sid, sname, stlat, stlon)
                        best_dist = d
                out = nearest_by_proj.get(proj)
                if out is None:
                    ok_all = False
                    break
                out_sid = out.get("station_id")
                out_name = out.get("station_name")
                out_slat = _safe_float(out.get("station_latitude"))
                out_slon = _safe_float(out.get("station_longitude"))
                out_dist = _safe_float(out.get("distance_km"))
                if not (out_sid and out_name is not None and out_slat is not None and out_slon is not None and out_dist is not None):
                    ok_all = False
                    break
                if not (out_sid == best[0] and abs(out_slat - best[2]) < 1e-6 and abs(out_slon - best[3]) < 1e-6):
                    ok_all = False
                    break
                if round(out_dist, 3) != round(best_dist, 3):
                    ok_all = False
                    break
            if ok_all:
                nearest_distance_correct_score = 1.0

    scores["nearest_output_distances_correct_vs_stations"] = nearest_distance_correct_score

    qa_score = 0.0
    if qa_md.exists() and qa_md.is_file():
        text = _read_text(qa_md)
        if text.strip():
            sub = 0
            total = 4
            has_a = (("row count" in text.lower()) and ("stations.csv" in text.lower())) or re.search(r"rows?\s*[:\-]\s*\d+", text, flags=re.IGNORECASE)
            has_b = ("filtered" in text.lower() or "skipped" in text.lower()) and ("coordinate" in text.lower() or "lat" in text.lower() or "lon" in text.lower())
            has_c = ("logs/command_log.txt" in text) and (("error" in text.lower()) or ("warning" in text.lower()) or ("stderr" in text.lower()))
            has_d = (("min" in text.lower() and "max" in text.lower() and ("lat" in text.lower() or "latitude" in text.lower()) and ("lon" in text.lower() or "longitude" in text.lower()))
                     and ("nearest" in text.lower() and "distance" in text.lower()))
            sub += 1 if has_a else 0
            sub += 1 if has_b else 0
            sub += 1 if has_c else 0
            sub += 1 if has_d else 0
            qa_score = sub / total
    scores["qa_report_content"] = qa_score

    notes_score = 0.0
    if notes_md.exists() and notes_md.is_file():
        text = _read_text(notes_md)
        if text.strip():
            sub = 0
            total = 4
            has_purpose = bool(re.search(r"\bpurpose\b", text, flags=re.IGNORECASE))
            has_summary = ("nearest" in text.lower()) and (("downstream" in text.lower()) or ("workflow" in text.lower())) and (("climate" in text.lower()) or ("ai" in text.lower()))
            has_decisions = bool(re.search(r"key decisions", text, flags=re.IGNORECASE))
            ai_count = _count_action_items(text)
            has_actions = 4 <= ai_count <= 6
            sub += 1 if has_purpose else 0
            sub += 1 if has_summary else 0
            sub += 1 if has_decisions else 0
            sub += 1 if has_actions else 0
            notes_score = sub / total
    scores["meeting_notes_content"] = notes_score

    for k, v in list(scores.items()):
        try:
            fv = float(v)
        except Exception:
            fv = 0.0
        if fv < 0.0:
            fv = 0.0
        if fv > 1.0:
            fv = 1.0
        scores[k] = fv

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()