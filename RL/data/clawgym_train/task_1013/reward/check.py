import json
import sys
import re
import csv
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional


def _safe_read_text(path: Path) -> Optional[str]:
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


def _safe_parse_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
        # Basic field presence check
        required_fields = {"date", "team", "player_id", "category", "severity", "sanction"}
        if not rows:
            return []
        if not required_fields.issubset(rows[0].keys()):
            return None
        return rows
    except Exception:
        return None


def _compute_summary(rows: List[Dict[str, str]]) -> Optional[dict]:
    if rows is None:
        return None
    try:
        totals = len(rows)
        dates = []
        by_category: Dict[str, int] = {}
        by_severity: Dict[str, int] = {}
        by_team: Dict[str, int] = {}
        sanctions_count: Dict[str, int] = {}
        by_player: Dict[str, int] = {}
        for r in rows:
            d = r.get("date", "")
            try:
                dates.append(datetime.strptime(d, "%Y-%m-%d").date())
            except Exception:
                return None
            cat = r.get("category", "")
            sev = r.get("severity", "")
            team = r.get("team", "")
            sanc = r.get("sanction", "")
            pid = r.get("player_id", "")
            by_category[cat] = by_category.get(cat, 0) + 1
            by_severity[sev] = by_severity.get(sev, 0) + 1
            by_team[team] = by_team.get(team, 0) + 1
            sanctions_count[sanc] = sanctions_count.get(sanc, 0) + 1
            by_player[pid] = by_player.get(pid, 0) + 1
        start = min(dates).strftime("%Y-%m-%d") if dates else None
        end = max(dates).strftime("%Y-%m-%d") if dates else None
        repeat = [{"player_id": pid, "incident_count": cnt} for pid, cnt in by_player.items() if cnt >= 2]
        repeat.sort(key=lambda x: (-x["incident_count"], x["player_id"]))
        return {
            "totals": totals,
            "date_range": {"start": start, "end": end},
            "by_category": by_category,
            "by_severity": by_severity,
            "by_team": by_team,
            "sanctions_count": sanctions_count,
            "repeat_offenders": repeat,
        }
    except Exception:
        return None


def _extract_headings(text: str) -> List[str]:
    headings = []
    for line in text.splitlines():
        if re.match(r'^\s*#{1,6}\s+', line):
            title = re.sub(r'^\s*#{1,6}\s+', '', line).strip()
            if title:
                headings.append(title)
    return headings


def _parse_sections(text: str) -> Dict[str, Tuple[str, str]]:
    # returns mapping lowercased heading -> (original_heading, content)
    sections: Dict[str, Tuple[str, str]] = {}
    current_title = None
    current_content_lines: List[str] = []
    for line in text.splitlines():
        if re.match(r'^\s*#{1,6}\s+', line):
            # store previous
            if current_title is not None:
                sections[current_title.lower()] = (current_title, "\n".join(current_content_lines).strip())
            # new section
            title = re.sub(r'^\s*#{1,6}\s+', '', line).strip()
            current_title = title
            current_content_lines = []
        else:
            if current_title is not None:
                current_content_lines.append(line)
    if current_title is not None:
        sections[current_title.lower()] = (current_title, "\n".join(current_content_lines).strip())
    return sections


def _find_section_content(sections: Dict[str, Tuple[str, str]], name: str) -> Optional[str]:
    key = name.lower().strip()
    for k, (_, content) in sections.items():
        if k == key:
            return content
    return None


def _find_heading_presence(headings: List[str], required: List[str]) -> bool:
    lower_heads = [h.strip().lower() for h in headings]
    for req in required:
        if req.strip().lower() not in lower_heads:
            return False
    return True


def _parse_total_incidents(text: str) -> Optional[int]:
    m = re.search(r'total incidents[^0-9]*([0-9]+)', text, flags=re.IGNORECASE)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _parse_repeat_offenders_count(text: str) -> Optional[int]:
    m = re.search(r'repeat offender[s]?\D+([0-9]+)', text, flags=re.IGNORECASE)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _parse_by_category_counts(text: str, categories: List[str]) -> Dict[str, Optional[int]]:
    # For each expected category, find "<Category>:\s*(\d+)" somewhere in the text
    found: Dict[str, Optional[int]] = {c: None for c in categories}
    lines = text.splitlines()
    for c in categories:
        pattern = re.compile(rf'{re.escape(c)}\s*:\s*([0-9]+)')
        for line in lines:
            m = pattern.search(line)
            if m:
                try:
                    found[c] = int(m.group(1))
                    break
                except Exception:
                    found[c] = None
    return found


def _parse_top_categories(text: str, categories: List[str]) -> Optional[List[str]]:
    # Find a line mentioning "top category" or "top categories" and extract category names present in that line.
    lines = text.splitlines()
    for line in lines:
        if re.search(r'top categor(y|ies)', line, flags=re.IGNORECASE):
            present = []
            for c in categories:
                if re.search(rf'\b{re.escape(c)}\b', line):
                    present.append(c)
            # If we found any categories in this line, return unique ordered by first appearance
            if present:
                # Deduplicate preserving order
                seen = set()
                ordered = []
                for item in present:
                    if item not in seen:
                        seen.add(item)
                        ordered.append(item)
                return ordered
            # If line exists but has no recognizable categories, return empty to fail
            return []
    return None


def _validate_summary_schema(data: dict) -> bool:
    # exact keys
    expected_keys = {
        "totals",
        "date_range",
        "by_category",
        "by_severity",
        "by_team",
        "sanctions_count",
        "repeat_offenders",
    }
    if not isinstance(data, dict):
        return False
    if set(data.keys()) != expected_keys:
        return False
    if not isinstance(data.get("totals"), int):
        return False
    dr = data.get("date_range")
    if not isinstance(dr, dict) or set(dr.keys()) != {"start", "end"}:
        return False
    if not (isinstance(dr.get("start"), str) and isinstance(dr.get("end"), str)):
        return False
    for key in ["by_category", "by_severity", "by_team", "sanctions_count"]:
        if not isinstance(data.get(key), dict):
            return False
        # all values must be int
        for v in data[key].values():
            if not isinstance(v, int):
                return False
    ro = data.get("repeat_offenders")
    if not isinstance(ro, list):
        return False
    for item in ro:
        if not isinstance(item, dict):
            return False
        if set(item.keys()) != {"player_id", "incident_count"}:
            return False
        if not isinstance(item.get("player_id"), str):
            return False
        if not isinstance(item.get("incident_count"), int):
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "incidents_summary_json_valid": 0.0,
        "incidents_summary_totals_correct": 0.0,
        "incidents_summary_date_range_correct": 0.0,
        "incidents_summary_by_category_correct": 0.0,
        "incidents_summary_by_severity_correct": 0.0,
        "incidents_summary_by_team_correct": 0.0,
        "incidents_summary_sanctions_count_correct": 0.0,
        "incidents_summary_repeat_offenders_correct": 0.0,
        "sportsmanship_review_sections_present": 0.0,
        "sportsmanship_review_data_checks_total_matches": 0.0,
        "sportsmanship_review_data_checks_by_category_matches": 0.0,
        "sportsmanship_review_data_checks_top_categories_matches": 0.0,
        "sportsmanship_review_data_checks_repeat_offenders_matches": 0.0,
        "policy_revised_sections_preserved": 0.0,
        "policy_revised_new_sections_present": 0.0,
        "policy_revised_sanction_levels_thresholds": 0.0,
        "policy_revised_sanction_levels_severity_alignment": 0.0,
        "policy_revised_restorative_actions_steps": 0.0,
        "policy_revised_data_snapshot_matches": 0.0,
        "policy_revised_revision_note_data_citation": 0.0,
    }

    # Load and compute expected summary from input/incidents.csv
    incidents_csv_path = workspace / "input" / "incidents.csv"
    rows = _safe_parse_csv(incidents_csv_path)
    expected_summary = _compute_summary(rows) if rows is not None else None

    # Load output incidents_summary.json
    summary_json_path = workspace / "output" / "incidents_summary.json"
    summary_json = _safe_load_json(summary_json_path)

    # Validate summary schema
    if summary_json is not None and _validate_summary_schema(summary_json):
        scores["incidents_summary_json_valid"] = 1.0

    # Compare summary content with expected values
    if expected_summary is not None and summary_json is not None and _validate_summary_schema(summary_json):
        # totals
        if summary_json.get("totals") == expected_summary.get("totals"):
            scores["incidents_summary_totals_correct"] = 1.0
        # date range
        if summary_json.get("date_range") == expected_summary.get("date_range"):
            scores["incidents_summary_date_range_correct"] = 1.0
        # by_category
        if summary_json.get("by_category") == expected_summary.get("by_category"):
            scores["incidents_summary_by_category_correct"] = 1.0
        # by_severity
        if summary_json.get("by_severity") == expected_summary.get("by_severity"):
            scores["incidents_summary_by_severity_correct"] = 1.0
        # by_team
        if summary_json.get("by_team") == expected_summary.get("by_team"):
            scores["incidents_summary_by_team_correct"] = 1.0
        # sanctions_count
        if summary_json.get("sanctions_count") == expected_summary.get("sanctions_count"):
            scores["incidents_summary_sanctions_count_correct"] = 1.0
        # repeat_offenders exact order
        if summary_json.get("repeat_offenders") == expected_summary.get("repeat_offenders"):
            scores["incidents_summary_repeat_offenders_correct"] = 1.0

    # Sportsmanship review checks
    review_path = workspace / "output" / "sportsmanship_review.md"
    review_text = _safe_read_text(review_path)
    if review_text is not None:
        review_headings = _extract_headings(review_text)
        required_review_sections = ["Overview", "Key Findings", "Ethical Assessment", "Recommendations", "Data Checks"]
        if _find_heading_presence(review_headings, required_review_sections):
            scores["sportsmanship_review_sections_present"] = 1.0

        review_sections = _parse_sections(review_text)
        data_checks_text = _find_section_content(review_sections, "Data Checks")
        # For checks to be meaningful and grounded, use the summary_json values
        if data_checks_text is not None and summary_json is not None and _validate_summary_schema(summary_json):
            # total incidents
            total_in_review = _parse_total_incidents(data_checks_text)
            if isinstance(total_in_review, int) and total_in_review == summary_json["totals"]:
                scores["sportsmanship_review_data_checks_total_matches"] = 1.0
            # by_category matches
            categories = list(summary_json["by_category"].keys())
            parsed_counts = _parse_by_category_counts(data_checks_text, categories)
            if all(parsed_counts.get(c) == summary_json["by_category"][c] for c in categories):
                scores["sportsmanship_review_data_checks_by_category_matches"] = 1.0
            # top categories
            # compute expected top set
            max_count = None
            expected_top_set = set()
            for c, cnt in summary_json["by_category"].items():
                if max_count is None or cnt > max_count:
                    max_count = cnt
                    expected_top_set = {c}
                elif cnt == max_count:
                    expected_top_set.add(c)
            top_list = _parse_top_categories(data_checks_text, categories)
            if top_list is not None:
                if set(top_list) == expected_top_set:
                    scores["sportsmanship_review_data_checks_top_categories_matches"] = 1.0
            # repeat offenders count
            expected_repeat_count = len(summary_json["repeat_offenders"])
            ro_count = _parse_repeat_offenders_count(data_checks_text)
            if isinstance(ro_count, int) and ro_count == expected_repeat_count:
                scores["sportsmanship_review_data_checks_repeat_offenders_matches"] = 1.0

    # Policy revised checks
    draft_policy_path = workspace / "input" / "policy_draft.md"
    draft_text = _safe_read_text(draft_policy_path)
    revised_policy_path = workspace / "output" / "policy_revised.md"
    revised_text = _safe_read_text(revised_policy_path)

    if draft_text is not None and revised_text is not None:
        draft_headings = _extract_headings(draft_text)
        # Preserve original section headings: consider only level-2+ headings from draft (skip top title)
        original_sections = []
        for line in draft_text.splitlines():
            if re.match(r'^\s*##\s+', line):
                title = re.sub(r'^\s*##\s+', '', line).strip()
                if title:
                    original_sections.append(title)
        revised_headings = _extract_headings(revised_text)
        if original_sections and _find_heading_presence(revised_headings, original_sections):
            scores["policy_revised_sections_preserved"] = 1.0

        # New sections present
        required_new_sections = [
            "Definitions",
            "Sanction Levels and Escalation",
            "Restorative Actions",
            "Transparency and Accountability",
            "Data Snapshot",
            "Revision Note",
        ]
        if _find_heading_presence(revised_headings, required_new_sections):
            scores["policy_revised_new_sections_present"] = 1.0

        # Parse sections of revised
        revised_sections = _parse_sections(revised_text)

        # Sanction Levels thresholds and severity alignment
        sanctions_section = _find_section_content(revised_sections, "Sanction Levels and Escalation")
        if sanctions_section is not None:
            text = sanctions_section
            # thresholds for 2+ and 3+ incidents (allow textual forms)
            def has_threshold(n: int) -> bool:
                patterns = []
                if n == 2:
                    patterns = [r'\b2\+\b', r'\b2nd\b', r'\bsecond\b', r'\btwo\b', r'\b2 or more\b', r'\b2 or more incidents\b']
                elif n == 3:
                    patterns = [r'\b3\+\b', r'\b3rd\b', r'\bthird\b', r'\bthree\b', r'\b3 or more\b', r'\b3 or more incidents\b']
                for p in patterns:
                    if re.search(p, text, flags=re.IGNORECASE):
                        return True
                return False

            thresholds_ok = has_threshold(2) and has_threshold(3)
            if thresholds_ok:
                scores["policy_revised_sanction_levels_thresholds"] = 1.0

            # severity alignment: mentions of severity and at least two severity levels and at least one sanction term
            severity_terms = ["Minor", "Moderate", "Major"]
            sanction_terms = ["Warning", "Penalty", "Ejection", "Suspension", "Probation", "Disqualification"]
            has_severity_word = bool(re.search(r'\bseverity\b', text, flags=re.IGNORECASE))
            present_severities = [s for s in severity_terms if re.search(rf'\b{s}\b', text, flags=re.IGNORECASE)]
            present_sanctions = [s for s in sanction_terms if re.search(rf'\b{s}\b', text, flags=re.IGNORECASE)]
            if has_severity_word and len(present_severities) >= 2 and len(present_sanctions) >= 1:
                scores["policy_revised_sanction_levels_severity_alignment"] = 1.0

        # Restorative Actions steps
        restorative_section = _find_section_content(revised_sections, "Restorative Actions")
        if restorative_section is not None:
            text = restorative_section
            # Look for bullet/numbered steps
            lines = [ln.strip() for ln in text.splitlines()]
            bullet_like = [ln for ln in lines if re.match(r'^(-|\*|\d+\.)\s+', ln)]
            restorative_keywords = ["apology", "mediate", "mediation", "training", "education", "counseling",
                                    "service", "community service", "reflection", "mentorship", "coaching", "repair"]
            keyword_hits = set()
            for kw in restorative_keywords:
                if re.search(rf'\b{re.escape(kw)}\b', text, flags=re.IGNORECASE):
                    keyword_hits.add(kw)
            if len(bullet_like) >= 2 and len(keyword_hits) >= 2:
                scores["policy_revised_restorative_actions_steps"] = 1.0

        # Data Snapshot matches summary.json (must be taken directly from it)
        data_snapshot_section = _find_section_content(revised_sections, "Data Snapshot")
        if data_snapshot_section is not None and summary_json is not None and _validate_summary_schema(summary_json):
            total_val = _parse_total_incidents(data_snapshot_section)
            categories = list(summary_json["by_category"].keys())
            counts = _parse_by_category_counts(data_snapshot_section, categories)
            match_total = isinstance(total_val, int) and total_val == summary_json["totals"]
            match_cats = all(counts.get(c) == summary_json["by_category"][c] for c in categories)
            if match_total and match_cats:
                scores["policy_revised_data_snapshot_matches"] = 1.0

        # Revision Note cites data points (top categories or repeat offenders)
        revision_note_section = _find_section_content(revised_sections, "Revision Note")
        if revision_note_section is not None:
            text = revision_note_section
            mentions_change = bool(re.search(r'\b(change|update|revise|revision|revised)\b', text, flags=re.IGNORECASE))
            cites_data = False
            if summary_json is not None and _validate_summary_schema(summary_json):
                # top categories
                by_cat = summary_json["by_category"]
                max_cnt = max(by_cat.values()) if by_cat else 0
                top_cats = [k for k, v in by_cat.items() if v == max_cnt]
                # if mentions any of the top categories or "repeat"
                if any(re.search(rf'\b{re.escape(cat)}\b', text) for cat in top_cats):
                    cites_data = True
                repeat_count = len(summary_json["repeat_offenders"])
                if re.search(r'\brepeat\b', text, flags=re.IGNORECASE):
                    cites_data = True
                if re.search(rf'\b{repeat_count}\b', text):
                    cites_data = True
            if mentions_change and cites_data:
                scores["policy_revised_revision_note_data_citation"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()