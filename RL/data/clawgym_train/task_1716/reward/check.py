import json
import csv
import sys
import subprocess
import shlex
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
        return None
    except Exception:
        return None


def _safe_load_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        objs: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                obj = json.loads(s)
                if not isinstance(obj, dict):
                    return None
                objs.append(obj)
        return objs
    except Exception:
        return None


def _safe_load_csv_semicolon(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        rows: List[Dict[str, str]] = []
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                # Normalize whitespace for all string values
                norm_row = {k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
                rows.append(norm_row)
        return rows
    except Exception:
        return None


def _normalize_status(raw: str) -> str:
    s = (raw or "").strip().lower()
    if s == "yes":
        return "yes"
    if s in {"no", "declined"}:
        return "no"
    if s == "maybe":
        return "maybe"
    if s in {"pending", "", "no response", "no_response"}:
        return "no_response"
    # Default to no_response for unknowns
    return "no_response"


def _compute_expected_stats(workspace: Path) -> Optional[Dict[str, Any]]:
    restaurants_path = workspace / "data" / "restaurants.jsonl"
    invites_path = workspace / "data" / "invitations.csv"

    restaurants = _safe_load_jsonl(restaurants_path)
    invites = _safe_load_csv_semicolon(invites_path)
    if restaurants is None or invites is None:
        return None

    region_by_restaurant: Dict[str, str] = {}
    country_by_restaurant: Dict[str, str] = {}
    for r in restaurants:
        rid = r.get("id")
        if isinstance(rid, str):
            region_by_restaurant[rid] = r.get("region") or "UNKNOWN"
            country_by_restaurant[rid] = r.get("country") or "UNKNOWN"

    # Deduplicate by email (case-insensitive), keep most recent record by ISO-8601 timestamp
    latest_by_email: Dict[str, Dict[str, str]] = {}
    for row in invites:
        email = (row.get("email") or "").strip().lower()
        if not email:
            # skip malformed row
            continue
        ts = (row.get("timestamp") or "").strip()
        prev = latest_by_email.get(email)
        if prev is None or ts > prev.get("timestamp", ""):
            latest_by_email[email] = {
                "email": email,
                "restaurant_id": (row.get("restaurant_id") or "").strip(),
                "status": _normalize_status(row.get("status") or ""),
                "timestamp": ts,
            }

    # Compute totals
    totals = {"invited": 0, "yes": 0, "no": 0, "maybe": 0, "no_response": 0}
    totals["invited"] = len(latest_by_email)
    for rec in latest_by_email.values():
        status = rec["status"]
        if status in totals:
            totals[status] += 1
        else:
            totals["no_response"] += 1

    # by_region
    by_region: Dict[str, Dict[str, Any]] = {}
    for rec in latest_by_email.values():
        rid = rec.get("restaurant_id")
        region = region_by_restaurant.get(rid, "UNKNOWN")
        if region not in by_region:
            by_region[region] = {"invited": 0, "yes": 0, "no": 0, "maybe": 0, "no_response": 0, "response_rate": 0.0}
        by_region[region]["invited"] += 1
        by_region[region][rec["status"]] += 1

    for region, stats in by_region.items():
        responded = stats["yes"] + stats["no"] + stats["maybe"]
        invited = stats["invited"]
        rr = (responded / invited) if invited > 0 else 0.0
        # Round to 2 decimals
        stats["response_rate"] = round(rr + 1e-12, 2)

    # top_countries_by_yes
    yes_by_country: Dict[str, int] = {}
    for rec in latest_by_email.values():
        if rec["status"] != "yes":
            continue
        rid = rec.get("restaurant_id")
        country = country_by_restaurant.get(rid, "UNKNOWN")
        yes_by_country[country] = yes_by_country.get(country, 0) + 1

    # Sort by yes desc, then by country name alphabetically
    sorted_countries = sorted(yes_by_country.items(), key=lambda kv: (-kv[1], kv[0]))
    top3 = [{"country": c, "yes": y} for c, y in sorted_countries[:3]]
    # Ensure length exactly 3 if possible; if fewer, it's okay to have fewer, but spec says 3
    # We'll not pad with zeros.

    return {"totals": totals, "by_region": by_region, "top_countries_by_yes": top3}


def _run_analyze_script(workspace: Path) -> Tuple[bool, str]:
    script = workspace / "scripts" / "analyze_event.py"
    if not script.exists():
        return False, "missing_script"
    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
            text=True,
        )
        success = proc.returncode == 0
        return success, proc.stderr.strip() if not success else ""
    except Exception as e:
        return False, str(e)


def _float_close(a: float, b: float, tol: float = 0.005) -> bool:
    return abs(a - b) <= tol


def _check_stats_structure(stats: Dict[str, Any]) -> bool:
    if not isinstance(stats, dict):
        return False
    if "totals" not in stats or "by_region" not in stats or "top_countries_by_yes" not in stats:
        return False
    totals = stats["totals"]
    if not isinstance(totals, dict):
        return False
    for k in ["invited", "yes", "no", "maybe", "no_response"]:
        if k not in totals:
            return False
        if not isinstance(totals[k], int):
            return False
    by_region = stats["by_region"]
    if not isinstance(by_region, dict):
        return False
    for region, reg_stats in by_region.items():
        if not isinstance(reg_stats, dict):
            return False
        for k in ["invited", "yes", "no", "maybe", "no_response", "response_rate"]:
            if k not in reg_stats:
                return False
        if not isinstance(reg_stats["invited"], int):
            return False
        for k in ["yes", "no", "maybe", "no_response"]:
            if not isinstance(reg_stats[k], int):
                return False
        if not isinstance(reg_stats["response_rate"], (int, float)):
            return False
    top = stats["top_countries_by_yes"]
    if not isinstance(top, list):
        return False
    if len(top) != 3:
        return False
    for item in top:
        if not isinstance(item, dict):
            return False
        if "country" not in item or "yes" not in item:
            return False
        if not isinstance(item["country"], str):
            return False
        if not isinstance(item["yes"], int):
            return False
    return True


def _compare_totals(actual: Dict[str, Any], expected: Dict[str, Any]) -> bool:
    keys = ["invited", "yes", "no", "maybe", "no_response"]
    for k in keys:
        if actual.get(k) != expected.get(k):
            return False
    return True


def _compare_by_region(actual: Dict[str, Any], expected: Dict[str, Any]) -> bool:
    # Require that the same set of regions appears and each region has correct fields/values
    if set(actual.keys()) != set(expected.keys()):
        return False
    for region, exp in expected.items():
        act = actual.get(region)
        if act is None:
            return False
        # Check counts
        for k in ["invited", "yes", "no", "maybe", "no_response"]:
            if act.get(k) != exp.get(k):
                return False
        # Check response_rate within tolerance
        act_rr = act.get("response_rate")
        exp_rr = exp.get("response_rate")
        if not isinstance(act_rr, (int, float)):
            return False
        if not _float_close(float(act_rr), float(exp_rr), tol=0.005):
            return False
    return True


def _compare_top_countries(actual: List[Dict[str, Any]], expected: List[Dict[str, Any]]) -> bool:
    if len(actual) != len(expected):
        return False
    for a, e in zip(actual, expected):
        if a.get("country") != e.get("country"):
            return False
        if a.get("yes") != e.get("yes"):
            return False
    return True


def _find_section_lines(lines: List[str], title_substring: str) -> Tuple[int, int]:
    """
    Find a section starting at a line containing title_substring.
    Returns (start_index, end_index_exclusive). The section is lines after the title
    until an empty line or next title-like line containing ':' at column after some text.
    """
    start = -1
    for i, line in enumerate(lines):
        if title_substring.lower() in line.strip().lower():
            start = i
            break
    if start == -1:
        return -1, -1
    # Section content starts after the title line
    start_content = start + 1
    end = len(lines)
    for j in range(start_content, len(lines)):
        l = lines[j].strip()
        if l == "":
            end = j
            break
        # If we detect a new section heading like "Action items" or a line ending with ":" treat as boundary
        if l.lower().startswith("action items") or l.endswith(":"):
            end = j
            break
    return start_content, end


def _extract_integers_from_text(text: str) -> List[int]:
    nums: List[int] = []
    current = ""
    for ch in text:
        if ch.isdigit():
            current += ch
        else:
            if current != "":
                try:
                    nums.append(int(current))
                except Exception:
                    pass
                current = ""
    if current != "":
        try:
            nums.append(int(current))
        except Exception:
            pass
    return nums


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "script_runs_successfully": 0.0,
        "output_files_exist": 0.0,
        "stats_json_structure": 0.0,
        "stats_totals_correct": 0.0,
        "stats_by_region_correct": 0.0,
        "stats_top_countries_by_yes_correct": 0.0,
        "notes_title_and_summary": 0.0,
        "notes_top_countries_section_correct": 0.0,
        "notes_action_items_correct": 0.0,
    }

    expected = _compute_expected_stats(workspace)

    # Run the script from repo root
    ran, _err = _run_analyze_script(workspace)
    if ran:
        scores["script_runs_successfully"] = 1.0

    # Check outputs existence
    stats_path = workspace / "output" / "stats.json"
    notes_path = workspace / "output" / "meeting_notes.md"
    if stats_path.exists() and notes_path.exists():
        scores["output_files_exist"] = 1.0

    stats = _safe_load_json(stats_path) if stats_path.exists() else None
    if stats is not None and _check_stats_structure(stats):
        scores["stats_json_structure"] = 1.0

    # Compare stats to expected if we have both
    if stats is not None and expected is not None:
        # Totals
        if isinstance(stats.get("totals"), dict) and _compare_totals(stats["totals"], expected["totals"]):
            scores["stats_totals_correct"] = 1.0
        # By region
        if isinstance(stats.get("by_region"), dict) and _compare_by_region(stats["by_region"], expected["by_region"]):
            scores["stats_by_region_correct"] = 1.0
        # Top countries
        actual_top = stats.get("top_countries_by_yes")
        if isinstance(actual_top, list) and _compare_top_countries(actual_top, expected["top_countries_by_yes"]):
            scores["stats_top_countries_by_yes_correct"] = 1.0

    # Meeting notes validations
    notes_text = _safe_read_text(notes_path) if notes_path.exists() else None
    if notes_text is not None:
        lines = [l.rstrip("\n") for l in notes_text.splitlines()]
        # Title check
        has_title = any(line.strip() == "Board Prep: Global Tasting RSVP Snapshot" for line in lines)
        summary_score = 0.0
        max_summary_checks = 5  # invited + 4 statuses
        passed_checks = 0

        # Find summary line: the first non-empty line after the title
        summary_line = None
        if has_title:
            title_idx = next(i for i, line in enumerate(lines) if line.strip() == "Board Prep: Global Tasting RSVP Snapshot")
            for j in range(title_idx + 1, len(lines)):
                if lines[j].strip():
                    summary_line = lines[j]
                    break
        if summary_line is None and lines:
            # fallback: first non-empty line
            for j in range(0, len(lines)):
                if lines[j].strip():
                    summary_line = lines[j]
                    break

        # Check invited and status counts presence in summary line
        exp_totals = expected["totals"] if expected is not None else None
        if summary_line and exp_totals is not None:
            sl = summary_line.lower()
            nums_in_line = _extract_integers_from_text(summary_line)
            # invited
            if "invited" in sl and exp_totals["invited"] in nums_in_line:
                passed_checks += 1
            # yes
            if "yes" in sl and exp_totals["yes"] in nums_in_line:
                passed_checks += 1
            # no response / no_response
            if ("no response" in sl or "no_response" in sl) and exp_totals["no_response"] in nums_in_line:
                passed_checks += 1
            # maybe
            if "maybe" in sl and exp_totals["maybe"] in nums_in_line:
                passed_checks += 1
            # no (avoid counting 'no response' as 'no' label; ensure ' no ' or at string edges)
            # We'll check token 'no' not followed by ' response'
            if (" no " in f" {sl} " and "no response" not in sl) and exp_totals["no"] in nums_in_line:
                passed_checks += 1

        if has_title and max_summary_checks > 0:
            summary_score = passed_checks / max_summary_checks
        else:
            summary_score = 0.0

        # Cap between 0 and 1
        if summary_score > 1.0:
            summary_score = 1.0
        scores["notes_title_and_summary"] = summary_score

        # Top countries section check
        top_start, top_end = _find_section_lines(lines, "Top 3 countries by confirmed 'Yes'")
        top_ok = False
        if expected is not None and top_start != -1 and top_end != -1:
            section_lines = [l.strip() for l in lines[top_start:top_end] if l.strip()]
            # Collect bullet-like lines
            bullet_lines = [l for l in section_lines if l.lstrip().startswith(("-", "*")) or True]
            needed = list(expected["top_countries_by_yes"])
            matched = 0
            for item in needed:
                country = item["country"]
                yes = item["yes"]
                found = any((country in bl) and (str(yes) in bl) for bl in section_lines)
                if found:
                    matched += 1
            if matched == len(needed) == 3:
                top_ok = True
        scores["notes_top_countries_section_correct"] = 1.0 if top_ok else 0.0

        # Action items per region
        ai_start, ai_end = _find_section_lines(lines, "Action items")
        ai_ok = False
        if expected is not None and ai_start != -1:
            section_lines = [l.strip() for l in lines[ai_start:ai_end if ai_end != -1 else None] if l.strip()]
            # Expected follow-ups per region
            exp_regions = expected["by_region"]
            # For each region, require a bullet line including region name and follow-up count (no_response + maybe)
            per_region_ok = 0
            for region, reg_stats in exp_regions.items():
                follow_up = reg_stats["no_response"] + reg_stats["maybe"]
                # find any line with region and the number
                found = any((region in l) and (str(follow_up) in l) for l in section_lines)
                if found:
                    per_region_ok += 1
            if per_region_ok == len(exp_regions):
                ai_ok = True
        scores["notes_action_items_correct"] = 1.0 if ai_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()