import json
import csv
import hashlib
from pathlib import Path
from datetime import datetime, timezone
import sys
import re


def _safe_load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_load_jsonl(path: Path):
    items = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except Exception:
                    return None
        return items
    except Exception:
        return None


def _safe_read_text_lines(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return [line.rstrip("\r\n") for line in f.readlines()]
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path):
    rows = []
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                rows.append(r)
        return rows
    except Exception:
        return None


def _parse_iso8601_z(ts: str):
    # Expect "YYYY-MM-DDTHH:MM:SSZ"
    try:
        if ts.endswith("Z"):
            return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        # Accept offsets like +00:00
        try:
            # Try parsing ISO 8601 with timezone offset if 'Z' not present
            # Python stdlib doesn't have fromisoformat for 'Z', but supports offsets
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is not None:
                return dt.astimezone(timezone.utc)
        except Exception:
            pass
    except Exception:
        return None
    return None


def _isoformat_z(dt: datetime) -> str:
    # Return ISO 8601 with 'Z'
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_hex(path: Path) -> str:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _slugify_course(name: str) -> str:
    # lowercased, spaces -> hyphens, remove non-alphanumerics except hyphen
    s = name.lower()
    s = re.sub(r"\s+", "-", s.strip())
    s = re.sub(r"[^a-z0-9\-]", "", s)
    s = re.sub(r"-{2,}", "-", s)
    s = s.strip("-")
    return s


def _compute_expected(rows: list, priority_species: list):
    # rows: list of dicts with columns:
    # timestamp,course_name,hole_number,habitat,species,count,notes
    timestamps = []
    total_records = 0
    total_birds = 0
    species_counts = {}
    sightings_by_habitat = {}
    by_course = {}

    for r in rows:
        ts = r.get("timestamp", "")
        dt = _parse_iso8601_z(ts)
        if dt is None:
            continue
        timestamps.append(dt)
        total_records += 1
        try:
            cnt = int(r.get("count", "0"))
        except Exception:
            cnt = 0
        total_birds += cnt
        species = r.get("species", "").strip()
        habitat = r.get("habitat", "").strip()
        course = r.get("course_name", "").strip()

        species_counts[species] = species_counts.get(species, 0) + cnt
        sightings_by_habitat[habitat] = sightings_by_habitat.get(habitat, 0) + 1

        c = by_course.setdefault(course, {
            "records": 0,
            "total_birds": 0,
            "species_counts": {},
            "sightings_by_habitat": {},
        })
        c["records"] += 1
        c["total_birds"] += cnt
        c["species_counts"][species] = c["species_counts"].get(species, 0) + cnt
        c["sightings_by_habitat"][habitat] = c["sightings_by_habitat"].get(habitat, 0) + 1

    start_iso = _isoformat_z(min(timestamps)) if timestamps else ""
    end_iso = _isoformat_z(max(timestamps)) if timestamps else ""
    unique_species_count = len(species_counts)

    # add derived fields to by_course
    by_course_final = {}
    for course, data in by_course.items():
        present = []
        for ps in priority_species:
            if ps in data["species_counts"] and data["species_counts"][ps] > 0:
                present.append(ps)
        by_course_final[course] = {
            "records": data["records"],
            "total_birds": data["total_birds"],
            "unique_species_count": len(data["species_counts"]),
            "species_counts": data["species_counts"],
            "sightings_by_habitat": data["sightings_by_habitat"],
            "priority_species_present": present,
        }

    return {
        "date_range": {"start_iso": start_iso, "end_iso": end_iso},
        "total_records": total_records,
        "total_birds_counted": total_birds,
        "unique_species_count": unique_species_count,
        "species_counts": species_counts,
        "sightings_by_habitat": sightings_by_habitat,
        "by_course": by_course_final,
    }


def _top_n_species(species_counts: dict, n: int):
    # Deterministic sort by descending count, then species name ascending
    items = sorted(species_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return items[:n]


def _extract_header_and_body(lines: list):
    if lines is None or len(lines) < 5:
        return None, None
    header = lines[:4]
    body = lines[4:]
    return header, body


def _parse_to_recipients(line: str):
    if not line.startswith("To:"):
        return None
    _, rest = line.split(":", 1)
    rest = rest.strip()
    if rest == "":
        return []
    parts = [p.strip() for p in rest.split(",")]
    return parts


def _check_subject_line(line: str, subject_prefix: str, course_name: str, start_date: str, end_date: str, unique_species_count: int, total_birds: int):
    expected = f"Subject: {subject_prefix} {course_name} {start_date} to {end_date}: {unique_species_count} species, {total_birds} birds"
    return line == expected


def _line_contains_count_for_token(line: str, token: str, count: int):
    # Check if line contains the token and the exact count number as a whole number
    if token not in line:
        return False
    # match number boundaries
    pattern = r"(?:^|[^0-9])" + re.escape(str(count)) + r"(?:[^0-9]|$)"
    return re.search(pattern, line) is not None


def _body_mentions_total_records(body_lines: list, records: int):
    for line in body_lines:
        if re.search(r"record", line, flags=re.IGNORECASE) and _line_contains_count_for_token(line, "", records):
            return True
    return False


def _body_mentions_habitat_counts(body_lines: list, habitat_counts: dict):
    # Ensure each habitat and its count are mentioned together somewhere
    for habitat, cnt in habitat_counts.items():
        found = False
        for line in body_lines:
            if habitat in line and _line_contains_count_for_token(line, "", cnt):
                found = True
                break
        if not found:
            return False
    return True


def _body_mentions_priority_species(body_lines: list, present: list):
    text = "\n".join(body_lines)
    if present:
        for sp in present:
            if sp not in text:
                return False
        return True
    else:
        # look for 'none' mention
        return re.search(r"\bnone\b", text, flags=re.IGNORECASE) is not None


def _body_lists_top_species(body_lines: list, species_counts: dict, allow_either_for_third_set: set = None):
    top3 = _top_n_species(species_counts, 3)

    def species_count_mentioned(species: str, count: int) -> bool:
        for line in body_lines:
            if species in line and _line_contains_count_for_token(line, species, count):
                return True
            if species in line and _line_contains_count_for_token(line, "", count):
                return True
        return False

    # If allow_either_for_third_set is provided, ensure first two exact, third may be any of the set with count 1
    if allow_either_for_third_set:
        # Require first two
        need_pairs = top3[:2]
        for sp, cnt in need_pairs:
            if not species_count_mentioned(sp, cnt):
                return False
        # Third can be any from allow_either_for_third_set with their expected counts
        third_ok = False
        for sp in allow_either_for_third_set:
            cnt = species_counts.get(sp, None)
            if cnt is None:
                continue
            if species_count_mentioned(sp, cnt):
                third_ok = True
                break
        return third_ok
    else:
        for sp, cnt in top3:
            if not species_count_mentioned(sp, cnt):
                return False
        return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "summary_file_exists": 0.0,
        "summary_json_valid": 0.0,
        "summary_content_correct": 0.0,
        "emails_exist_for_courses": 0.0,
        "email_headers_willow_creek_golf_club": 0.0,
        "email_headers_pine_ridge_links": 0.0,
        "email_body_willow_creek_golf_club": 0.0,
        "email_body_pine_ridge_links": 0.0,
        "state_file_exists": 0.0,
        "state_has_entry_for_csv": 0.0,
        "state_paths_reference_outputs": 0.0,
        "state_processed_at_utc": 0.0,
        "state_no_duplicate_sha": 0.0,
    }

    # Expected input and config
    input_csv_rel = "input/sightings/2026-04-15_sightings.csv"
    input_csv_path = workspace / input_csv_rel
    config_path = workspace / "input/config/notify_config.json"

    rows = _safe_read_csv_dicts(input_csv_path)
    config = _safe_load_json(config_path)

    if rows is None or config is None:
        # If missing essential inputs, we cannot compute expected; all checks remain 0.0
        return scores

    recipients_map = config.get("recipients", {})
    priority_species = config.get("priority_species", [])
    email_from = config.get("email_from", "")
    subject_prefix = config.get("subject_prefix", "")

    expected = _compute_expected(rows, priority_species)
    # Build expected file outputs
    basename = Path(input_csv_rel).name.rsplit(".", 1)[0]
    expected_summary_rel = f"out/summary/{basename}.summary.json"
    expected_summary_path = workspace / expected_summary_rel

    # Courses present:
    courses = list(expected["by_course"].keys())
    # Compute expected email paths
    expected_email_paths = {}
    for course in courses:
        slug = _slugify_course(course)
        rel = f"out/emails/{basename}__{slug}.txt"
        expected_email_paths[course] = rel

    # Summary checks
    if expected_summary_path.exists():
        scores["summary_file_exists"] = 1.0
        summary = _safe_load_json(expected_summary_path)
        if summary is not None:
            scores["summary_json_valid"] = 1.0
            # Check content
            content_ok = True
            # Required keys
            required_top_keys = [
                "file",
                "date_range",
                "total_records",
                "total_birds_counted",
                "unique_species_count",
                "species_counts",
                "sightings_by_habitat",
                "by_course",
            ]
            for k in required_top_keys:
                if k not in summary:
                    content_ok = False
                    break
            if content_ok:
                # file path equals relative
                if summary.get("file") != input_csv_rel:
                    content_ok = False
                # date range
                dr = summary.get("date_range", {})
                if not isinstance(dr, dict):
                    content_ok = False
                else:
                    if dr.get("start_iso") != expected["date_range"]["start_iso"]:
                        content_ok = False
                    if dr.get("end_iso") != expected["date_range"]["end_iso"]:
                        content_ok = False
                # totals
                if summary.get("total_records") != expected["total_records"]:
                    content_ok = False
                if summary.get("total_birds_counted") != expected["total_birds_counted"]:
                    content_ok = False
                if summary.get("unique_species_count") != expected["unique_species_count"]:
                    content_ok = False
                # species_counts dict equality
                if summary.get("species_counts") != expected["species_counts"]:
                    content_ok = False
                # sightings_by_habitat equality
                if summary.get("sightings_by_habitat") != expected["sightings_by_habitat"]:
                    content_ok = False
                # by_course structure and content
                bc = summary.get("by_course")
                if not isinstance(bc, dict):
                    content_ok = False
                else:
                    # All expected courses present
                    for course in expected["by_course"]:
                        if course not in bc:
                            content_ok = False
                            break
                        got = bc[course]
                        exp = expected["by_course"][course]
                        # Check required keys
                        reqc = [
                            "records",
                            "total_birds",
                            "unique_species_count",
                            "species_counts",
                            "sightings_by_habitat",
                            "priority_species_present",
                        ]
                        for kk in reqc:
                            if kk not in got:
                                content_ok = False
                                break
                        if not content_ok:
                            break
                        if got["records"] != exp["records"]:
                            content_ok = False
                        if got["total_birds"] != exp["total_birds"]:
                            content_ok = False
                        if got["unique_species_count"] != exp["unique_species_count"]:
                            content_ok = False
                        if got["species_counts"] != exp["species_counts"]:
                            content_ok = False
                        if got["sightings_by_habitat"] != exp["sightings_by_habitat"]:
                            content_ok = False
                        # Priority species list order should follow config order; compare exact list
                        if got["priority_species_present"] != exp["priority_species_present"]:
                            content_ok = False
                        if not content_ok:
                            break
            if content_ok:
                scores["summary_content_correct"] = 1.0

    # Email files and content checks
    email_exist_ok = True
    for course, rel in expected_email_paths.items():
        if not (workspace / rel).exists():
            email_exist_ok = False
            break
    if email_exist_ok:
        scores["emails_exist_for_courses"] = 1.0

    # Compute dates for subject headers
    start_date = expected["date_range"]["start_iso"][:10] if expected["date_range"]["start_iso"] else ""
    end_date = expected["date_range"]["end_iso"][:10] if expected["date_range"]["end_iso"] else ""

    # Check each course email headers and body
    for course, rel in expected_email_paths.items():
        email_lines = _safe_read_text_lines(workspace / rel)
        if email_lines is None or len(email_lines) < 5:
            # not enough content
            continue
        header, body = _extract_header_and_body(email_lines)
        if header is None or body is None:
            continue
        # Header must be exactly 3 lines then a blank line
        line_to = header[0]
        line_from = header[1]
        line_subject = header[2]
        line_blank = header[3] == ""

        # Recipients
        expected_recipients = recipients_map.get(course, [])
        parsed_recipients = _parse_to_recipients(line_to)
        to_ok = parsed_recipients is not None and parsed_recipients == expected_recipients

        from_ok = (line_from == f"From: {email_from}")

        uc = expected["by_course"][course]["unique_species_count"]
        tb = expected["by_course"][course]["total_birds"]

        subj_ok = _check_subject_line(
            line_subject,
            subject_prefix,
            course,
            start_date,
            end_date,
            uc,
            tb,
        )

        header_ok = bool(to_ok and from_ok and subj_ok and line_blank)
        if "Willow Creek Golf Club" in course:
            scores["email_headers_willow_creek_golf_club"] = 1.0 if header_ok else 0.0
        elif "Pine Ridge Links" in course:
            scores["email_headers_pine_ridge_links"] = 1.0 if header_ok else 0.0

        # Body checks
        course_info = expected["by_course"][course]
        species_counts_course = course_info["species_counts"]
        prs = course_info["priority_species_present"]

        # Determine if third top species tie acceptance needed
        allow_either = set()
        # Determine ranked top 3; if tie for third exists with multiple species having same count and more than 3 species,
        # allow any among tied set for the third slot.
        sorted_species = sorted(species_counts_course.items(), key=lambda kv: (-kv[1], kv[0]))
        if len(sorted_species) >= 4:
            third_count = sorted_species[2][1]
            tied = [sp for sp, cnt in sorted_species if cnt == third_count]
            if len(tied) > 1:
                allow_either = set(tied)

        if allow_either:
            top_ok = _body_lists_top_species(body, species_counts_course, allow_either_for_third_set=allow_either)
        else:
            top_ok = _body_lists_top_species(body, species_counts_course)

        records_ok = _body_mentions_total_records(body, course_info["records"])
        habitat_ok = _body_mentions_habitat_counts(body, course_info["sightings_by_habitat"])
        priority_ok = _body_mentions_priority_species(body, prs)

        body_ok = bool(top_ok and records_ok and habitat_ok and priority_ok)

        if "Willow Creek Golf Club" in course:
            scores["email_body_willow_creek_golf_club"] = 1.0 if body_ok else 0.0
        elif "Pine Ridge Links" in course:
            scores["email_body_pine_ridge_links"] = 1.0 if body_ok else 0.0

    # State file checks
    state_path = workspace / "state/processed.jsonl"
    if state_path.exists():
        scores["state_file_exists"] = 1.0
        items = _safe_load_jsonl(state_path)
        if items is not None:
            # compute sha
            file_sha = _sha256_hex(input_csv_path)
            # find entries with same sha
            matching = [it for it in items if isinstance(it, dict) and it.get("sha256") == file_sha and it.get("file") == input_csv_rel]
            if matching:
                scores["state_has_entry_for_csv"] = 1.0
                entry = matching[-1]
                # Paths referenced
                summary_path_ref = entry.get("summary_path")
                email_paths_ref = entry.get("email_paths")
                paths_ok = True
                if summary_path_ref != expected_summary_rel:
                    paths_ok = False
                if not isinstance(email_paths_ref, list):
                    paths_ok = False
                else:
                    # Compare as sets
                    expected_email_rel_set = set(expected_email_paths.values())
                    email_ref_set = set(email_paths_ref)
                    if email_ref_set != expected_email_rel_set:
                        paths_ok = False
                # Also ensure the referenced files exist
                if paths_ok:
                    if not expected_summary_path.exists():
                        paths_ok = False
                    for rel in email_paths_ref:
                        if not (workspace / rel).exists():
                            paths_ok = False
                scores["state_paths_reference_outputs"] = 1.0 if paths_ok else 0.0

                # processed_at validity (ISO 8601 UTC)
                processed_at = entry.get("processed_at", "")
                pa_ok = False
                # Accept 'Z' or '+00:00' as UTC
                try:
                    if processed_at.endswith("Z"):
                        dt = datetime.strptime(processed_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                        pa_ok = True
                    else:
                        dt = datetime.fromisoformat(processed_at)
                        if dt.tzinfo is not None and dt.utcoffset() == timezone.utc.utcoffset(dt):
                            pa_ok = True
                except Exception:
                    pa_ok = False
                scores["state_processed_at_utc"] = 1.0 if pa_ok else 0.0

            # No duplicate entries for same sha256
            same_sha = [it for it in items if isinstance(it, dict) and it.get("sha256") == file_sha]
            scores["state_no_duplicate_sha"] = 1.0 if len(same_sha) <= 1 and len(same_sha) >= 1 else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()