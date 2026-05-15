import json
import csv
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()})
            return rows
    except Exception:
        return None


def _parse_simple_yaml(path: Path) -> Optional[Dict[str, object]]:
    """
    Very small YAML parser for simple key: value at top-level.
    Only supports scalar values and simple top-level lists.
    """
    text = _read_text_safe(path)
    if text is None:
        return None
    result: Dict[str, object] = {}
    current_key = None
    in_list = False
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")
        if not line.strip() or line.strip().startswith("#"):
            continue
        if re.match(r"^[\w\-]+:\s", line) or re.match(r"^[\w\-]+:\s*$", line):
            # New key
            parts = line.split(":", 1)
            key = parts[0].strip()
            val = parts[1].strip()
            if val == "":
                # Could be start of list or nested; we only support list
                current_key = key
                in_list = True
                result[current_key] = []
            else:
                # scalar
                in_list = False
                current_key = key
                # remove quotes if present
                val = val.strip()
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                result[current_key] = val
        elif in_list and current_key is not None and line.strip().startswith("-"):
            item = line.strip()[1:].strip()
            if (item.startswith('"') and item.endswith('"')) or (item.startswith("'") and item.endswith("'")):
                item = item[1:-1]
            lst = result.get(current_key)
            if isinstance(lst, list):
                lst.append(item)
        else:
            # Unsupported structure; ignore safely
            continue
    return result


def _parse_build_output(path: Path) -> Optional[Dict[Tuple[str, str], List[str]]]:
    """
    Parse build_output.txt and return mapping from (module, category) to list of detail tokens.
    Categories: compilation, test_failure, style
    Details:
      - compilation: <FileName.java:line> (from cannot find symbol occurrences)
      - test_failure: <TestName.method:line>
      - style: <FileName.java:line> (from checkstyle warnings)
    """
    text = _read_text_safe(path)
    if text is None:
        return None

    lines = text.splitlines()
    current_module: Optional[str] = None
    in_checkstyle = False
    in_failures_section = False

    groups: Dict[Tuple[str, str], List[str]] = {}

    def add_issue(mod: Optional[str], category: str, detail: str) -> None:
        if not mod:
            return
        key = (mod, category)
        groups.setdefault(key, []).append(detail)

    # Helpers for module detection
    build_re = re.compile(r"^\[INFO\]\s+Building\s+(.+?)\s")
    plugin_module_re = re.compile(r"^\[INFO\]\s+---\s+[^@]+@\s+([^\s]+)\s+---\s*$")
    checkstyle_plugin_re = re.compile(r"^\[INFO\]\s+---\s+maven-checkstyle-plugin:")
    surefire_plugin_re = re.compile(r"^\[INFO\]\s+---\s+maven-surefire-plugin:")

    for i, line in enumerate(lines):
        # Detect module markers
        m1 = build_re.match(line)
        m2 = plugin_module_re.match(line)
        if m1:
            current_module = m1.group(1).strip()
            in_checkstyle = False
            in_failures_section = False
        elif m2:
            current_module = m2.group(1).strip()
            in_checkstyle = False
            in_failures_section = False

        # Detect plugin phases
        if checkstyle_plugin_re.match(line):
            in_checkstyle = True
        elif surefire_plugin_re.match(line):
            # Not necessarily needed, but ensure failures section handled later
            pass

        # Detect leaving sections
        if line.startswith("[INFO] ------------------------------------------------------------------------"):
            in_checkstyle = False
            in_failures_section = False

        # Compilation issues: count individual cannot find symbol occurrences
        # Lines look like:
        # [ERROR] /path/.../UserController.java:[42,13] cannot find symbol
        comp_m = re.match(r"^\[ERROR\]\s+(?P<path>.*?\.java):\[(?P<line>\d+),\d+\]\s+cannot find symbol", line)
        if comp_m and current_module:
            filename = Path(comp_m.group("path")).name
            line_no = comp_m.group("line")
            detail = f"{filename}:{line_no}"
            add_issue(current_module, "compilation", detail)

        # Test failures: detect Failures: section and capture lines starting with "[ERROR]   "
        if line.strip() == "[ERROR] Failures:":
            in_failures_section = True
            continue
        if in_failures_section:
            if line.startswith("[ERROR]   "):
                # Extract token up to first space after id
                # Example: [ERROR]   PaymentProcessorTest.shouldApplyDiscount:57 expected...
                after = line[len("[ERROR]   "):]
                token = after.split(None, 1)[0].strip()
                # Normalize token
                add_issue(current_module, "test_failure", token)
            else:
                # End of failures section when we hit a non-indented error or info
                if line.startswith("[INFO]") or (line.startswith("[ERROR]") and not line.startswith("[ERROR]   ")):
                    in_failures_section = False

        # Style issues: warnings during checkstyle phase; lines like:
        # [WARNING] /path/.../CsvExporter.java:88: message...
        if in_checkstyle and line.startswith("[WARNING] "):
            style_m = re.match(r"^\[WARNING\]\s+(?P<path>.*?\.java):(?P<line>\d+):", line)
            if style_m and current_module:
                filename = Path(style_m.group("path")).name
                line_no = style_m.group("line")
                detail = f"{filename}:{line_no}"
                add_issue(current_module, "style", detail)

    return groups


def _build_expected_issue_summary(build_groups: Dict[Tuple[str, str], List[str]],
                                  roster_rows: List[Dict[str, str]],
                                  project: str,
                                  release_date: str) -> Dict[str, object]:
    # Build roster map
    roster_map: Dict[str, Dict[str, str]] = {}
    for r in roster_rows:
        mod = r.get("module", "")
        roster_map[mod] = {"owner": r.get("owner", ""), "owner_email": r.get("owner_email", "")}

    issues_list = []
    for (module, category), details in sorted(build_groups.items(), key=lambda x: (x[0][0], x[0][1])):
        owner_name = roster_map.get(module, {}).get("owner", "")
        owner_email = roster_map.get(module, {}).get("owner_email", "")
        issues_list.append({
            "module": module,
            "category": category,
            "issue_count": len(details),
            "owner_name": owner_name,
            "owner_email": owner_email,
            "details": details
        })

    return {
        "project": project,
        "release_date": release_date,
        "issues": issues_list
    }


def _json_load(path: Path) -> Optional[object]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _extract_action_lines(standup_text: str) -> List[str]:
    # Extract lines that begin with "Action:" possibly with leading bullet or whitespace
    result = []
    for line in standup_text.splitlines():
        stripped = line.lstrip()
        # Keep verbatim original line when match occurs after optional '-' and spaces
        if stripped.startswith("Action:") or stripped.startswith("- Action:"):
            # Use the original line as "verbatim"
            result.append(line.rstrip("\n"))
    return result


def _owners_from_roster(roster_rows: List[Dict[str, str]]) -> Dict[str, Tuple[str, str]]:
    return {r.get("module", ""): (r.get("owner", ""), r.get("owner_email", "")) for r in roster_rows}


def _find_headings_positions(md_text: str, headings: List[str]) -> Optional[List[int]]:
    """
    Return list of indices (line numbers) for given headings in order.
    Accept heading lines with optional leading '#'s and spaces, but exact heading text and colon.
    """
    lines = md_text.splitlines()
    positions = []
    start_idx = 0
    for heading in headings:
        found_idx = -1
        pattern = re.compile(r"^\s*#*\s*" + re.escape(heading) + r"\s*$")
        for i in range(start_idx, len(lines)):
            if pattern.match(lines[i]):
                found_idx = i
                break
        if found_idx == -1:
            return None
        positions.append(found_idx)
        start_idx = found_idx + 1
    return positions


def _section_text(md_text: str, start_line: int, end_line: Optional[int]) -> str:
    lines = md_text.splitlines()
    if end_line is None:
        body_lines = lines[start_line + 1:]
    else:
        body_lines = lines[start_line + 1:end_line]
    return "\n".join(body_lines).strip()


def _word_count(text: str) -> int:
    return len([w for w in re.findall(r"\b\w+\b", text)])


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "issue_summary_json_present_and_valid_structure": 0.0,
        "issue_summary_project_release_match_input": 0.0,
        "issue_summary_groups_and_counts_correct": 0.0,
        "issue_summary_details_quality": 0.0,
        "owners_report_matches_json": 0.0,
        "knowledge_base_headings_order": 0.0,
        "knowledge_base_overview_includes_project_and_date": 0.0,
        "knowledge_base_roster_lists_all": 0.0,
        "knowledge_base_current_issues_references": 0.0,
        "knowledge_base_action_items_listed": 0.0,
        "team_email_subject_and_word_limit": 0.0,
        "team_email_mentions_modules_owners_and_deadline": 0.0,
        "slack_rewrite_constraints": 0.0,
    }

    # Input file paths
    build_output_path = workspace / "input" / "build_output.txt"
    roster_path = workspace / "input" / "roster.csv"
    standup_notes_path = workspace / "input" / "standup_notes.md"
    project_brief_path = workspace / "input" / "project_brief.yaml"

    # Outputs
    outputs_dir = workspace / "outputs"
    issue_summary_path = outputs_dir / "issue_summary.json"
    owners_report_path = outputs_dir / "owners_report.csv"
    knowledge_base_path = outputs_dir / "knowledge_base.md"
    team_email_path = outputs_dir / "team_email.txt"
    slack_rewrite_path = outputs_dir / "draft_slack_message_rewrite.txt"

    # Load inputs
    roster_rows = _load_csv_dicts(roster_path) or []
    standup_text = _read_text_safe(standup_notes_path) or ""
    project_brief = _parse_simple_yaml(project_brief_path) or {}
    project = str(project_brief.get("project", "") or "")
    release_date = str(project_brief.get("release_date", "") or "")

    build_groups = _parse_build_output(build_output_path) or {}

    # Build expected summary from inputs
    expected_summary = _build_expected_issue_summary(build_groups, roster_rows, project, release_date)

    # Load student's issue_summary.json
    issue_summary = _json_load(issue_summary_path)
    if isinstance(issue_summary, dict):
        # Validate structure minimally
        if "project" in issue_summary and "release_date" in issue_summary and "issues" in issue_summary and isinstance(issue_summary["issues"], list):
            scores["issue_summary_json_present_and_valid_structure"] = 1.0

    # Check project/release match input
    if isinstance(issue_summary, dict):
        if issue_summary.get("project") == project and issue_summary.get("release_date") == release_date:
            scores["issue_summary_project_release_match_input"] = 1.0

    # Compare groups and counts and owners
    groups_ok = False
    details_ok = False
    if isinstance(issue_summary, dict) and isinstance(issue_summary.get("issues"), list):
        # Build maps
        expected_map: Dict[Tuple[str, str], Dict[str, object]] = {}
        expected_details_tokens: Dict[Tuple[str, str], List[str]] = {}
        for item in expected_summary["issues"]:
            key = (item["module"], item["category"])
            expected_map[key] = item
            expected_details_tokens[key] = list(item["details"])

        student_map: Dict[Tuple[str, str], Dict[str, object]] = {}
        try:
            for item in issue_summary["issues"]:
                module = item.get("module")
                category = item.get("category")
                if not isinstance(module, str) or not isinstance(category, str):
                    raise ValueError
                student_map[(module, category)] = item
        except Exception:
            student_map = {}

        # Groups set equality and counts + owners
        if set(student_map.keys()) == set(expected_map.keys()):
            all_counts_ok = True
            owners_ok = True
            for key in expected_map.keys():
                exp = expected_map[key]
                stu = student_map[key]
                # Check count
                if int(stu.get("issue_count", -1)) != int(exp.get("issue_count", -2)):
                    all_counts_ok = False
                # Check owner fields
                if stu.get("owner_name") != exp.get("owner_name") or stu.get("owner_email") != exp.get("owner_email"):
                    owners_ok = False
            if all_counts_ok and owners_ok:
                groups_ok = True

        # Details quality: lengths equal and coverage of expected tokens
        details_all_ok = True
        for key, exp_tokens in expected_details_tokens.items():
            stu = student_map.get(key)
            if not stu or not isinstance(stu.get("details"), list):
                details_all_ok = False
                break
            stu_details = [str(x) for x in stu.get("details")]
            if len(stu_details) != len(exp_tokens):
                details_all_ok = False
                break
            # each expected token should be contained in some student detail
            for tok in exp_tokens:
                if not any(tok in d for d in stu_details):
                    details_all_ok = False
                    break
            if not details_all_ok:
                break
        if details_all_ok and groups_ok:
            details_ok = True

    if groups_ok:
        scores["issue_summary_groups_and_counts_correct"] = 1.0
    if details_ok:
        scores["issue_summary_details_quality"] = 1.0

    # owners_report_matches_json
    owners_report_ok = False
    if issue_summary and isinstance(issue_summary, dict) and isinstance(issue_summary.get("issues"), list):
        # Build expected rows from student's JSON
        exp_rows = []
        for it in issue_summary["issues"]:
            try:
                exp_rows.append((
                    str(it["module"]),
                    str(it["category"]),
                    str(it["owner_name"]),
                    str(it["owner_email"]),
                    str(int(it["issue_count"]))
                ))
            except Exception:
                pass
        # Read CSV
        rows = _load_csv_dicts(owners_report_path)
        if rows is not None:
            # Validate header
            header_ok = False
            try:
                with owners_report_path.open("r", encoding="utf-8") as f:
                    header_line = f.readline().strip()
                    header_ok = (header_line == "module,category,owner,owner_email,issue_count")
            except Exception:
                header_ok = False
            if header_ok:
                stu_rows = []
                for r in rows:
                    try:
                        stu_rows.append((
                            r.get("module", ""),
                            r.get("category", ""),
                            r.get("owner", ""),
                            r.get("owner_email", ""),
                            str(int(r.get("issue_count", "0")))
                        ))
                    except Exception:
                        # malformed row
                        stu_rows.append(("", "", "", "", ""))
                if sorted(stu_rows) == sorted(exp_rows) and len(stu_rows) == len(exp_rows):
                    owners_report_ok = True
    if owners_report_ok:
        scores["owners_report_matches_json"] = 1.0

    # knowledge_base.md checks
    kb_text = _read_text_safe(knowledge_base_path) or ""
    headings = ["Project Overview:", "Team Roster:", "Current Issues:", "Action Items:"]
    heading_positions = _find_headings_positions(kb_text, headings) if kb_text else None
    if heading_positions is not None:
        scores["knowledge_base_headings_order"] = 1.0

        # Sections
        # Determine section texts
        po_start = heading_positions[0]
        tr_start = heading_positions[1]
        ci_start = heading_positions[2]
        ai_start = heading_positions[3]
        po_text = _section_text(kb_text, po_start, tr_start)
        tr_text = _section_text(kb_text, tr_start, ci_start)
        ci_text = _section_text(kb_text, ci_start, ai_start)
        ai_text = _section_text(kb_text, ai_start, None)

        # Project Overview must include project and release_date
        if project and release_date and (project in po_text) and (release_date in po_text):
            scores["knowledge_base_overview_includes_project_and_date"] = 1.0

        # Team Roster must list each module with owner and owner_email
        roster_ok = True
        for r in roster_rows:
            mod = r.get("module", "")
            owner = r.get("owner", "")
            email = r.get("owner_email", "")
            # Simple containment check
            if not (mod in tr_text and owner in tr_text and email in tr_text):
                roster_ok = False
                break
        if roster_ok and roster_rows:
            scores["knowledge_base_roster_lists_all"] = 1.0

        # Current Issues: summarize counts by module and category and include at least one representative detail per module
        ci_ok = False
        detail_ok_per_module = True
        counts_ok = True
        modules_seen = set()
        if issue_summary and isinstance(issue_summary, dict) and isinstance(issue_summary.get("issues"), list):
            # For each group, ensure module, category and count numeral appear
            for it in issue_summary["issues"]:
                mod = str(it.get("module", ""))
                cat = str(it.get("category", ""))
                cnt = str(it.get("issue_count", ""))
                if not (mod and cat and cnt):
                    counts_ok = False
                    break
                if not (mod in ci_text and cat in ci_text and cnt in ci_text):
                    counts_ok = False
                    break
                modules_seen.add(mod)
            # For each module, at least one detail from its details list appears
            if counts_ok:
                module_to_details: Dict[str, List[str]] = {}
                for it in issue_summary["issues"]:
                    module_to_details.setdefault(str(it["module"]), [])
                    details_list = it.get("details", [])
                    if isinstance(details_list, list):
                        for d in details_list:
                            module_to_details[str(it["module"])].append(str(d))
                for mod, detail_list in module_to_details.items():
                    if not detail_list:
                        detail_ok_per_module = False
                        break
                    # At least one detail token contained in ci_text
                    if not any(tok in ci_text for tok in detail_list):
                        detail_ok_per_module = False
                        break
            ci_ok = counts_ok and detail_ok_per_module
        if ci_ok:
            scores["knowledge_base_current_issues_references"] = 1.0

        # Action Items: extract every line from standup_notes.md that begins with "Action:" and list them verbatim
        expected_actions = _extract_action_lines(standup_text)
        ai_ok = True
        for action_line in expected_actions:
            if action_line not in ai_text:
                ai_ok = False
                break
        # If there are expected actions, require they are present; if none expected, consider it ok
        if ai_ok:
            scores["knowledge_base_action_items_listed"] = 1.0

    # team_email.txt checks
    email_text = _read_text_safe(team_email_path) or ""
    email_ok_subject = False
    email_ok_body = False
    if email_text:
        lines = email_text.splitlines()
        if lines:
            subject_line = lines[0].strip()
            body_text = "\n".join(lines[1:]).strip()
            if subject_line.startswith("Subject:") and (project in subject_line) and (release_date in subject_line):
                email_ok_subject = True
            if body_text:
                word_count = _word_count(body_text)
                if word_count <= 200:
                    # Must mention modules and owners and deadline ask
                    modules = [it.get("module") for it in (issue_summary.get("issues", []) if isinstance(issue_summary, dict) else [])]
                    modules = [str(m) for m in modules if isinstance(m, str)]
                    owners_map = _owners_from_roster(roster_rows)
                    modules_unique = sorted(set(modules))
                    # For each module, its name appears; each owner name appears
                    modules_present = all(m in body_text for m in modules_unique) if modules_unique else False
                    owners_present = all(owners_map.get(m, ("", ""))[0] in body_text for m in modules_unique) if modules_unique else False
                    # Must reference deadline and clear ask
                    has_deadline = release_date in body_text
                    ask_words = ["address", "resolve", "fix", "investigate", "please"]
                    has_ask = any(w in body_text.lower() for w in ask_words)
                    if modules_present and owners_present and has_deadline and has_ask:
                        email_ok_body = True
    if email_ok_subject:
        scores["team_email_subject_and_word_limit"] = 1.0 if (_word_count("\n".join(email_text.splitlines()[1:])) <= 200) else 0.0
    if email_ok_body:
        scores["team_email_mentions_modules_owners_and_deadline"] = 1.0

    # slack rewrite constraints
    slack_text = _read_text_safe(slack_rewrite_path) or ""
    slack_ok = False
    if slack_text:
        word_count = _word_count(slack_text)
        has_release_date = release_date in slack_text
        # Determine top two modules by total issue_count from student's JSON (as specified)
        top_two: List[str] = []
        if issue_summary and isinstance(issue_summary, dict) and isinstance(issue_summary.get("issues"), list):
            totals: Dict[str, int] = {}
            for it in issue_summary["issues"]:
                mod = str(it.get("module", ""))
                cnt = int(it.get("issue_count", 0)) if isinstance(it.get("issue_count", 0), int) or str(it.get("issue_count")).isdigit() else 0
                totals[mod] = totals.get(mod, 0) + cnt
            # Sort by count desc, then module name asc
            sorted_mods = sorted(totals.items(), key=lambda x: (-x[1], x[0]))
            top_two = [m for m, _ in sorted_mods[:2]]
        mentions_top_two = all(m in slack_text for m in top_two) if top_two else False
        # Friendly and direct: require "please" or "thanks"/"thank you"
        friendly = any(w in slack_text.lower() for w in ["please", "thanks", "thank you"])
        # Avoid blame: ensure absence of certain words
        banned = ["blame", "fault", "stupid", "idiot", "incompetent", "lazy"]
        no_blaming = not any(b in slack_text.lower() for b in banned)
        # Specific ask: presence of action words
        action_words = ["address", "resolve", "fix", "investigate", "review", "update"]
        has_action = any(w in slack_text.lower() for w in action_words)
        if word_count <= 100 and has_release_date and mentions_top_two and friendly and no_blaming and has_action:
            slack_ok = True
    if slack_ok:
        scores["slack_rewrite_constraints"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()