import json
import csv
import sys
import re
from pathlib import Path
from typing import Optional, List, Dict, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text)
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            # Ensure required columns exist
            required = {"id", "title", "author", "year", "country", "type"}
            if not required.issubset(set(reader.fieldnames or [])):
                return None
            return rows
    except Exception:
        return None


def _compute_expected_stats(rows: List[Dict[str, str]]) -> Dict[str, object]:
    total_sources = len(rows)
    unique_authors = len({r["author"].strip() for r in rows})
    # by_country
    country_counts: Dict[str, int] = {}
    for r in rows:
        c = r["country"].strip()
        country_counts[c] = country_counts.get(c, 0) + 1
    # sort by count desc, then country asc
    by_country_pairs: List[Tuple[str, int]] = sorted(
        country_counts.items(),
        key=lambda kv: (-kv[1], kv[0])
    )
    # by_decade
    decade_counts: Dict[str, int] = {}
    for r in rows:
        try:
            y = int(r["year"])
        except Exception:
            # Malformed year; treat as failure upstream by returning impossible decade to trigger mismatch
            y = None
        if y is None:
            continue
        decade_start = (y // 10) * 10
        label = f"{decade_start}s"
        decade_counts[label] = decade_counts.get(label, 0) + 1
    # sort decades chronologically ascending by numeric portion
    def decade_key(label: str) -> int:
        m = re.match(r"^(\d{4})s$", label)
        return int(m.group(1)) if m else 0
    by_decade_pairs: List[Tuple[str, int]] = sorted(decade_counts.items(), key=lambda kv: decade_key(kv[0]))
    unique_countries = len(country_counts)
    return {
        "total_sources": total_sources,
        "unique_authors": unique_authors,
        "by_country_pairs": by_country_pairs,
        "by_decade_pairs": by_decade_pairs,
        "unique_countries": unique_countries,
    }


def _parse_md_table(md_text: str) -> Dict[str, object]:
    # Returns dict with keys: summary_total, summary_unique, rows: list of dicts with keys country,count,share_str,share_num
    lines = md_text.splitlines()
    # Find first non-empty line (or take very first line) but spec says first line is the summary line exactly
    summary_line = lines[0].strip() if lines else ""
    m = re.fullmatch(r"Total sources:\s*(\d+)\s*\|\s*Unique authors:\s*(\d+)", summary_line)
    summary_total = int(m.group(1)) if m else None
    summary_unique = int(m.group(2)) if m else None

    # Find header row containing Country | Count | Share (%)
    header_idx = -1
    header_cols = []
    for i, line in enumerate(lines[1:], start=1):
        if "Country" in line and "Count" in line and "Share (%)" in line:
            # Attempt to parse columns by splitting on |
            parts = [p.strip() for p in line.strip().strip("|").split("|")]
            if len(parts) >= 3:
                header_cols = parts
                header_idx = i
                break
    rows = []
    if header_idx != -1:
        # Determine column indices
        col_map = {}
        for idx, name in enumerate(header_cols):
            col_map[name] = idx
        needed = ["Country", "Count", "Share (%)"]
        if all(n in col_map for n in needed):
            # Skip a possible separator row next
            body_start = header_idx + 1
            # Skip any separator lines composed largely of - : | and spaces
            while body_start < len(lines) and re.fullmatch(r"[\s\|\-\:\+]+", lines[body_start].strip() or ""):
                body_start += 1
            # Collect subsequent table rows until a blank line or non-table-like line
            for j in range(body_start, len(lines)):
                line = lines[j].rstrip("\n")
                if not line.strip():
                    break
                if "|" not in line:
                    break
                parts = [p.strip() for p in line.strip().strip("|").split("|")]
                if len(parts) < len(header_cols):
                    break
                try:
                    country = parts[col_map["Country"]]
                    count_str = parts[col_map["Count"]]
                    share_str = parts[col_map["Share (%)"]]
                    count_val = int(count_str)
                    # share may have optional % sign
                    share_clean = share_str.strip().rstrip("%").strip()
                    share_num = float(share_clean)
                except Exception:
                    continue
                rows.append({
                    "country": country,
                    "count": count_val,
                    "share_str": share_str,
                    "share_num": share_num,
                })
    return {
        "summary_total": summary_total,
        "summary_unique": summary_unique,
        "rows": rows,
    }


def _check_workflow_trigger_only_push_main(yaml_text: str) -> bool:
    # Remove comments (naively: remove everything after # on a line)
    stripped_lines = []
    for line in yaml_text.splitlines():
        # Preserve hashes inside quotes by simple heuristic: if # appears and before it there is an even number of quotes
        # To keep it simple and robust, just strip from first # regardless (most YAML won't put quotes in keys)
        if "#" in line:
            line = line.split("#", 1)[0]
        stripped_lines.append(line.rstrip())
    lines = stripped_lines

    # Find 'on:' block
    on_idx = -1
    on_indent = 0
    for i, line in enumerate(lines):
        if re.match(r"^\s*on:\s*$", line):
            on_idx = i
            on_indent = len(line) - len(line.lstrip(" "))
            break
    if on_idx == -1:
        return False

    # Collect block lines under 'on:'
    block = []
    for j in range(on_idx + 1, len(lines)):
        line = lines[j]
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent <= on_indent:
            break
        block.append((indent, line.strip()))
    # Identify top-level keys inside on block (minimal indent > on_indent)
    if not block:
        return False
    min_indent = min(indent for indent, _ in block)
    top_keys = []
    for indent, content in block:
        if indent == min_indent and content.endswith(":"):
            key = content[:-1].strip()
            top_keys.append((key, indent))
    # Should contain exactly one key: push
    if not top_keys or any(k for k, _ in top_keys if k != "push"):
        return False
    if len([k for k, _ in top_keys]) != 1 or top_keys[0][0] != "push":
        return False

    # Now inside push block, find branches and ensure only 'main'
    push_indent = top_keys[0][1]
    # Gather push sub-block
    push_block = []
    started = False
    for indent, content in block:
        if indent == push_indent and content == "push:":
            started = True
            continue
        if started:
            if indent <= push_indent:
                break
            push_block.append((indent, content))

    # Find branches
    branches_items: List[str] = []
    b_indent = None
    for idx, (indent, content) in enumerate(push_block):
        if content.startswith("branches:"):
            # inline list?
            after = content[len("branches:"):].strip()
            b_indent = indent
            if after.startswith("[") and after.endswith("]"):
                inner = after[1:-1].strip()
                items = [s.strip().strip("'").strip('"') for s in inner.split(",") if s.strip()]
                branches_items.extend(items)
            else:
                # multiline list expected
                # collect subsequent '- item' at indent > b_indent
                k = idx + 1
                while k < len(push_block):
                    sub_indent, sub_content = push_block[k]
                    if sub_indent <= b_indent:
                        break
                    if sub_content.startswith("-"):
                        item = sub_content[1:].strip().strip("'").strip('"')
                        if item:
                            branches_items.append(item)
                    k += 1
            break
    if not branches_items:
        return False
    # Ensure only 'main' present
    if len(branches_items) != 1 or branches_items[0] != "main":
        return False

    # Ensure no other triggers outside 'on:' block like 'pull_request' at top-level 'on' keys
    # Already ensured top_keys only contains push
    return True


def _check_workflow_generate_stats_step(yaml_text: str) -> bool:
    # Look for the "Generate reading stats" step and ensure run block contains the correct invocation
    lines = yaml_text.splitlines()
    target_step_name = "Generate reading stats"
    name_line_idxs = [i for i, line in enumerate(lines) if re.match(r"^\s*name:\s*"+re.escape(target_step_name)+r"\s*$", line)]
    if not name_line_idxs:
        return False
    # For each such step, try to find a run block beneath it
    desired_cmd = "python scripts/compute_stats.py --input data/citations.csv --out-json build/source_stats.json --out-md docs/source_stats.md"
    for name_idx in name_line_idxs:
        step_indent = len(lines[name_idx]) - len(lines[name_idx].lstrip(" "))
        # search forward until next step (line with same or less indent and starting with '- name:' or 'name:')
        j = name_idx + 1
        run_idx = -1
        while j < len(lines):
            line = lines[j]
            indent = len(line) - len(line.lstrip(" "))
            content = line.strip()
            if indent <= step_indent and (content.startswith("name:") or content.startswith("- name:") or content.startswith("-")):
                break
            if re.match(r"^\s*run:\s*\|?\s*$", line):
                run_idx = j
                break
            j += 1
        if run_idx == -1:
            continue
        # Collect run block content
        run_indent = len(lines[run_idx]) - len(lines[run_idx].lstrip(" "))
        # If it's "run: |", then subsequent indented lines are the script
        k = run_idx + 1
        commands = []
        while k < len(lines):
            l = lines[k]
            lindent = len(l) - len(l.lstrip(" "))
            if lindent <= run_indent:
                break
            commands.append(l.strip())
            k += 1
        # Check if any command line contains desired invocation
        for cmd in commands:
            if cmd.strip() == desired_cmd:
                return True
            # Alternatively, parse to verify flags if begins with python scripts/compute_stats.py
            if cmd.strip().startswith("python scripts/compute_stats.py"):
                # tokenize respecting simple spaces
                parts = cmd.strip().split()
                # Expect tokens in pairs for flags
                flags = {}
                i = 0
                while i < len(parts):
                    if parts[i].startswith("--"):
                        key = parts[i]
                        val = parts[i+1] if i+1 < len(parts) else ""
                        flags[key] = val
                        i += 2
                    else:
                        i += 1
                if flags.get("--input") == "data/citations.csv" and flags.get("--out-json") == "build/source_stats.json" and flags.get("--out-md") == "docs/source_stats.md":
                    return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_exists": 0.0,
        "json_present_valid": 0.0,
        "json_totals_correct": 0.0,
        "json_by_country_correct": 0.0,
        "json_by_decade_correct": 0.0,
        "md_present": 0.0,
        "md_summary_line_correct": 0.0,
        "md_table_countries_counts_match_json": 0.0,
        "md_shares_correct": 0.0,
        "course_page_summary_inserted_correctly": 0.0,
        "workflow_trigger_correct": 0.0,
        "workflow_stats_step_invocation_correct": 0.0,
    }

    # Paths
    csv_path = workspace / "data" / "citations.csv"
    json_path = workspace / "build" / "source_stats.json"
    md_path = workspace / "docs" / "source_stats.md"
    course_page_path = workspace / "docs" / "course_page.md"
    workflow_path = workspace / ".github" / "workflows" / "site.yml"
    script_path = workspace / "scripts" / "compute_stats.py"

    # Check script exists
    if script_path.is_file():
        scores["script_exists"] = 1.0

    # Load CSV
    rows = _read_csv_dicts(csv_path)
    if rows is None:
        # Without valid CSV, many checks cannot proceed
        expected_stats = None
    else:
        expected_stats = _compute_expected_stats(rows)

    # JSON checks
    json_obj = _load_json(json_path)
    if json_obj is not None and isinstance(json_obj, dict):
        # Validate structure keys
        required_keys = {"total_sources", "unique_authors", "by_country", "by_decade"}
        if required_keys.issubset(json_obj.keys()):
            # Ensure types
            if isinstance(json_obj.get("total_sources"), int) and isinstance(json_obj.get("unique_authors"), int):
                if isinstance(json_obj.get("by_country"), list) and isinstance(json_obj.get("by_decade"), list):
                    scores["json_present_valid"] = 1.0

    if expected_stats and scores["json_present_valid"] == 1.0:
        # Totals
        totals_ok = (json_obj["total_sources"] == expected_stats["total_sources"] and
                     json_obj["unique_authors"] == expected_stats["unique_authors"])
        scores["json_totals_correct"] = 1.0 if totals_ok else 0.0

        # by_country exact match of pairs and order
        try:
            by_country_list = json_obj["by_country"]
            parsed_pairs = []
            valid_structure = True
            for item in by_country_list:
                if not isinstance(item, dict):
                    valid_structure = False
                    break
                country = item.get("country")
                count = item.get("count")
                if not isinstance(country, str) or not isinstance(count, int):
                    valid_structure = False
                    break
                parsed_pairs.append((country, count))
            expected_pairs = expected_stats["by_country_pairs"]
            by_country_sorted_ok = parsed_pairs == expected_pairs
            scores["json_by_country_correct"] = 1.0 if (valid_structure and by_country_sorted_ok) else 0.0
        except Exception:
            scores["json_by_country_correct"] = 0.0

        # by_decade correct content and chronological order
        try:
            by_decade_list = json_obj["by_decade"]
            parsed_decade_pairs = []
            valid_structure_d = True
            for item in by_decade_list:
                if not isinstance(item, dict):
                    valid_structure_d = False
                    break
                decade = item.get("decade")
                count = item.get("count")
                if not isinstance(decade, str) or not isinstance(count, int):
                    valid_structure_d = False
                    break
                # decade must end with 's' and start with 4 digits
                if not re.fullmatch(r"\d{4}s", decade):
                    valid_structure_d = False
                    break
                parsed_decade_pairs.append((decade, count))
            expected_decade_pairs = expected_stats["by_decade_pairs"]
            by_decade_ok = parsed_decade_pairs == expected_decade_pairs
            scores["json_by_decade_correct"] = 1.0 if (valid_structure_d and by_decade_ok) else 0.0
        except Exception:
            scores["json_by_decade_correct"] = 0.0

    # MD checks
    md_text = _read_text(md_path)
    if md_text is not None:
        scores["md_present"] = 1.0
        parsed_md = _parse_md_table(md_text)
        if parsed_md["summary_total"] is not None and parsed_md["summary_unique"] is not None:
            # Summary line must match exactly the computed numbers
            if expected_stats:
                if parsed_md["summary_total"] == expected_stats["total_sources"] and parsed_md["summary_unique"] == expected_stats["unique_authors"]:
                    # Ensure first line equals the expected string exactly
                    first_line = md_text.splitlines()[0].strip() if md_text.splitlines() else ""
                    expected_first_line = f"Total sources: {expected_stats['total_sources']} | Unique authors: {expected_stats['unique_authors']}"
                    scores["md_summary_line_correct"] = 1.0 if first_line == expected_first_line else 0.0
                else:
                    scores["md_summary_line_correct"] = 0.0

        # Table consistency with JSON by_country order and counts
        if scores["json_by_country_correct"] == 1.0 and "rows" in parsed_md:
            md_rows = parsed_md["rows"]
            json_pairs = json_obj["by_country"]
            # The table must list the same countries and counts in the same order
            same = True
            if len(md_rows) != len(json_pairs):
                same = False
            else:
                for md_row, jp in zip(md_rows, json_pairs):
                    if md_row["country"] != jp["country"] or md_row["count"] != jp["count"]:
                        same = False
                        break
            scores["md_table_countries_counts_match_json"] = 1.0 if same else 0.0

            # Shares correct to one decimal
            if expected_stats and same:
                total = expected_stats["total_sources"]
                shares_ok = True
                for md_row in md_rows:
                    expected_share = round((md_row["count"] * 100.0) / total, 1)
                    # Accept optional '%' sign, but ensure numeric equals expected to one decimal
                    if round(md_row["share_num"], 1) != expected_share:
                        shares_ok = False
                        break
                    # Ensure one decimal place format in string (with or without %)
                    cell = md_row["share_str"].strip()
                    if cell.endswith("%"):
                        num_part = cell[:-1].strip()
                    else:
                        num_part = cell
                    if not re.fullmatch(r"\d+\.\d", num_part):
                        shares_ok = False
                        break
                scores["md_shares_correct"] = 1.0 if shares_ok else 0.0

    # Course page update check
    course_text = _read_text(course_page_path)
    if expected_stats is not None and course_text is not None:
        # Baseline content from the provided input file (normalize newlines to \n)
        baseline = (
            "# Modern Southeast Asian Political History – Course Materials\n\n"
            "Welcome to the course materials hub. Here you will find lecture notes, reading lists, and supplementary resources for discussions on political transitions, state formation, and social movements across Southeast Asia.\n\n"
            "## Bibliography overview\n\n"
            "<!-- STATS_SUMMARY -->\n\n"
            "For a detailed breakdown by country, see the generated report in docs/source_stats.md.\n"
        )
        # Build expected replacement sentence
        # Top 3 by country count, ties broken alphabetically by country name
        top3 = expected_stats["by_country_pairs"][:3]
        sentence = (
            f"This term's bibliography includes {expected_stats['total_sources']} sources spanning "
            f"{expected_stats['unique_countries']} countries; top countries: "
            f"{top3[0][0]} ({top3[0][1]}), {top3[1][0]} ({top3[1][1]}), {top3[2][0]} ({top3[2][1]})."
        )
        expected_course = baseline.replace("<!-- STATS_SUMMARY -->", sentence)
        # Normalize newlines
        def norm(s: str) -> str:
            return s.replace("\r\n", "\n").replace("\r", "\n")
        if norm(course_text) == norm(expected_course):
            scores["course_page_summary_inserted_correctly"] = 1.0
        else:
            scores["course_page_summary_inserted_correctly"] = 0.0

    # Workflow checks
    workflow_text = _read_text(workflow_path)
    if workflow_text is not None:
        if _check_workflow_trigger_only_push_main(workflow_text):
            scores["workflow_trigger_correct"] = 1.0
        if _check_workflow_generate_stats_step(workflow_text):
            scores["workflow_stats_step_invocation_correct"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()