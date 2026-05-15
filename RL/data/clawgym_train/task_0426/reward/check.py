import json
import csv
import sys
import re
from pathlib import Path
from collections import defaultdict, Counter


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _safe_load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return reader.fieldnames or [], rows
    except Exception:
        return [], []


def _float_equal(a: float, b: float, tol: float = 0.01) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def _parse_report_sections(text: str, headings: list) -> dict:
    # Returns mapping heading -> (start_idx_of_content, end_idx_exclusive, content_lines)
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    idxs = {}
    for i, ln in enumerate(lines):
        if ln.strip() in headings:
            idxs[ln.strip()] = i
    sections = {}
    for i, h in enumerate(headings):
        if h not in idxs:
            continue
        start = idxs[h] + 1
        # find next heading index
        next_idx = len(lines)
        for j in range(i + 1, len(headings)):
            if headings[j] in idxs and idxs[headings[j]] > idxs[h]:
                next_idx = min(next_idx, idxs[headings[j]])
        sections[h] = (start, next_idx, lines[start:next_idx])
    return sections


def _parse_markdown_table(lines: list, expected_headers: list):
    # Return (ok, header_cells, rows_as_list_of_dicts)
    # Extract lines containing '|' and not empty
    table_lines = [ln.strip() for ln in lines if '|' in ln]
    if not table_lines:
        return False, [], []
    # Split header
    header_line = table_lines[0]
    # Handle Markdown pipes possibly with surrounding pipes
    def split_row(s: str):
        s2 = s.strip()
        if s2.startswith("|"):
            s2 = s2[1:]
        if s2.endswith("|"):
            s2 = s2[:-1]
        return [c.strip() for c in s2.split("|")]
    header_cells = split_row(header_line)
    # Normalize spaces and lowercase for comparison
    if [h.strip() for h in header_cells] != expected_headers:
        # Try case-insensitive exact match
        if [h.strip().lower() for h in header_cells] != [e.lower() for e in expected_headers]:
            return False, header_cells, []
    # Skip separator line if present (e.g., --- | ---)
    data_lines = table_lines[1:]
    if data_lines:
        sep_cells = split_row(data_lines[0])
        if all(set(c.replace("-", "").strip()) == set() for c in sep_cells):
            data_lines = data_lines[1:]
    rows = []
    for ln in data_lines:
        cells = split_row(ln)
        if len(cells) != len(expected_headers):
            continue
        row = {expected_headers[i]: cells[i] for i in range(len(expected_headers))}
        rows.append(row)
    return True, expected_headers, rows


def _extract_number_from_line(line: str):
    m = re.findall(r"[-+]?\d*\.\d+|\d+", line)
    if not m:
        return None
    # prefer last number to handle labels containing digits
    s = m[-1]
    try:
        if "." in s:
            return float(s)
        else:
            return int(s)
    except Exception:
        return None


def _compute_expected_from_csv(csv_rows: list):
    # Convert fields to appropriate types
    rows = []
    for r in csv_rows:
        try:
            rows.append({
                "date": r["date"],
                "route": r["route"],
                "group_size": int(r["group_size"]),
                "rating": float(r["rating"]),
                "comment": (r.get("comment") or "").strip()
            })
        except Exception:
            return None
    if not rows:
        return {
            "overview": {"total_tours": 0, "total_visitors": 0, "avg_rating": 0.0, "avg_group_size": 0.0},
            "by_route": {},
            "by_month": {},
            "highlights": [],
            "top_keywords": {}
        }
    total_tours = len(rows)
    total_visitors = sum(r["group_size"] for r in rows)
    avg_rating = round(sum(r["rating"] for r in rows) / total_tours, 2)
    avg_group_size = round(total_visitors / total_tours, 2)
    overview = {
        "total_tours": total_tours,
        "total_visitors": total_visitors,
        "avg_rating": avg_rating,
        "avg_group_size": avg_group_size
    }
    # By route
    routes = defaultdict(list)
    for r in rows:
        routes[r["route"]].append(r)
    by_route = {}
    for route, rs in routes.items():
        tours = len(rs)
        avg_r = round(sum(x["rating"] for x in rs) / tours, 2) if tours else 0.0
        tot_v = sum(x["group_size"] for x in rs)
        avg_g = round(tot_v / tours, 2) if tours else 0.0
        by_route[route] = {
            "tours": tours,
            "avg_rating": avg_r,
            "total_visitors": tot_v,
            "avg_group_size": avg_g
        }
    # By month (YYYY-MM)
    by_month = defaultdict(int)
    for r in rows:
        month = r["date"][:7]
        by_month[month] += 1
    # Highlights will depend on config thresholds; compute function later
    # Top comment keywords
    stopwords = set(["the","and","a","an","to","of","for","with","but","very","more","great","good","at","on","in","it","is","was","were","be","being","been","this","that","those","these","as","about"])
    counter = Counter()
    for r in rows:
        text = r["comment"].lower()
        # strip punctuation: keep alphanumerics and whitespace
        text = re.sub(r"[^a-z0-9\s]", " ", text)
        tokens = [t for t in text.split() if t and t not in stopwords]
        counter.update(tokens)
    top_keywords_counts = dict(counter)
    return {
        "overview": overview,
        "by_route": by_route,
        "by_month": dict(by_month),
        "rows": rows,
        "top_keywords": top_keywords_counts
    }


def _compute_expected_highlights(rows: list, high_rating_threshold: float, large_group_size: int):
    highlights = []
    for r in rows:
        if (r["rating"] >= high_rating_threshold) or (r["group_size"] >= large_group_size):
            highlights.append(f'{r["date"]} — {r["route"]} (rating {r["rating"]}, group {r["group_size"]})')
    return highlights


def _count_words(text: str) -> int:
    if not isinstance(text, str):
        return 0
    tokens = [t for t in re.findall(r"\S+", text.strip())]
    return len(tokens)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_report_title_correct": 0.0,
        "config_thresholds_correct": 0.0,
        "config_highlight_routes_include_required": 0.0,
        "report_exists_and_sections_order": 0.0,
        "report_title_matches_config": 0.0,
        "report_configuration_section_reflects_config": 0.0,
        "overview_values_correct": 0.0,
        "by_route_table_header_correct": 0.0,
        "by_route_values_correct": 0.0,
        "by_month_table_header_correct": 0.0,
        "by_month_values_correct": 0.0,
        "highlights_list_correct": 0.0,
        "top_keywords_list_valid": 0.0,
        "route_stats_csv_header_correct": 0.0,
        "route_stats_csv_values_correct": 0.0,
        "messages_rewritten_exists_and_schema": 0.0,
        "messages_ids_coverage": 0.0,
        "messages_placeholders_preserved": 0.0,
        "messages_subject_length_ok": 0.0,
        "messages_body_word_limit_and_count_ok": 0.0,
    }

    # Paths
    config_path = workspace / "config" / "report.json"
    feedback_csv_path = workspace / "input" / "tour_feedback.csv"
    messages_json_path = workspace / "input" / "messages.json"
    report_md_path = workspace / "output" / "docs" / "tour_report.md"
    route_stats_csv_path = workspace / "output" / "route_stats.csv"
    messages_rewritten_path = workspace / "output" / "messages_rewritten.json"

    # Load inputs
    cfg = _safe_load_json(config_path)
    csv_headers, csv_rows = _safe_read_csv_dicts(feedback_csv_path)
    msgs = _safe_load_json(messages_json_path)
    expected = None
    if csv_rows:
        expected = _compute_expected_from_csv(csv_rows)

    # 1) Config checks
    required_routes = {"Village Heritage Walk", "Riverside Geology Stroll", "Hartington Hall & Grounds"}
    target_title = "Hartington History Walks — Term Summary"
    target_high = 4.5
    target_group = 20

    if isinstance(cfg, dict):
        # title
        if cfg.get("report_title") == target_title:
            scores["config_report_title_correct"] = 1.0
        # thresholds
        if (cfg.get("high_rating_threshold") == target_high) and (cfg.get("large_group_size") == target_group):
            scores["config_thresholds_correct"] = 1.0
        # highlight routes include required
        hr = cfg.get("highlight_routes")
        if isinstance(hr, list):
            if required_routes.issubset(set(hr)):
                scores["config_highlight_routes_include_required"] = 1.0

    # 2) Report checks
    report_text = _safe_read_text(report_md_path)
    headings_order = ["Configuration", "Overview", "By Route", "By Month", "Highlights", "Top Comment Keywords"]
    sections = {}
    if report_text:
        # report exists and sections order
        # Title line is expected to be first non-empty line
        lines = [ln.strip() for ln in report_text.splitlines()]
        non_empty_lines = [ln for ln in lines if ln]
        # Parse sections
        sections = _parse_report_sections(report_text, headings_order)
        # Check all headings present and in order
        heading_positions = []
        for h in headings_order:
            pos = None
            # Find exact heading line
            for i, ln in enumerate(lines):
                if ln == h:
                    pos = i
                    break
            if pos is None:
                heading_positions = []
                break
            heading_positions.append(pos)
        if heading_positions and heading_positions == sorted(heading_positions):
            scores["report_exists_and_sections_order"] = 1.0

        # Title matches config
        if isinstance(cfg, dict):
            if non_empty_lines:
                if non_empty_lines[0] == cfg.get("report_title"):
                    scores["report_title_matches_config"] = 1.0

        # Configuration section reflects config
        if "Configuration" in sections and isinstance(cfg, dict):
            _, _, conf_lines = sections["Configuration"]
            conf_blob = "\n".join(conf_lines)
            conf_ok = True
            # thresholds and values presence
            high_str = str(cfg.get("high_rating_threshold"))
            lg_str = str(cfg.get("large_group_size"))
            if (high_str not in conf_blob) or (lg_str not in conf_blob):
                conf_ok = False
            # highlight routes values presence
            for rr in required_routes:
                if rr not in conf_blob:
                    conf_ok = False
                    break
            if conf_ok:
                scores["report_configuration_section_reflects_config"] = 1.0

        # Overview values correct
        if "Overview" in sections and expected is not None:
            _, _, ov_lines = sections["Overview"]
            # Find labeled lines (case-insensitive)
            labels = {
                "Total tours": expected["overview"]["total_tours"],
                "Total visitors": expected["overview"]["total_visitors"],
                "Average rating": expected["overview"]["avg_rating"],
                "Average group size": expected["overview"]["avg_group_size"],
            }
            found_all = True
            for label, exp_val in labels.items():
                # find line containing this label
                candidates = [ln for ln in ov_lines if label.lower() in ln.lower()]
                if not candidates:
                    found_all = False
                    break
                num = _extract_number_from_line(candidates[0])
                if num is None:
                    found_all = False
                    break
                # compare numerically (floats use tolerance)
                if isinstance(exp_val, float):
                    if not _float_equal(float(num), exp_val):
                        found_all = False
                        break
                else:
                    try:
                        if int(num) != int(exp_val):
                            found_all = False
                            break
                    except Exception:
                        found_all = False
                        break
            if found_all:
                scores["overview_values_correct"] = 1.0

        # By Route table
        if "By Route" in sections and expected is not None:
            _, _, br_lines = sections["By Route"]
            expected_headers = ["route", "tours", "avg_rating", "total_visitors", "avg_group_size"]
            ok, headers, rows = _parse_markdown_table(br_lines, expected_headers)
            if ok:
                scores["by_route_table_header_correct"] = 1.0
                # Build expected rows dict
                exp_map = expected["by_route"]
                # Validate rows contain all routes and values
                ok_values = True
                # Create set to track seen routes
                seen_routes = set()
                for row in rows:
                    route = row.get("route", "")
                    if route not in exp_map:
                        ok_values = False
                        break
                    seen_routes.add(route)
                    # compare fields
                    exp = exp_map[route]
                    # tours int
                    try:
                        if int(row["tours"]) != int(exp["tours"]):
                            ok_values = False
                            break
                    except Exception:
                        ok_values = False
                        break
                    # avg_rating float 2 decimals tolerance
                    try:
                        if not _float_equal(float(row["avg_rating"]), float(exp["avg_rating"])):
                            ok_values = False
                            break
                    except Exception:
                        ok_values = False
                        break
                    # total_visitors int
                    try:
                        if int(row["total_visitors"]) != int(exp["total_visitors"]):
                            ok_values = False
                            break
                    except Exception:
                        ok_values = False
                        break
                    # avg_group_size float
                    try:
                        if not _float_equal(float(row["avg_group_size"]), float(exp["avg_group_size"])):
                            ok_values = False
                            break
                    except Exception:
                        ok_values = False
                        break
                # Ensure all expected routes present
                if seen_routes != set(exp_map.keys()):
                    ok_values = False
                if ok_values:
                    scores["by_route_values_correct"] = 1.0

        # By Month table
        if "By Month" in sections and expected is not None:
            _, _, bm_lines = sections["By Month"]
            expected_headers = ["month", "tours"]
            ok, headers, rows = _parse_markdown_table(bm_lines, expected_headers)
            if ok:
                scores["by_month_table_header_correct"] = 1.0
                # map months from table
                table_map = {}
                ok_vals = True
                for row in rows:
                    month = row.get("month", "")
                    try:
                        tours = int(row.get("tours", ""))
                    except Exception:
                        ok_vals = False
                        break
                    table_map[month] = tours
                # compare with expected months
                if ok_vals and table_map == expected["by_month"]:
                    scores["by_month_values_correct"] = 1.0

        # Highlights
        if "Highlights" in sections and expected is not None and isinstance(cfg, dict):
            _, _, hl_lines = sections["Highlights"]
            # gather bullet lines
            bullets = []
            for ln in hl_lines:
                s = ln.strip()
                if not s:
                    continue
                if s.startswith("-") or s.startswith("*"):
                    s = s.lstrip("-* ").strip()
                bullets.append(s)
            exp_hl = _compute_expected_highlights(expected["rows"], float(cfg.get("high_rating_threshold", 0)), int(cfg.get("large_group_size", 0)))
            if set(bullets) == set(exp_hl) and len(bullets) == len(exp_hl):
                scores["highlights_list_correct"] = 1.0

        # Top Comment Keywords
        if "Top Comment Keywords" in sections and expected is not None:
            _, _, tk_lines = sections["Top Comment Keywords"]
            # Extract bullet items as (term, count)
            items = []
            for ln in tk_lines:
                s = ln.strip()
                if not s:
                    continue
                if s.startswith("-") or s.startswith("*"):
                    s = s.lstrip("-* ").strip()
                # extract last integer as count
                m_count = re.findall(r"\d+", s)
                if not m_count:
                    continue
                count = int(m_count[-1])
                # extract first word token as term (letters/digits)
                m_term = re.findall(r"[A-Za-z0-9]+", s)
                if not m_term:
                    continue
                term = m_term[0].lower()
                items.append((term, count))
            valid = True
            if len(items) != 5:
                valid = False
            else:
                # Ensure each item matches expected counts and not a stopword; ensure "informative" appears with correct count if present in expected
                exp_counts = expected["top_keywords"]
                stopwords = set(["the","and","a","an","to","of","for","with","but","very","more","great","good","at","on","in","it","is","was","were","be","being","been","this","that","those","these","as","about"])
                for term, cnt in items:
                    if term in stopwords:
                        valid = False
                        break
                    if term not in exp_counts:
                        valid = False
                        break
                    if exp_counts[term] != cnt:
                        valid = False
                        break
                # ensure top unique max "informative" is included if it exists with max count
                if valid:
                    # Determine max count
                    if exp_counts:
                        max_term = max(exp_counts.items(), key=lambda x: x[1])[0]
                        max_cnt = exp_counts[max_term]
                        # If informative is the unique max, require its presence
                        top_terms = [t for t, c in exp_counts.items() if c == max_cnt]
                        if len(top_terms) == 1 and top_terms[0] == "informative":
                            if ("informative", max_cnt) not in items:
                                valid = False
                # Ensure unique terms
                if valid and len(set(t for t, _ in items)) != 5:
                    valid = False
            if valid:
                scores["top_keywords_list_valid"] = 1.0

    # 3) Route stats CSV checks
    header, rows = _safe_read_csv_dicts(route_stats_csv_path)
    expected_headers_csv = ["route", "tours", "avg_rating", "total_visitors", "avg_group_size"]
    if header and [h.strip() for h in header] == expected_headers_csv:
        scores["route_stats_csv_header_correct"] = 1.0
    if expected is not None and rows:
        # Build map from CSV
        csv_map = {}
        ok_vals = True
        for r in rows:
            route = r.get("route")
            try:
                rec = {
                    "tours": int(r.get("tours", "")),
                    "avg_rating": float(r.get("avg_rating", "")),
                    "total_visitors": int(r.get("total_visitors", "")),
                    "avg_group_size": float(r.get("avg_group_size", "")),
                }
            except Exception:
                ok_vals = False
                break
            csv_map[route] = rec
        if ok_vals and set(csv_map.keys()) == set(expected["by_route"].keys()):
            for route, exp in expected["by_route"].items():
                got = csv_map.get(route)
                if got is None:
                    ok_vals = False
                    break
                if got["tours"] != exp["tours"]:
                    ok_vals = False
                    break
                if not _float_equal(got["avg_rating"], exp["avg_rating"]):
                    ok_vals = False
                    break
                if got["total_visitors"] != exp["total_visitors"]:
                    ok_vals = False
                    break
                if not _float_equal(got["avg_group_size"], exp["avg_group_size"]):
                    ok_vals = False
                    break
        else:
            ok_vals = False
        if ok_vals:
            scores["route_stats_csv_values_correct"] = 1.0

    # 4) Messages rewrites checks
    msgs_out = _safe_load_json(messages_rewritten_path)
    # Basic schema
    schema_ok = False
    if isinstance(msgs_out, list):
        # every item is dict with fields id, new_subject, new_body, word_count
        schema_ok = True
        for item in msgs_out:
            if not isinstance(item, dict):
                schema_ok = False
                break
            if not all(k in item for k in ["id", "new_subject", "new_body", "word_count"]):
                schema_ok = False
                break
        if schema_ok:
            scores["messages_rewritten_exists_and_schema"] = 1.0

    # ids coverage
    if isinstance(msgs, dict) and "drafts" in msgs and isinstance(msgs_out, list):
        src_ids = {d.get("id") for d in msgs.get("drafts", []) if isinstance(d, dict)}
        out_ids = {d.get("id") for d in msgs_out if isinstance(d, dict)}
        if src_ids and src_ids == out_ids:
            scores["messages_ids_coverage"] = 1.0

        # placeholders preserved (across subject+body)
        placeholders = ["{DATE}", "{TIME}", "{MEETING_POINT}"]
        preserved_ok = True
        # Build map id -> combined original placeholders present
        src_ph_map = {}
        for d in msgs.get("drafts", []):
            if not isinstance(d, dict):
                preserved_ok = False
                break
            text = f"{d.get('subject','')} {d.get('body','')}"
            present = set(p for p in placeholders if p in text)
            src_ph_map[d.get("id")] = present
        for item in msgs_out:
            if not isinstance(item, dict):
                preserved_ok = False
                break
            oid = item.get("id")
            present = src_ph_map.get(oid, set())
            new_text = f"{item.get('new_subject','')} {item.get('new_body','')}"
            for p in present:
                if p not in new_text:
                    preserved_ok = False
                    break
            if not preserved_ok:
                break
        if preserved_ok and src_ph_map:
            scores["messages_placeholders_preserved"] = 1.0

        # subject length and body limits
        subj_ok = True
        body_ok = True
        for item in msgs_out if isinstance(msgs_out, list) else []:
            subj = item.get("new_subject", "")
            body = item.get("new_body", "")
            wc = item.get("word_count", None)
            if not isinstance(subj, str) or len(subj) > 60:
                subj_ok = False
            # count words
            wc_calc = _count_words(body)
            if (not isinstance(body, str)) or wc_calc > 120:
                body_ok = False
            try:
                if int(wc) != wc_calc:
                    body_ok = False
            except Exception:
                body_ok = False
        if subj_ok and msgs_out:
            scores["messages_subject_length_ok"] = 1.0
        if body_ok and msgs_out:
            scores["messages_body_word_limit_and_count_ok"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()