import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple


EXPECTED_DEPLOYMENT_PREFIX = (
    "# Railway History Site — Deployment Plan\n\n"
    "This repository builds our class's static website about Oklahoma railway depots.\n\n"
    "## Next Release Candidates\n"
    "The table between the markers below should list the top 5 depot pages to be (re)built in the next content push.\n\n"
)
EXPECTED_BEGIN_MARKER = "<!-- BEGIN NEXT_RELEASE -->"
EXPECTED_END_MARKER = "<!-- END NEXT_RELEASE -->"
EXPECTED_DEPLOYMENT_SUFFIX = (
    "\n\n## Notes\n"
    "- Target URLs should follow the pattern /depots/{slug}/.\n"
    "- Only edit the section between the markers above when updating the next release.\n"
)


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            rows = [dict(row) for row in reader]
            for r in rows:
                for k, v in list(r.items()):
                    if v is None:
                        r[k] = ""
            return rows
    except Exception:
        return None


def _slugify(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s


def _parse_iso_date(date_str: str) -> Optional[datetime]:
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d")
    except Exception:
        return None


def _compute_expected_candidates(workspace: Path) -> Optional[List[Dict[str, object]]]:
    data_path = workspace / "data" / "railway_sites.csv"
    rows = _safe_read_csv_dicts(data_path)
    if rows is None:
        return None

    eligible = []
    cutoff = datetime(2026, 1, 1)
    for r in rows:
        try:
            if r.get("state") != "OK":
                continue
            if r.get("status") != "candidate":
                continue
            score = int(r.get("preservation_score", "").strip())
            if score < 60:
                continue
            d = _parse_iso_date(r.get("last_featured_date", ""))
            if d is None or not (d < cutoff):
                continue
            year = int(str(r.get("year_built", "")).strip())
            name = r.get("name", "").strip()
            county = r.get("county", "").strip()
            slug = _slugify(name)
            eligible.append({
                "name": name,
                "county": county,
                "year_built": year,
                "preservation_score": score,
                "slug": slug,
            })
        except Exception:
            return None

    eligible.sort(key=lambda x: (-x["preservation_score"], x["year_built"], x["name"]))
    top_n = min(5, len(eligible))
    ranked = []
    for i in range(top_n):
        e = dict(eligible[i])
        e["rank"] = i + 1
        ranked.append(e)
    return ranked


def _parse_release_candidates_csv(path: Path) -> Tuple[Optional[List[Dict[str, object]]], Optional[List[str]]]:
    rows = _safe_read_csv_dicts(path)
    if rows is None:
        return None, None
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            header_line = f.readline()
        header_line = header_line.strip()
        headers = [h.strip() for h in header_line.split(",")]
    except Exception:
        return None, None
    parsed_rows = []
    for r in rows:
        try:
            pr = {
                "rank": int(str(r.get("rank", "")).strip()),
                "name": r.get("name", "").strip(),
                "county": r.get("county", "").strip(),
                "year_built": int(str(r.get("year_built", "")).strip()),
                "preservation_score": int(str(r.get("preservation_score", "")).strip()),
                "slug": r.get("slug", "").strip(),
            }
            parsed_rows.append(pr)
        except Exception:
            return None, headers
    return parsed_rows, headers


def _find_markers_section(text: str, begin_marker: str, end_marker: str) -> Optional[Tuple[str, str, str]]:
    begin_idx = text.find(begin_marker)
    end_idx = text.find(end_marker)
    if begin_idx == -1 or end_idx == -1 or end_idx < begin_idx:
        return None
    prefix = text[:begin_idx]
    after_begin = text[begin_idx + len(begin_marker):]
    end_pos = after_begin.find(end_marker)
    if end_pos == -1:
        return None
    section = after_begin[:end_pos]
    suffix_start = end_pos + len(end_marker)
    suffix = after_begin[suffix_start:]
    return prefix, section, suffix


def _parse_markdown_table(section_text: str) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    lines = section_text.strip("\n").splitlines()
    i = 0
    while i < len(lines) and '|' not in lines[i]:
        i += 1
    if i >= len(lines):
        return None
    header_line = lines[i].strip()
    if not header_line:
        return None
    header_cells = [c.strip() for c in header_line.strip('|').split('|')]
    if len(header_cells) == 0:
        return None
    i += 1
    if i < len(lines):
        sep_line = lines[i].strip()
        if sep_line and set(sep_line.strip('|').replace(' ', '')) <= set('-:'):
            i += 1
    rows = []
    while i < len(lines):
        line = lines[i]
        if '|' not in line:
            break
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if len(cells) != len(header_cells):
            return None
        row = {header_cells[j]: cells[j] for j in range(len(header_cells))}
        rows.append(row)
        i += 1
    return header_cells, rows


def _extract_meeting_sections(text: str) -> Tuple[Optional[str], Optional[str], Optional[List[str]]]:
    lines = text.splitlines()
    ranked_start = None
    action_start = None
    for idx, line in enumerate(lines):
        if line.strip() == "## Ranked Candidates":
            ranked_start = idx + 1
        if line.strip() == "## Action Items":
            action_start = idx + 1
            break
    ranked_section = None
    action_section = None
    top_item_lines = None
    if ranked_start is not None:
        end = len(lines)
        for j in range(ranked_start, len(lines)):
            if j != ranked_start and lines[j].startswith("## "):
                end = j
                break
        ranked_section = "\n".join(lines[ranked_start:end]).strip()
    if action_start is not None:
        end = len(lines)
        for j in range(action_start, len(lines)):
            if j != action_start and lines[j].startswith("## "):
                end = j
                break
        action_section = "\n".join(lines[action_start:end]).strip()
        item_lines = []
        for line in action_section.splitlines():
            if re.match(r'^\s*\d+\.\s', line):
                item_lines.append(line.strip())
        top_item_lines = item_lines
    return ranked_section, action_section, top_item_lines


def _validate_action_items(section: Optional[str], expected_names: List[str]) -> bool:
    if section is None:
        return False
    lines = section.splitlines()
    item_indices = []
    for idx, line in enumerate(lines):
        if re.match(r'^\s*\d+\.\s', line):
            item_indices.append(idx)
    if len(item_indices) != len(expected_names):
        return False
    for k, idx in enumerate(item_indices):
        end_idx = len(lines)
        if k + 1 < len(item_indices):
            end_idx = item_indices[k + 1]
        bullets = []
        for j in range(idx + 1, end_idx):
            if re.match(r'^\s*-\s', lines[j]) or re.match(r'^\s*\*\s', lines[j]):
                bullets.append(lines[j].strip())
        # Require exactly the three specified bullets in order
        if len(bullets) != 3:
            return False
        patterns = [
            r"^-\s*Draft a 150(?:–|-|—)200 word historical overview\. \(Owner:\s*____;\s*Due:\s*2026-05-01\)\s*$",
            r"^-\s*Locate and cite at least 2 reliable sources\. \(Owner:\s*____;\s*Due:\s*2026-05-01\)\s*$",
            r"^-\s*Gather 2 archival images or maps with usable licenses\. \(Owner:\s*____;\s*Due:\s*2026-05-01\)\s*$",
        ]
        for p, b in zip(patterns, bullets):
            if not re.match(p, b):
                return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "release_candidates_csv_valid": 0.0,
        "deployment_plan_section_valid": 0.0,
        "deployment_plan_matches_csv": 0.0,
        "meeting_notes_base_structure": 0.0,
        "meeting_notes_ranked_table_valid": 0.0,
        "meeting_notes_actions_valid": 0.0,
        "notes_table_matches_csv": 0.0,
    }

    expected = _compute_expected_candidates(workspace)

    release_path = workspace / "outputs" / "release_candidates.csv"
    parsed_release, release_headers = (None, None)
    if release_path.exists():
        parsed_release, release_headers = _parse_release_candidates_csv(release_path)

    if expected is not None and parsed_release is not None and release_headers is not None:
        expected_headers = ["rank", "name", "county", "year_built", "preservation_score", "slug"]
        header_ok = release_headers == expected_headers
        expected_n = len(expected)
        rows_ok = len(parsed_release) == expected_n
        content_ok = True
        if rows_ok:
            for idx, row in enumerate(parsed_release):
                exp = expected[idx]
                try:
                    if row["rank"] != idx + 1:
                        content_ok = False
                        break
                    if row["name"] != exp["name"]:
                        content_ok = False
                        break
                    if row["county"] != exp["county"]:
                        content_ok = False
                        break
                    if row["year_built"] != exp["year_built"]:
                        content_ok = False
                        break
                    if row["preservation_score"] != exp["preservation_score"]:
                        content_ok = False
                        break
                    if row["slug"] != _slugify(row["name"]):
                        content_ok = False
                        break
                except Exception:
                    content_ok = False
                    break
        else:
            content_ok = False
        if header_ok and content_ok:
            scores["release_candidates_csv_valid"] = 1.0

    deploy_path = workspace / "docs" / "DEPLOYMENT_PLAN.md"
    deploy_text = _safe_read_text(deploy_path) if deploy_path.exists() else None
    deployment_valid = False
    deployment_matches_csv = False
    if deploy_text is not None and expected is not None:
        markers = _find_markers_section(deploy_text, EXPECTED_BEGIN_MARKER, EXPECTED_END_MARKER)
        if markers is not None:
            prefix, section, suffix = markers
            outside_ok = (prefix == EXPECTED_DEPLOYMENT_PREFIX) and (suffix == EXPECTED_DEPLOYMENT_SUFFIX)
            parsed_table = _parse_markdown_table(section)
            table_ok = False
            csv_match = False
            if parsed_table is not None:
                headers, rows = parsed_table
                expected_headers = ["Rank", "Name", "County", "Year", "Score", "Target URL"]
                if headers == expected_headers and len(rows) == len(expected):
                    all_ok = True
                    for idx, row in enumerate(rows):
                        exp = expected[idx]
                        try:
                            rank_str = row.get("Rank", "").strip()
                            if str(idx + 1) != rank_str:
                                all_ok = False
                                break
                            if row.get("Name", "").strip() != exp["name"]:
                                all_ok = False
                                break
                            if row.get("County", "").strip() != exp["county"]:
                                all_ok = False
                                break
                            if row.get("Year", "").strip() != str(exp["year_built"]):
                                all_ok = False
                                break
                            if row.get("Score", "").strip() != str(exp["preservation_score"]):
                                all_ok = False
                                break
                            expected_url = f"/depots/{exp['slug']}/"
                            if row.get("Target URL", "").strip() != expected_url:
                                all_ok = False
                                break
                        except Exception:
                            all_ok = False
                            break
                    table_ok = all_ok
                    if parsed_release is not None and len(parsed_release) == len(rows):
                        csv_ok = True
                        for idx, row in enumerate(rows):
                            rel = parsed_release[idx]
                            expected_url = f"/depots/{rel['slug']}/"
                            if (
                                row.get("Name", "").strip() != rel["name"] or
                                row.get("County", "").strip() != rel["county"] or
                                row.get("Year", "").strip() != str(rel["year_built"]) or
                                row.get("Score", "").strip() != str(rel["preservation_score"]) or
                                row.get("Target URL", "").strip() != expected_url or
                                row.get("Rank", "").strip() != str(rel["rank"])
                            ):
                                csv_ok = False
                                break
                        csv_match = csv_ok
            if outside_ok and table_ok:
                deployment_valid = True
            if csv_match:
                deployment_matches_csv = True
    scores["deployment_plan_section_valid"] = 1.0 if deployment_valid else 0.0
    scores["deployment_plan_matches_csv"] = 1.0 if deployment_matches_csv else 0.0

    notes_path = workspace / "outputs" / "meeting_2026-04-22_notes.md"
    notes_text = _safe_read_text(notes_path) if notes_path.exists() else None
    base_structure_ok = False
    ranked_table_ok = False
    notes_vs_csv_ok = False
    actions_ok = False
    if notes_text is not None and expected is not None:
        has_title = "# History Club Meeting — Depot Release Planning" in notes_text
        has_date = "Date: 2026-04-22" in notes_text
        no_tokens_left = ("{{DATE}}" not in notes_text) and ("{{RANKED_TABLE}}" not in notes_text) and ("{{ACTION_ITEMS}}" not in notes_text)
        base_structure_ok = has_title and has_date and no_tokens_left

        ranked_section, action_section, _ = _extract_meeting_sections(notes_text)
        parsed = None
        if ranked_section:
            parsed = _parse_markdown_table(ranked_section)
        expected_names = [e["name"] for e in expected]
        if parsed is not None:
            headers, rows = parsed
            expected_headers = ["Name", "County", "Year", "Score", "Target URL"]
            if headers == expected_headers and len(rows) == len(expected):
                all_ok = True
                for idx, row in enumerate(rows):
                    exp = expected[idx]
                    try:
                        if row.get("Name", "").strip() != exp["name"]:
                            all_ok = False
                            break
                        if row.get("County", "").strip() != exp["county"]:
                            all_ok = False
                            break
                        if row.get("Year", "").strip() != str(exp["year_built"]):
                            all_ok = False
                            break
                        if row.get("Score", "").strip() != str(exp["preservation_score"]):
                            all_ok = False
                            break
                        expected_url = f"/depots/{exp['slug']}/"
                        if row.get("Target URL", "").strip() != expected_url:
                            all_ok = False
                            break
                    except Exception:
                        all_ok = False
                        break
                ranked_table_ok = all_ok
                if parsed_release is not None and len(parsed_release) == len(rows):
                    csv_ok = True
                    for idx, row in enumerate(rows):
                        rel = parsed_release[idx]
                        expected_url = f"/depots/{rel['slug']}/"
                        if (
                            row.get("Name", "").strip() != rel["name"] or
                            row.get("County", "").strip() != rel["county"] or
                            row.get("Year", "").strip() != str(rel["year_built"]) or
                            row.get("Score", "").strip() != str(rel["preservation_score"]) or
                            row.get("Target URL", "").strip() != expected_url
                        ):
                            csv_ok = False
                            break
                    notes_vs_csv_ok = csv_ok
        actions_ok = _validate_action_items(action_section, expected_names)

    scores["meeting_notes_base_structure"] = 1.0 if base_structure_ok else 0.0
    scores["meeting_notes_ranked_table_valid"] = 1.0 if ranked_table_ok else 0.0
    scores["meeting_notes_actions_valid"] = 1.0 if actions_ok else 0.0
    scores["notes_table_matches_csv"] = 1.0 if notes_vs_csv_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()