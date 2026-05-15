import csv
import json
import math
import hashlib
import sys
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _sha256_of_file(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader]
            header = reader.fieldnames or []
        return header, rows
    except Exception:
        return None


def _parse_makefile_targets(text: str) -> List[str]:
    targets = []
    for line in text.splitlines():
        if line.strip().startswith("#"):
            continue
        if ":" in line:
            if not line.startswith("\t") and not line.startswith(" ") and not line.startswith("."):
                left = line.split(":", 1)[0]
                if left and " " not in left and not left.startswith("#"):
                    targets.append(left.strip())
    return targets


def _parse_yaml_front_matter(md_text: str) -> Optional[dict]:
    lines = md_text.splitlines()
    if not lines:
        return None
    if lines[0].strip() != "---":
        return None
    content = {}
    i = 1
    in_yaml = True
    current_key = None
    shots_list: List[str] = []
    while i < len(lines) and in_yaml:
        line = lines[i]
        if line.strip() == "---":
            in_yaml = False
            break
        if current_key == "shots_needed" and line.strip().startswith("- "):
            item = line.strip()[2:].strip()
            if (item.startswith('"') and item.endswith('"')) or (item.startswith("'") and item.endswith("'")):
                item = item[1:-1]
            shots_list.append(item)
            i += 1
            continue
        if ":" in line:
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            if key == "shots_needed":
                current_key = "shots_needed"
                shots_list = []
            else:
                current_key = key
                if val.startswith('"') and val.endswith('"') and len(val) >= 2:
                    val = val[1:-1]
                if val.startswith("'") and val.endswith("'") and len(val) >= 2:
                    val = val[1:-1]
                content[key] = val
        else:
            if current_key == "shots_needed" and line.strip().startswith("- "):
                item = line.strip()[2:].strip()
                if (item.startswith('"') and item.endswith('"')) or (item.startswith("'") and item.endswith("'")):
                    item = item[1:-1]
                shots_list.append(item)
        i += 1
    if "shots_needed" in content or shots_list:
        content["shots_needed"] = shots_list
    required = ["story_id", "country", "iso_a2", "story_date", "shots_needed"]
    for r in required:
        if r not in content:
            if r == "shots_needed" and shots_list:
                continue
            return None
    return content


def _load_narratives(narratives_dir: Path) -> Optional[List[dict]]:
    if not narratives_dir.exists():
        return None
    results = []
    try:
        for p in sorted(narratives_dir.glob("*.md")):
            text = _read_text(p)
            if text is None:
                return None
            parsed = _parse_yaml_front_matter(text)
            if parsed is None:
                return None
            shots = parsed.get("shots_needed", [])
            if not isinstance(shots, list):
                return None
            results.append({
                "story_id": parsed.get("story_id", ""),
                "country": parsed.get("country", ""),
                "iso_a2": parsed.get("iso_a2", ""),
                "story_date": parsed.get("story_date", ""),
                "shots_needed": shots,
            })
        return results
    except Exception:
        return None


def _load_shot_catalog(path: Path) -> Optional[Dict[str, int]]:
    try:
        header, rows = _read_csv_dicts(path) or (None, None)
        if header is None or rows is None:
            return None
        expected_header = ["shot_key", "difficulty_1_to_5", "description"]
        if header != expected_header:
            return None
        catalog: Dict[str, int] = {}
        for row in rows:
            key = row.get("shot_key")
            diff = row.get("difficulty_1_to_5")
            if key is None or diff is None:
                return None
            try:
                diff_int = int(diff)
            except Exception:
                return None
            catalog[key] = diff_int
        return catalog
    except Exception:
        return None


def _parse_country_info(path: Path) -> Optional[Dict[str, Dict[str, str]]]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    header_fields: Optional[List[str]] = None
    rows: Dict[str, Dict[str, str]] = {}
    for line in text.splitlines():
        if not line:
            continue
        if line.startswith("#"):
            if line.startswith("#ISO"):
                hdr = line[1:].strip()
                header_fields = hdr.split("\t")
            continue
        if header_fields is None:
            return None
        parts = line.split("\t")
        if len(parts) < len(header_fields):
            parts += [""] * (len(header_fields) - len(parts))
        record = {header_fields[i]: parts[i] if i < len(parts) else "" for i in range(len(header_fields))}
        iso = record.get("ISO", "").strip()
        if not iso:
            continue
        pop_str = record.get("Population", "").strip()
        rows[iso] = {
            "ISO": iso,
            "Country": record.get("Country", "").strip(),
            "Capital": record.get("Capital", "").strip(),
            "Population": pop_str,
        }
    return rows


def _to_int(s: str) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        return None


def _looks_like_iso8601(s: str) -> bool:
    if not isinstance(s, str):
        return False
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}T", s))


def _https_geonames_domain(url: str) -> bool:
    if not isinstance(url, str):
        return False
    if not url.lower().startswith("https://"):
        return False
    m = re.match(r"^https://([^/]+)/", url.lower() + "/")
    if not m:
        return False
    host = m.group(1)
    return host.endswith("geonames.org")


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "makefile_targets_present": 0.0,
        "requirements_present": 0.0,
        "data_file_present": 0.0,
        "manifest_exists_and_schema": 0.0,
        "manifest_url_and_domain_https": 0.0,
        "manifest_sha256_and_length_match": 0.0,
        "priority_ranked_csv_structure": 0.0,
        "priority_ranked_sorted_desc": 0.0,
        "priority_ranked_row_count_match": 0.0,
        "priority_ranked_computed_values": 0.0,
        "cross_sha256_consistency": 0.0,
        "country_profiles_csv_structure": 0.0,
        "country_profiles_computed_values": 0.0,
        "process_counts_match": 0.0,
        "idempotency_signal": 0.0,
    }

    makefile_path = workspace / "Makefile"
    make_targets = []
    if makefile_path.exists():
        mf_text = _read_text(makefile_path) or ""
        make_targets = _parse_makefile_targets(mf_text)
        required_targets = ["setup", "fetch", "build", "clean"]
        present = sum(1 for t in required_targets if t in make_targets)
        scores["makefile_targets_present"] = present / len(required_targets)
    else:
        scores["makefile_targets_present"] = 0.0

    req_path = workspace / "requirements.txt"
    if req_path.exists():
        text = _read_text(req_path) or ""
        nonempty = [ln for ln in (text.splitlines()) if ln.strip() and not ln.strip().startswith("#")]
        scores["requirements_present"] = 1.0 if nonempty else 0.0
    else:
        scores["requirements_present"] = 0.0

    data_path = workspace / "data" / "countryInfo.txt"
    data_sha = _sha256_of_file(data_path) if data_path.exists() else None
    if data_path.exists():
        scores["data_file_present"] = 1.0
    else:
        scores["data_file_present"] = 0.0

    narratives = _load_narratives(workspace / "input" / "narratives")
    catalog = _load_shot_catalog(workspace / "input" / "shot_catalog.csv")
    country_info = _parse_country_info(data_path) if data_path.exists() else None

    manifest_path = workspace / "build" / "manifest.json"
    manifest = _load_json(manifest_path) if manifest_path.exists() else None

    if manifest is not None and isinstance(manifest, dict):
        dr = manifest.get("downloaded_resource", {})
        pr = manifest.get("process", {})
        required_dr = ["resource_name", "source_domain", "url_used", "http_status", "content_length", "sha256"]
        required_pr = ["narratives_count", "countries_count", "run_started_at", "run_completed_at", "python_version", "platform"]
        schema_ok = all(k in dr for k in required_dr) and all(k in pr for k in required_pr)
        if schema_ok:
            types_ok = isinstance(dr.get("resource_name"), str) and isinstance(dr.get("source_domain"), str) and \
                       isinstance(dr.get("url_used"), str) and isinstance(dr.get("http_status"), (int, float)) and \
                       isinstance(dr.get("content_length"), (int, float)) and isinstance(dr.get("sha256"), str) and \
                       isinstance(pr.get("narratives_count"), int) and isinstance(pr.get("countries_count"), int) and \
                       isinstance(pr.get("python_version"), str) and isinstance(pr.get("platform"), str) and \
                       isinstance(pr.get("run_started_at"), str) and isinstance(pr.get("run_completed_at"), str)
            timestamps_ok = _looks_like_iso8601(pr.get("run_started_at")) and _looks_like_iso8601(pr.get("run_completed_at"))
            if types_ok and timestamps_ok:
                scores["manifest_exists_and_schema"] = 1.0
            else:
                scores["manifest_exists_and_schema"] = 0.0
        else:
            scores["manifest_exists_and_schema"] = 0.0
        url_ok = _https_geonames_domain(dr.get("url_used", "")) if isinstance(dr, dict) else False
        domain_ok = (dr.get("source_domain") == "geonames.org") if isinstance(dr, dict) else False
        resource_ok = (dr.get("resource_name") == "countryInfo.txt") if isinstance(dr, dict) else False
        scores["manifest_url_and_domain_https"] = 1.0 if (url_ok and domain_ok and resource_ok) else 0.0
        if data_path.exists():
            actual_sha = data_sha
            try:
                actual_len = data_path.stat().st_size
            except Exception:
                actual_len = None
            sha_ok = (dr.get("sha256") == actual_sha) if actual_sha else False
            len_ok = (int(dr.get("content_length")) == actual_len) if (actual_len is not None and isinstance(dr.get("content_length"), (int, float))) else False
            scores["manifest_sha256_and_length_match"] = 1.0 if (sha_ok and len_ok) else 0.0
        else:
            scores["manifest_sha256_and_length_match"] = 0.0
    else:
        scores["manifest_exists_and_schema"] = 0.0
        scores["manifest_url_and_domain_https"] = 0.0
        scores["manifest_sha256_and_length_match"] = 0.0

    ranked_path = workspace / "build" / "priority_ranked.csv"
    ranked_header: List[str] = []
    ranked_rows: List[Dict[str, str]] = []
    ranked_exists = ranked_path.exists()
    if ranked_exists:
        read_r = _read_csv_dicts(ranked_path)
        if read_r is not None:
            ranked_header, ranked_rows = read_r
            expected_header = [
                "story_id",
                "country",
                "iso_a2",
                "capital",
                "population",
                "shot_count",
                "total_difficulty",
                "final_score",
                "source_data_sha256",
            ]
            if ranked_header == expected_header:
                scores["priority_ranked_csv_structure"] = 1.0
            else:
                scores["priority_ranked_csv_structure"] = 0.0
        else:
            scores["priority_ranked_csv_structure"] = 0.0
    else:
        scores["priority_ranked_csv_structure"] = 0.0

    profiles_path = workspace / "build" / "country_profiles.csv"
    profiles_header: List[str] = []
    profiles_rows: List[Dict[str, str]] = []
    if profiles_path.exists():
        read_p = _read_csv_dicts(profiles_path)
        if read_p is not None:
            profiles_header, profiles_rows = read_p
            expected_p_header = ["country", "iso_a2", "capital", "population", "stories", "total_shots", "total_difficulty"]
            if profiles_header == expected_p_header:
                scores["country_profiles_csv_structure"] = 1.0
            else:
                scores["country_profiles_csv_structure"] = 0.0
        else:
            scores["country_profiles_csv_structure"] = 0.0
    else:
        scores["country_profiles_csv_structure"] = 0.0

    expected_included: List[dict] = []
    if narratives is not None and catalog is not None and country_info is not None:
        for n in narratives:
            iso = n.get("iso_a2", "")
            ci = country_info.get(iso)
            if not ci:
                continue
            pop_str = ci.get("Population", "")
            pop = _to_int(pop_str) if pop_str is not None and pop_str != "" else None
            if pop is None or pop <= 0:
                continue
            shots = n.get("shots_needed", [])
            missing_key = False
            total_diff = 0
            for sk in shots:
                if sk not in catalog:
                    missing_key = True
                    break
                total_diff += catalog[sk]
            if missing_key:
                continue
            shot_count = len(shots)
            final_score = (2 * shot_count) + total_diff + math.log10(pop)
            final_score_rounded = f"{round(final_score, 3):.3f}"
            expected_included.append({
                "story_id": n.get("story_id", ""),
                "country": ci.get("Country", ""),
                "iso_a2": iso,
                "capital": ci.get("Capital", ""),
                "population": str(pop),
                "shot_count": str(shot_count),
                "total_difficulty": str(total_diff),
                "final_score": final_score_rounded,
            })
    if expected_included:
        expected_included.sort(key=lambda r: float(r["final_score"]), reverse=True)

    if ranked_rows is not None and expected_included is not None:
        if expected_included:
            scores["priority_ranked_row_count_match"] = 1.0 if len(ranked_rows) == len(expected_included) else 0.0
        else:
            scores["priority_ranked_row_count_match"] = 0.0

    if ranked_rows:
        try:
            finals = [float(r["final_score"]) for r in ranked_rows if "final_score" in r and r["final_score"] != ""]
            sorted_ok = all(finals[i] >= finals[i + 1] for i in range(len(finals) - 1))
            scores["priority_ranked_sorted_desc"] = 1.0 if sorted_ok and len(finals) == len(ranked_rows) else 0.0
        except Exception:
            scores["priority_ranked_sorted_desc"] = 0.0
    else:
        scores["priority_ranked_sorted_desc"] = 0.0

    if ranked_rows and expected_included:
        actual_by_story = {r.get("story_id"): r for r in ranked_rows}
        matched = 0
        for exp in expected_included:
            act = actual_by_story.get(exp["story_id"])
            if not act:
                continue
            fields_ok = (
                act.get("country") == exp["country"] and
                act.get("iso_a2") == exp["iso_a2"] and
                act.get("capital") == exp["capital"] and
                str(act.get("population")) == exp["population"] and
                str(act.get("shot_count")) == exp["shot_count"] and
                str(act.get("total_difficulty")) == exp["total_difficulty"] and
                str(act.get("final_score")) == exp["final_score"]
            )
            sha_ok = True
            if data_sha is not None:
                sha_ok = (act.get("source_data_sha256") == data_sha)
            fields_ok = fields_ok and sha_ok
            if fields_ok:
                matched += 1
        scores["priority_ranked_computed_values"] = matched / len(expected_included) if expected_included else 0.0
    else:
        scores["priority_ranked_computed_values"] = 0.0

    if ranked_rows and manifest is not None and isinstance(manifest, dict):
        dr = manifest.get("downloaded_resource", {})
        sha_manifest = dr.get("sha256") if isinstance(dr, dict) else None
        if sha_manifest and all(r.get("source_data_sha256") == sha_manifest for r in ranked_rows):
            scores["cross_sha256_consistency"] = 1.0
        else:
            scores["cross_sha256_consistency"] = 0.0
    else:
        scores["cross_sha256_consistency"] = 0.0

    if profiles_rows and expected_included:
        agg_expected: Dict[str, Dict[str, str]] = {}
        for r in expected_included:
            iso = r["iso_a2"]
            if iso not in agg_expected:
                agg_expected[iso] = {
                    "country": r["country"],
                    "iso_a2": iso,
                    "capital": r["capital"],
                    "population": r["population"],
                    "stories": 0,
                    "total_shots": 0,
                    "total_difficulty": 0,
                }
            agg_expected[iso]["stories"] += 1
            agg_expected[iso]["total_shots"] += int(r["shot_count"])
            agg_expected[iso]["total_difficulty"] += int(r["total_difficulty"])
        actual_by_iso = {row.get("iso_a2"): row for row in profiles_rows}
        matched_groups = 0
        for iso, exp in agg_expected.items():
            act = actual_by_iso.get(iso)
            if not act:
                continue
            ok = (
                act.get("country") == exp["country"] and
                act.get("iso_a2") == exp["iso_a2"] and
                act.get("capital") == exp["capital"] and
                str(act.get("population")) == str(exp["population"]) and
                str(act.get("stories")) == str(exp["stories"]) and
                str(act.get("total_shots")) == str(exp["total_shots"]) and
                str(act.get("total_difficulty")) == str(exp["total_difficulty"])
            )
            if ok:
                matched_groups += 1
        scores["country_profiles_computed_values"] = matched_groups / len(agg_expected) if agg_expected else 0.0
    else:
        scores["country_profiles_computed_values"] = 0.0

    if manifest is not None and isinstance(manifest, dict) and expected_included is not None:
        pr = manifest.get("process", {}) if isinstance(manifest.get("process"), dict) else {}
        if isinstance(pr, dict) and "narratives_count" in pr and "countries_count" in pr:
            expected_count = len(expected_included)
            expected_countries = len(set([r["iso_a2"] for r in expected_included]))
            try:
                nc_ok = int(pr.get("narratives_count")) == expected_count
                cc_ok = int(pr.get("countries_count")) == expected_countries
                scores["process_counts_match"] = 1.0 if (nc_ok and cc_ok) else 0.0
            except Exception:
                scores["process_counts_match"] = 0.0
        else:
            scores["process_counts_match"] = 0.0
    else:
        scores["process_counts_match"] = 0.0

    idempotency_ok = (
        scores["priority_ranked_sorted_desc"] == 1.0 and
        scores["cross_sha256_consistency"] == 1.0 and
        scores["manifest_sha256_and_length_match"] == 1.0
    )
    scores["idempotency_signal"] = 1.0 if idempotency_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()