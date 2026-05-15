import json
import sys
import csv
import re
from pathlib import Path
from html.parser import HTMLParser


class FeedbackHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_tbody = False
        self.in_tr = False
        self.in_td = False
        self.current_cell = []
        self.current_row = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "tbody":
            self.in_tbody = True
        elif tag == "tr" and self.in_tbody:
            self.in_tr = True
            self.current_row = []
        elif tag == "td" and self.in_tr:
            self.in_td = True
            self.current_cell = []

    def handle_data(self, data):
        if self.in_td:
            self.current_cell.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "td" and self.in_td:
            cell_text = "".join(self.current_cell).strip()
            self.current_row.append(cell_text)
            self.in_td = False
            self.current_cell = []
        elif tag == "tr" and self.in_tr:
            if len(self.current_row) >= 4:
                self.rows.append(self.current_row[:4])
            self.in_tr = False
            self.current_row = []
        elif tag == "tbody":
            self.in_tbody = False


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def safe_load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def safe_load_jsonl(path: Path):
    items = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
        return items
    except Exception:
        return None


def safe_load_csv(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows
    except Exception:
        return None


def parse_html_feedback(path: Path):
    try:
        parser = FeedbackHTMLParser()
        parser.feed(safe_read_text(path))
        rows = []
        for row in parser.rows:
            if len(row) >= 4:
                screen, issue, severity, comment = row[:4]
                rows.append(
                    {
                        "screen": screen.strip(),
                        "issue": issue.strip(),
                        "severity": severity.strip(),
                        "comment": comment.strip(),
                    }
                )
        return rows
    except Exception:
        return None


def recompute_expected_issues(workspace: Path):
    csv_path = workspace / "input" / "ux_feedback.csv"
    html_path = workspace / "input" / "feedback_sessions.html"

    csv_rows = safe_load_csv(csv_path)
    html_rows = parse_html_feedback(html_path)
    if csv_rows is None or html_rows is None:
        return None

    issues = {}

    def get_or_create(issue_text, original_issue):
        key = issue_text.lower()
        if key not in issues:
            issues[key] = {
                "issue": original_issue,
                "csv_count": 0,
                "html_count": 0,
                "severities": [],
                "screens": set(),
                "platforms": set(),
                "csv_comments": [],
                "html_comments": [],
            }
        return issues[key]

    for r in csv_rows:
        issue = (r.get("issue") or "").strip()
        screen = (r.get("screen") or "").strip()
        platform = (r.get("platform") or "").strip()
        notes = (r.get("notes") or "").strip()
        sev_raw = (r.get("severity") or "").strip()
        try:
            sev = float(sev_raw)
        except Exception:
            continue
        if not issue:
            continue
        ent = get_or_create(issue, issue)
        ent["csv_count"] += 1
        ent["severities"].append(sev)
        if screen:
            ent["screens"].add(screen)
        if platform:
            ent["platforms"].add(platform)
        if notes:
            ent["csv_comments"].append(notes)

    for r in html_rows:
        issue = (r.get("issue") or "").strip()
        screen = (r.get("screen") or "").strip()
        comment = (r.get("comment") or "").strip()
        sev_raw = (r.get("severity") or "").strip()
        try:
            sev = float(sev_raw)
        except Exception:
            continue
        if not issue:
            continue
        ent = get_or_create(issue, issues.get(issue.lower(), {"issue": issue})["issue"])
        ent["html_count"] += 1
        ent["severities"].append(sev)
        if screen:
            ent["screens"].add(screen)
        if comment:
            ent["html_comments"].append(comment)

    expected_list = []
    for _, ent in issues.items():
        reports_count = ent["csv_count"] + ent["html_count"]
        if reports_count == 0 or len(ent["severities"]) == 0:
            continue
        avg = sum(ent["severities"]) / len(ent["severities"])
        severity_avg = round(avg + 1e-8, 1)
        expected_list.append(
            {
                "issue": ent["issue"],
                "reports_count": reports_count,
                "severity_avg": severity_avg,
                "screens": sorted(ent["screens"]),
                "platforms": sorted(ent["platforms"]) if ent["platforms"] else None,
                "source_counts": {"csv": ent["csv_count"], "html": ent["html_count"]},
                "example_comments_set": set(ent["csv_comments"] + ent["html_comments"]),
            }
        )
    expected_list.sort(key=lambda x: (-x["severity_avg"], -x["reports_count"], x["issue"].lower()))
    for idx, ent in enumerate(expected_list, start=1):
        ent["priority_rank"] = idx
    return expected_list


def extract_section(text: str, header: str, next_headers: list):
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip().lower().startswith(header.lower()):
            start = i + 1
            break
    if start is None:
        return None
    end = len(lines)
    lower_next = [h.lower() for h in next_headers]
    for j in range(start, len(lines)):
        l = lines[j].strip().lower()
        for h in lower_next:
            if l.startswith(h):
                end = j
                return "\n".join(lines[start:end]).strip()
    return "\n".join(lines[start:end]).strip()


def count_bullets(text: str) -> int:
    count = 0
    for line in text.splitlines():
        s = line.strip()
        if re.match(r"^(-|\*|\d+\.)\s+", s):
            count += 1
    return count


def words_count(text: str) -> int:
    tokens = re.findall(r"\b\w+\b", text)
    return len(tokens)


def find_top3_mentions(text: str, issues: list, screens_map: dict) -> bool:
    text_lower = text.lower()
    for ent in issues[:3]:
        issue = ent["issue"]
        if issue.lower() not in text_lower:
            return False
        screens = screens_map.get(issue.lower(), [])
        screen_mentioned = any(s.lower() in text_lower for s in screens)
        if not screen_mentioned:
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "prioritized_json_exists_and_parseable": 0.0,
        "issues_set_matches_expected": 0.0,
        "counts_and_source_counts_correct": 0.0,
        "severity_averages_correct": 0.0,
        "screens_sets_correct": 0.0,
        "platforms_sets_correct": 0.0,
        "ranking_and_sorting_correct": 0.0,
        "example_comments_sources_valid": 0.0,
        "weekly_status_exists_and_sections": 0.0,
        "weekly_status_summary_numbers_correct": 0.0,
        "weekly_status_top3_mentions": 0.0,
        "weekly_status_progress_mentions": 0.0,
        "weekly_status_next_actions_count": 0.0,
        "revised_messages_exists": 0.0,
        "slack_update_word_limit_and_content": 0.0,
        "beta_email_word_limit_and_structure": 0.0,
        "messages_alignment_with_priorities": 0.0,
    }

    expected = recompute_expected_issues(workspace)
    if expected is None:
        return scores

    expected_issue_set = {e["issue"].lower() for e in expected}
    expected_by_issue = {e["issue"].lower(): e for e in expected}
    expected_total_feedback = 0
    csv_rows = safe_load_csv(workspace / "input" / "ux_feedback.csv")
    html_rows = parse_html_feedback(workspace / "input" / "feedback_sessions.html")
    if csv_rows is not None and html_rows is not None:
        expected_total_feedback = len(csv_rows) + len(html_rows)

    out_json_path = workspace / "outputs" / "prioritized_ux_issues.json"
    out_json = safe_load_json(out_json_path)
    if isinstance(out_json, list):
        valid_items = True
        for item in out_json:
            if not isinstance(item, dict):
                valid_items = False
                break
            required_fields = ["issue", "priority_rank", "reports_count", "severity_avg", "screens", "source_counts", "example_comments"]
            for f in required_fields:
                if f not in item:
                    valid_items = False
                    break
            if not valid_items:
                break
            if not isinstance(item["issue"], str):
                valid_items = False
                break
            if not isinstance(item["priority_rank"], int):
                valid_items = False
                break
            if not isinstance(item["reports_count"], int):
                valid_items = False
                break
            if not (isinstance(item["severity_avg"], int) or isinstance(item["severity_avg"], float)):
                valid_items = False
                break
            if not isinstance(item["screens"], list):
                valid_items = False
                break
            if not isinstance(item["source_counts"], dict):
                valid_items = False
                break
            if not isinstance(item["example_comments"], list):
                valid_items = False
                break
        if valid_items:
            scores["prioritized_json_exists_and_parseable"] = 1.0

        try:
            out_issue_set = {str(item["issue"]).lower() for item in out_json if isinstance(item, dict) and "issue" in item}
            if out_issue_set == expected_issue_set and len(out_issue_set) == len(expected_issue_set):
                scores["issues_set_matches_expected"] = 1.0
        except Exception:
            pass

        counts_ok = True
        for item in out_json if isinstance(out_json, list) else []:
            if not isinstance(item, dict) or "issue" not in item:
                counts_ok = False
                break
            key = str(item["issue"]).lower()
            exp = expected_by_issue.get(key)
            sc = item.get("source_counts", {})
            if not isinstance(sc, dict) or "csv" not in sc or "html" not in sc:
                counts_ok = False
                break
            if not isinstance(sc.get("csv"), int) or not isinstance(sc.get("html"), int):
                counts_ok = False
                break
            rc = item.get("reports_count")
            if not isinstance(rc, int):
                counts_ok = False
                break
            if rc != sc.get("csv") + sc.get("html"):
                counts_ok = False
                break
            if exp is None:
                counts_ok = False
                break
            if rc != exp["reports_count"]:
                counts_ok = False
                break
            if sc.get("csv") != exp["source_counts"]["csv"] or sc.get("html") != exp["source_counts"]["html"]:
                counts_ok = False
                break
        if counts_ok and scores["prioritized_json_exists_and_parseable"] == 1.0:
            scores["counts_and_source_counts_correct"] = 1.0

        sev_ok = True
        for item in out_json if isinstance(out_json, list) else []:
            key = str(item.get("issue", "")).lower()
            exp = expected_by_issue.get(key)
            if exp is None:
                sev_ok = False
                break
            item_sev = item.get("severity_avg")
            try:
                if round(float(item_sev), 1) != exp["severity_avg"]:
                    sev_ok = False
                    break
            except Exception:
                sev_ok = False
                break
        if sev_ok and scores["prioritized_json_exists_and_parseable"] == 1.0:
            scores["severity_averages_correct"] = 1.0

        screens_ok = True
        for item in out_json if isinstance(out_json, list) else []:
            key = str(item.get("issue", "")).lower()
            exp = expected_by_issue.get(key)
            if exp is None:
                screens_ok = False
                break
            item_screens = item.get("screens")
            if not isinstance(item_screens, list):
                screens_ok = False
                break
            if set([str(s).strip() for s in item_screens]) != set(exp["screens"]):
                screens_ok = False
                break
        if screens_ok and scores["prioritized_json_exists_and_parseable"] == 1.0:
            scores["screens_sets_correct"] = 1.0

        platforms_ok = True
        for item in out_json if isinstance(out_json, list) else []:
            key = str(item.get("issue", "")).lower()
            exp = expected_by_issue.get(key)
            if exp is None:
                platforms_ok = False
                break
            item_platforms_present = "platforms" in item
            if exp["source_counts"]["csv"] == 0:
                if item_platforms_present and item.get("platforms") not in ([], None):
                    platforms_ok = False
                    break
            else:
                if not item_platforms_present or not isinstance(item.get("platforms"), list):
                    platforms_ok = False
                    break
                if set([str(p).strip() for p in item.get("platforms")]) != set(exp["platforms"]):
                    platforms_ok = False
                    break
        if platforms_ok and scores["prioritized_json_exists_and_parseable"] == 1.0:
            scores["platforms_sets_correct"] = 1.0

        # Ranking: ensure order exactly matches expected sorted order and priority_rank sequence
        ranking_ok = True
        expected_order = [e["issue"].lower() for e in expected]
        if len(out_json) != len(expected_order):
            ranking_ok = False
        else:
            for idx, item in enumerate(out_json, start=1):
                if not isinstance(item, dict):
                    ranking_ok = False
                    break
                if item.get("priority_rank") != idx:
                    ranking_ok = False
                    break
                if str(item.get("issue", "")).lower() != expected_order[idx - 1]:
                    ranking_ok = False
                    break
        if ranking_ok and scores["prioritized_json_exists_and_parseable"] == 1.0:
            scores["ranking_and_sorting_correct"] = 1.0

        comments_ok = True
        for item in out_json:
            key = str(item.get("issue", "")).lower()
            exp = expected_by_issue.get(key)
            if exp is None:
                comments_ok = False
                break
            example_comments = item.get("example_comments")
            if not isinstance(example_comments, list):
                comments_ok = False
                break
            if len(example_comments) > 2:
                comments_ok = False
                break
            known_comments = exp["example_comments_set"]
            for c in example_comments:
                if not isinstance(c, str) or c.strip() not in known_comments:
                    comments_ok = False
                    break
            if not comments_ok:
                break
        if comments_ok:
            csv_rows_local = csv_rows if csv_rows is not None else []
            html_rows_local = html_rows if html_rows is not None else []
            issue_to_csv_comments = {}
            issue_to_html_comments = {}
            for r in csv_rows_local:
                issue = (r.get("issue") or "").strip()
                notes = (r.get("notes") or "").strip()
                if issue and notes:
                    issue_to_csv_comments.setdefault(issue.lower(), set()).add(notes)
            for r in html_rows_local:
                issue = (r.get("issue") or "").strip()
                comment = (r.get("comment") or "").strip()
                if issue and comment:
                    issue_to_html_comments.setdefault(issue.lower(), set()).add(comment)
            for item in out_json:
                key = str(item.get("issue", "")).lower()
                ex_comments = item.get("example_comments", [])
                csv_set = issue_to_csv_comments.get(key, set())
                html_set = issue_to_html_comments.get(key, set())
                if len(csv_set) > 0 and len(html_set) > 0:
                    has_csv = any((c in csv_set) for c in ex_comments)
                    has_html = any((c in html_set) for c in ex_comments)
                    if not (has_csv and has_html):
                        comments_ok = False
                        break
        if comments_ok and scores["prioritized_json_exists_and_parseable"] == 1.0:
            scores["example_comments_sources_valid"] = 1.0

    status_path = workspace / "outputs" / "ux_weekly_status.md"
    status_text = safe_read_text(status_path)
    if status_text:
        has_summary = any(l.strip().lower().startswith("summary:") for l in status_text.splitlines())
        has_top3 = any(l.strip().lower().startswith("top 3 ux priorities:") for l in status_text.splitlines())
        has_progress = any(l.strip().lower().startswith("progress this week:") for l in status_text.splitlines())
        has_next = any(l.strip().lower().startswith("next actions:") for l in status_text.splitlines())
        if has_summary and has_top3 and has_progress and has_next:
            scores["weekly_status_exists_and_sections"] = 1.0

        summary_section = extract_section(
            status_text,
            "Summary:",
            ["Top 3 UX priorities:", "Progress this week:", "Next actions:"],
        )
        if summary_section:
            processed_match = re.search(r"Total feedback items processed:\s*(\d+)", summary_section, flags=re.IGNORECASE)
            distinct_match = re.search(r"Distinct issues identified:\s*(\d+)", summary_section, flags=re.IGNORECASE)
            if processed_match and distinct_match:
                try:
                    processed_num = int(processed_match.group(1))
                    distinct_num = int(distinct_match.group(1))
                    expected = recompute_expected_issues(workspace)
                    if expected is not None:
                        csv_rows2 = safe_load_csv(workspace / "input" / "ux_feedback.csv")
                        html_rows2 = parse_html_feedback(workspace / "input" / "feedback_sessions.html")
                        if csv_rows2 is not None and html_rows2 is not None:
                            total_feedback = len(csv_rows2) + len(html_rows2)
                            if processed_num == total_feedback and distinct_num == len(expected):
                                scores["weekly_status_summary_numbers_correct"] = 1.0
                except Exception:
                    pass

        top3_section = extract_section(
            status_text,
            "Top 3 UX priorities:",
            ["Summary:", "Progress this week:", "Next actions:"],
        )
        if top3_section:
            screens_map = {e["issue"].lower(): e["screens"] for e in expected}
            if find_top3_mentions(top3_section, expected, screens_map):
                scores["weekly_status_top3_mentions"] = 1.0

        progress_section = extract_section(
            status_text,
            "Progress this week:",
            ["Summary:", "Top 3 UX priorities:", "Next actions:"],
        )
        if progress_section:
            plower = progress_section.lower()
            cond1 = ("sign-in" in plower and "confusing sign-in error message" in plower)
            cond2 = ("checkout" in plower and "checkout button is hard to tap" in plower)
            if cond1 and cond2:
                scores["weekly_status_progress_mentions"] = 1.0

        next_section = extract_section(
            status_text,
            "Next actions:",
            ["Summary:", "Top 3 UX priorities:", "Progress this week:"],
        )
        if next_section:
            bullets = count_bullets(next_section)
            if 3 <= bullets <= 5:
                scores["weekly_status_next_actions_count"] = 1.0

    rev_path = workspace / "outputs" / "revised_messages.md"
    rev_text = safe_read_text(rev_path)
    if rev_text:
        scores["revised_messages_exists"] = 1.0
        lines = rev_text.splitlines()
        subj_idx = None
        for i, l in enumerate(lines):
            if l.strip().lower().startswith("subject:"):
                subj_idx = i
                break
        slack_text = ""
        email_subject_line = ""
        email_body_text = ""
        if subj_idx is not None:
            slack_text = "\n".join(lines[:subj_idx]).strip()
            email_subject_line = lines[subj_idx].strip()
            email_body_text = "\n".join(lines[subj_idx + 1 :]).strip()
        else:
            slack_text = rev_text.strip()

        if slack_text:
            wc = words_count(slack_text)
            lower = slack_text.lower()
            has_appreciation = ("thank" in lower) or ("appreciat" in lower)
            has_progress_word = ("fixed" in lower) or ("in progress" in lower) or ("in-progress" in lower) or ("progress" in lower)
            mentions_screen = any(s in lower for s in ["checkout", "sign-in", "profile"])
            if wc <= 120 and has_appreciation and has_progress_word and mentions_screen:
                scores["slack_update_word_limit_and_content"] = 1.0

        if email_subject_line:
            body_wc = words_count(email_body_text)
            lower_body = (email_subject_line + "\n" + email_body_text).lower()
            has_subject = email_subject_line.lower().startswith("subject:")
            has_thanks = ("thank" in lower_body)
            has_feedback = ("feedback" in lower_body)
            has_fixed = ("fixed" in lower_body)
            has_next = ("next" in lower_body) or ("working on" in lower_body) or ("in progress" in lower_body) or ("in-progress" in lower_body)
            if has_subject and body_wc <= 120 and has_thanks and has_feedback and has_fixed and has_next:
                scores["beta_email_word_limit_and_structure"] = 1.0

        if email_subject_line:
            combined = (email_subject_line + "\n" + email_body_text).lower()
            mentions_issue_or_screen = False
            for ent in expected[:3]:
                if ent["issue"].lower() in combined:
                    mentions_issue_or_screen = True
                    break
                for sc in ent["screens"]:
                    if sc.lower() in combined:
                        mentions_issue_or_screen = True
                        break
                if mentions_issue_or_screen:
                    break
            if mentions_issue_or_screen:
                scores["messages_alignment_with_priorities"] = 1.0

    return {k: float(v) for k, v in scores.items()}


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2, sort_keys=False))


if __name__ == "__main__":
    main()