import json
import csv
import re
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
        return rows
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_press_release(md_text: str) -> List[Dict[str, Any]]:
    items = []
    # Pattern: "- Title — dir. Director Name — Runtime min"
    # Robustly match em dash and spacing.
    pattern = re.compile(
        r"^\s*-\s+(?P<title>.*?)\s+—\s+dir\.\s+(?P<director>.*?)\s+—\s+(?P<runtime>\d+)\s*min\b",
        re.IGNORECASE,
    )
    for line in md_text.splitlines():
        m = pattern.match(line)
        if m:
            title = m.group("title").strip()
            director = m.group("director").strip()
            runtime = int(m.group("runtime"))
            items.append({"title": title, "director": director, "runtime": runtime})
    return items


def _parse_schedule(rows: List[Dict[str, str]]) -> Dict[str, Dict[str, Any]]:
    schedule = {}
    for r in rows:
        try:
            title = r["title"].strip()
            schedule[title] = {
                "title": title,
                "director": r.get("director", "").strip(),
                "runtime_min": int(r.get("runtime_min", "").strip()),
                "country": r.get("country", "").strip(),
                "date": r.get("date", "").strip(),
                "time": r.get("time", "").strip(),
                "venue_code": r.get("venue_code", "").strip(),
                "ticket_id": r.get("ticket_id", "").strip(),
            }
        except Exception:
            # Malformed row -> cause downstream checks to fail by skipping entry
            return {}
    return schedule


def _parse_venues(rows: List[Dict[str, str]]) -> Dict[str, str]:
    venues = {}
    for r in rows:
        code = (r.get("venue_code") or "").strip()
        name = (r.get("venue_name") or "").strip()
        if code:
            venues[code] = name
        else:
            return {}
    return venues


def _parse_social_posts(rows: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    posts = []
    for r in rows:
        try:
            posts.append(
                {
                    "post_id": r.get("post_id", "").strip(),
                    "film_title": (r.get("film_title") or "").strip(),
                    "runtime_in_copy": int((r.get("runtime_in_copy") or "").strip()),
                    "venue_name_in_copy": (r.get("venue_name_in_copy") or "").strip(),
                    "copy_text": (r.get("copy_text") or "").strip(),
                }
            )
        except Exception:
            return []
    return posts


def _compute_expected_discrepancies(
    schedule: Dict[str, Dict[str, Any]],
    press_items: List[Dict[str, Any]],
    venues: Dict[str, str],
    social_posts: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    discrepancies: List[Dict[str, str]] = []

    # Press release checks
    press_titles = set()
    for item in press_items:
        pr_title = item["title"]
        press_titles.add(pr_title)
        if pr_title in schedule:
            # Compare director and runtime
            sched = schedule[pr_title]
            if item["director"] != sched["director"]:
                discrepancies.append(
                    {
                        "source": "press_release",
                        "film_title_in_source": pr_title,
                        "issue_type": "director_mismatch",
                        "schedule_title_if_applicable": sched["title"],
                        "expected_value": sched["director"],
                        "found_value": item["director"],
                    }
                )
            if item["runtime"] != sched["runtime_min"]:
                discrepancies.append(
                    {
                        "source": "press_release",
                        "film_title_in_source": pr_title,
                        "issue_type": "runtime_mismatch",
                        "schedule_title_if_applicable": sched["title"],
                        "expected_value": str(sched["runtime_min"]),
                        "found_value": str(item["runtime"]),
                    }
                )
        else:
            # Missing in schedule
            discrepancies.append(
                {
                    "source": "press_release",
                    "film_title_in_source": pr_title,
                    "issue_type": "missing_in_schedule",
                    "schedule_title_if_applicable": "",
                    "expected_value": "",
                    "found_value": pr_title,
                }
            )

    # Omissions: schedule films not in press release highlights (exact title match)
    for title, sched in schedule.items():
        if title not in press_titles:
            discrepancies.append(
                {
                    "source": "press_release",
                    "film_title_in_source": "",
                    "issue_type": "omitted_from_copy",
                    "schedule_title_if_applicable": title,
                    "expected_value": title,
                    "found_value": "",
                }
            )

    # Social posts checks
    for post in social_posts:
        title = post["film_title"]
        if title in schedule:
            sched = schedule[title]
            # runtime comparison
            if int(post["runtime_in_copy"]) != sched["runtime_min"]:
                discrepancies.append(
                    {
                        "source": "social_posts",
                        "film_title_in_source": title,
                        "issue_type": "runtime_mismatch",
                        "schedule_title_if_applicable": sched["title"],
                        "expected_value": str(sched["runtime_min"]),
                        "found_value": str(post["runtime_in_copy"]),
                    }
                )
            # venue comparison: via venue_code -> canonical name
            venue_code = sched["venue_code"]
            canonical_name = venues.get(venue_code, "")
            if canonical_name and post["venue_name_in_copy"] != canonical_name:
                discrepancies.append(
                    {
                        "source": "social_posts",
                        "film_title_in_source": title,
                        "issue_type": "venue_mismatch",
                        "schedule_title_if_applicable": sched["title"],
                        "expected_value": canonical_name,
                        "found_value": post["venue_name_in_copy"],
                    }
                )
        else:
            # If not in schedule, should this be flagged? Task 3 specifies verify film_title exists in the schedule; but the schema doesn't include a "missing_in_schedule" for social_posts; allowed sources are both, and issue_type includes "missing_in_schedule". It could apply here too, but inputs don't require this case.
            # For determinism with given inputs, we skip adding anything.
            pass

    return discrepancies


def _make_tuple_for_compare(d: Dict[str, str]) -> Tuple[str, str, str, str, str, str]:
    return (
        d.get("source", ""),
        d.get("film_title_in_source", ""),
        d.get("issue_type", ""),
        d.get("schedule_title_if_applicable", ""),
        d.get("expected_value", ""),
        d.get("found_value", ""),
    )


def _count_words(text: str) -> int:
    # Count words as sequences of alphanumerics/underscore
    return len(re.findall(r"\b\w+\b", text))


def _line_has_keywords_and_number(line: str, keywords: List[str], number: int) -> bool:
    ln = line.lower()
    if all(k.lower() in ln for k in keywords):
        nums = [int(n) for n in re.findall(r"\b\d+\b", line)]
        return number in nums
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    # Paths
    input_dir = workspace / "input"
    output_dir = workspace / "output"
    discrepancies_path = output_dir / "discrepancies.json"
    verification_report_path = output_dir / "verification_report.md"
    internal_update_path = output_dir / "internal_update.md"
    email_to_programming_path = output_dir / "email_to_programming_team.txt"

    scores: Dict[str, float] = {
        "discrepancies_json_exists": 0.0,
        "discrepancies_json_schema_valid": 0.0,
        "discrepancies_json_matches_expected": 0.0,
        "verification_report_exists": 0.0,
        "verification_report_counts_correct": 0.0,
        "verification_report_discrepancy_listing": 0.0,
        "internal_update_exists": 0.0,
        "internal_update_word_count_and_content": 0.0,
        "email_to_programming_exists": 0.0,
        "email_content_quality": 0.0,
    }

    # Load inputs
    schedule_rows = _read_csv_dicts(input_dir / "schedule.csv")
    venues_rows = _read_csv_dicts(input_dir / "venues.csv")
    press_md = _read_text(input_dir / "press_release.md")
    social_rows = _read_csv_dicts(input_dir / "social_posts.csv")

    # Prepare expected computations only if inputs are all available and parseable
    expected_discrepancies: Optional[List[Dict[str, str]]] = None
    expected_counts: Optional[Dict[str, int]] = None
    expected_total_films: Optional[int] = None
    expected_matched_in_press: Optional[int] = None

    if (
        schedule_rows is not None
        and venues_rows is not None
        and press_md is not None
        and social_rows is not None
    ):
        schedule = _parse_schedule(schedule_rows)
        venues = _parse_venues(venues_rows)
        press_items = _parse_press_release(press_md)
        social_posts = _parse_social_posts(social_rows)

        if schedule and venues is not None and press_items is not None and social_posts is not None:
            expected_discrepancies = _compute_expected_discrepancies(
                schedule, press_items, venues, social_posts
            )
            # Counts
            expected_total_films = len(schedule)
            press_titles_set = {p["title"] for p in press_items}
            expected_matched_in_press = sum(1 for t in schedule if t in press_titles_set)
            # Count issue types across both sources
            counts: Dict[str, int] = {}
            for d in expected_discrepancies:
                it = d["issue_type"]
                counts[it] = counts.get(it, 0) + 1
            expected_counts = counts

    # Existence checks
    if discrepancies_path.exists():
        scores["discrepancies_json_exists"] = 1.0
    if verification_report_path.exists():
        scores["verification_report_exists"] = 1.0
    if internal_update_path.exists():
        scores["internal_update_exists"] = 1.0
    if email_to_programming_path.exists():
        scores["email_to_programming_exists"] = 1.0

    # discrepancies.json schema and content checks
    parsed_json = None
    if discrepancies_path.exists():
        parsed_json = _load_json(discrepancies_path)
        if isinstance(parsed_json, list):
            schema_ok = True
            allowed_sources = {"press_release", "social_posts"}
            allowed_issue_types = {
                "missing_in_schedule",
                "director_mismatch",
                "runtime_mismatch",
                "venue_mismatch",
                "omitted_from_copy",
            }
            for item in parsed_json:
                if not isinstance(item, dict):
                    schema_ok = False
                    break
                required_fields = [
                    "source",
                    "film_title_in_source",
                    "issue_type",
                    "schedule_title_if_applicable",
                    "expected_value",
                    "found_value",
                ]
                if any(k not in item for k in required_fields):
                    schema_ok = False
                    break
                if item["source"] not in allowed_sources:
                    schema_ok = False
                    break
                if item["issue_type"] not in allowed_issue_types:
                    schema_ok = False
                    break
                # All fields should be strings
                if any(not isinstance(item[k], str) for k in required_fields):
                    schema_ok = False
                    break
            scores["discrepancies_json_schema_valid"] = 1.0 if schema_ok else 0.0

            # Match expected exactly (order-insensitive)
            if schema_ok and expected_discrepancies is not None:
                expected_set = set(_make_tuple_for_compare(d) for d in expected_discrepancies)
                actual_set = set(_make_tuple_for_compare(d) for d in parsed_json)
                scores["discrepancies_json_matches_expected"] = 1.0 if expected_set == actual_set else 0.0
            else:
                scores["discrepancies_json_matches_expected"] = 0.0
        else:
            scores["discrepancies_json_schema_valid"] = 0.0
            scores["discrepancies_json_matches_expected"] = 0.0

    # verification_report.md content checks
    report_text = None
    if verification_report_path.exists():
        report_text = _read_text(verification_report_path)
    if report_text is not None and expected_discrepancies is not None:
        # Counts check: total films; matched in press; count of each issue_type
        checks_total = 0
        checks_hit = 0

        # total films in schedule
        checks_total += 1
        if expected_total_films is not None:
            if any(
                _line_has_keywords_and_number(line, ["total", "schedule"], expected_total_films)
                for line in report_text.splitlines()
            ):
                checks_hit += 1

        # films matched in press release
        checks_total += 1
        if expected_matched_in_press is not None:
            if any(
                _line_has_keywords_and_number(line, ["matched", "press"], expected_matched_in_press)
                for line in report_text.splitlines()
            ):
                checks_hit += 1

        # issue type counts
        for issue_type, expected_count in expected_counts.items():
            checks_total += 1
            found = False
            for line in report_text.splitlines():
                if issue_type in line:
                    nums = [int(n) for n in re.findall(r"\b\d+\b", line)]
                    if expected_count in nums:
                        found = True
                        break
            if found:
                checks_hit += 1

        scores["verification_report_counts_correct"] = (checks_hit / checks_total) if checks_total > 0 else 0.0

        # Discrepancy listing check
        # For mismatch types, require title + expected_value + found_value appear somewhere in the report.
        # For missing_in_schedule, require film_title_in_source + ("missing" or "missing_in_schedule")
        # For omitted_from_copy, require schedule_title_if_applicable + ("omitted" or "omitted_from_copy")
        total_disc = len(expected_discrepancies)
        hit_disc = 0
        low_report = report_text.lower()
        for d in expected_discrepancies:
            issue = d["issue_type"]
            title_from_source = d["film_title_in_source"]
            schedule_title = d["schedule_title_if_applicable"]
            expected_value = d["expected_value"]
            found_value = d["found_value"]
            if issue in {"director_mismatch", "runtime_mismatch", "venue_mismatch"}:
                # Title could be from schedule (same as source for mismatches); require all three substrings present
                cond = (
                    (title_from_source in report_text or schedule_title in report_text)
                    and (expected_value == "" or expected_value in report_text)
                    and (found_value == "" or found_value in report_text)
                )
                if cond:
                    hit_disc += 1
            elif issue == "missing_in_schedule":
                # Must include the PR title and "missing" mention
                cond = (title_from_source in report_text) and (
                    "missing_in_schedule" in low_report or "missing" in low_report
                )
                if cond:
                    hit_disc += 1
            elif issue == "omitted_from_copy":
                cond = (schedule_title in report_text) and (
                    "omitted_from_copy" in low_report or "omitted" in low_report
                )
                if cond:
                    hit_disc += 1
        scores["verification_report_discrepancy_listing"] = (hit_disc / total_disc) if total_disc > 0 else 0.0

    # internal_update.md checks
    internal_text = None
    if internal_update_path.exists():
        internal_text = _read_text(internal_update_path)
    if internal_text is not None and expected_discrepancies is not None:
        wc = _count_words(internal_text)
        wc_ok = 150 <= wc <= 200
        contains_press = re.search(r"\bpress\b", internal_text, re.IGNORECASE) is not None
        contains_social = re.search(r"\bsocial\b", internal_text, re.IGNORECASE) is not None
        contains_schedule = re.search(r"\bschedule\b", internal_text, re.IGNORECASE) is not None
        # Presence of issue type names (at least two)
        issue_types = ["missing_in_schedule", "director_mismatch", "runtime_mismatch", "venue_mismatch", "omitted_from_copy"]
        issue_mentions = sum(1 for it in issue_types if re.search(re.escape(it), internal_text, re.IGNORECASE))
        has_numbers = re.search(r"\b\d+\b", internal_text) is not None
        mentions_next_steps = (re.search(r"next\s+steps", internal_text, re.IGNORECASE) is not None) or (
            re.search(r"\bresolve\b", internal_text, re.IGNORECASE) is not None
        )

        # Score as average of sub-checks
        subs = [
            wc_ok,
            contains_press and contains_social and contains_schedule,
            issue_mentions >= 2,
            has_numbers,
            mentions_next_steps,
        ]
        subs_pass = sum(1 for x in subs if x)
        scores["internal_update_word_count_and_content"] = subs_pass / len(subs)

    # email_to_programming_team.txt checks
    email_text = None
    if email_to_programming_path.exists():
        email_text = _read_text(email_to_programming_path)
    if email_text is not None and expected_discrepancies is not None:
        lines = email_text.splitlines()
        bullet_lines = []
        for ln in lines:
            m = re.match(r"^\s*[-*]\s+(.+)$", ln)
            if m:
                bullet_lines.append(m.group(1))
        # Explanation: mentions verification and schedule/press/social
        explains = (
            re.search(r"verification", email_text, re.IGNORECASE) is not None
            and (re.search(r"schedule", email_text, re.IGNORECASE) is not None
                 or re.search(r"press", email_text, re.IGNORECASE) is not None
                 or re.search(r"social", email_text, re.IGNORECASE) is not None)
        )
        # Request confirmation and deadline
        req_confirm = re.search(r"\bconfirm|\bconfirmation", email_text, re.IGNORECASE) is not None
        has_deadline = (
            re.search(r"\bdeadline\b", email_text, re.IGNORECASE) is not None
            or re.search(r"\bby\s+\w+", email_text, re.IGNORECASE) is not None
            or re.search(r"\bEOD\b", email_text, re.IGNORECASE) is not None
        )
        req_and_deadline = req_confirm and has_deadline

        # Bullet coverage: for each expected discrepancy, ensure a bullet contains the title and specific mismatch keyword
        def _issue_keyword(issue_type: str) -> str:
            if issue_type == "director_mismatch":
                return "director"
            if issue_type == "runtime_mismatch":
                return "runtime"
            if issue_type == "venue_mismatch":
                return "venue"
            if issue_type == "missing_in_schedule":
                return "missing"
            if issue_type == "omitted_from_copy":
                return "omitted"
            return ""

        covered = 0
        for d in expected_discrepancies:
            title_search = d["schedule_title_if_applicable"] if d["issue_type"] == "omitted_from_copy" else (d["film_title_in_source"] or d["schedule_title_if_applicable"])
            kw = _issue_keyword(d["issue_type"])
            found = False
            for bl in bullet_lines:
                if (title_search in bl) and (re.search(r"\b" + re.escape(kw) + r"\b", bl, re.IGNORECASE)):
                    found = True
                    break
            if found:
                covered += 1
        bullet_coverage = (covered / len(expected_discrepancies)) if expected_discrepancies else 0.0

        # Combine
        sub_scores = [
            bullet_coverage,
            1.0 if explains else 0.0,
            1.0 if req_and_deadline else 0.0,
        ]
        scores["email_content_quality"] = sum(sub_scores) / len(sub_scores)

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()