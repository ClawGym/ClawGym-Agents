import os
import sys
import json
import csv
from typing import List, Dict, Tuple

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def read_lines(path: str) -> List[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().splitlines()
    except Exception:
        return []

def read_csv_rows(path: str) -> List[Dict[str, str]]:
    rows = []
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                rows.append({k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in r.items()})
    except Exception:
        return []
    return rows

def parse_yaml_campaigns(path: str) -> List[Dict[str, str]]:
    # Minimal YAML list-of-dicts parser for simple "key: value" lines
    # Expects a list like:
    # - name: X
    #   start: YYYY-MM-DD
    #   end: YYYY-MM-DD
    #   goal: ...
    #   status: ...
    #   progress: 42
    items = []
    current = None
    try:
        for raw in read_lines(path):
            line = raw.rstrip("\n")
            stripped = line.strip()
            if stripped.startswith("- "):
                # Start of new item
                if current:
                    items.append(current)
                current = {}
                after_dash = stripped[2:].strip()
                if after_dash:
                    if ":" in after_dash:
                        k, v = after_dash.split(":", 1)
                        current[k.strip()] = v.strip().strip('"').strip("'")
            elif current is not None and ":" in stripped:
                k, v = stripped.split(":", 1)
                current[k.strip()] = v.strip().strip('"').strip("'")
        if current:
            items.append(current)
    except Exception:
        return []
    return items

def section_block(lines: List[str], start_marker: str) -> Tuple[int, int]:
    # Return (start_idx, end_idx_exclusive) of the section that starts with a line containing start_marker
    # Ends at next line that starts with '## ' or '### ' (another section) and not the same start line
    start_idx = -1
    for i, ln in enumerate(lines):
        if start_marker.lower() in ln.lower():
            start_idx = i
            break
    if start_idx == -1:
        return (-1, -1)
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        if lines[j].startswith("## ") or lines[j].startswith("### "):
            end_idx = j
            break
    return (start_idx, end_idx)

def contains_metric_row(content_lines: List[str], metric_name: str, current_val, previous_val) -> bool:
    # Check if a single line contains metric_name and both numbers
    cur_s = str(current_val)
    prev_s = str(previous_val)
    for ln in content_lines:
        if metric_name in ln and cur_s in ln and prev_s in ln:
            return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Initialize checks
    checks = {
        "check1_hot_cache_structure": False,
        "check2_dir_structure": False,
        "check3_keyword_files_last_updated": False,
        "check4_historical_rankings": False,
        "check5_hot_cache_keywords_and_promotions": False,
        "check6_competitors_in_hot_and_cold": False,
        "check7_competitors_analysis_file": False,
        "check8_metrics_snapshot": False,
        "check9_active_campaigns": False,
        "check10_glossary": False,
    }

    # Load inputs
    date_path = os.path.join(input_dir, "current_date.txt")
    date_str = read_text(date_path).strip()
    # Early exit if date missing; many checks depend on it, but we still proceed for others
    # Read inputs used by specific checks
    hero_csv = read_csv_rows(os.path.join(input_dir, "hero_keywords.csv"))
    secondary_csv = read_csv_rows(os.path.join(input_dir, "secondary_keywords.csv"))
    lt_csv = read_csv_rows(os.path.join(input_dir, "long_tail_keywords.csv"))  # not directly used in checks
    ranking_rows = read_csv_rows(os.path.join(input_dir, "ranking_check.csv"))
    competitors_rows = read_csv_rows(os.path.join(input_dir, "competitors.csv"))
    metrics_json = {}
    try:
        metrics_json_path = os.path.join(input_dir, "metrics.json")
        if os.path.isfile(metrics_json_path):
            metrics_json = json.loads(read_text(metrics_json_path) or "{}")
    except Exception:
        metrics_json = {}
    campaigns = parse_yaml_campaigns(os.path.join(input_dir, "campaigns.yaml"))
    promote_list = [ln.strip() for ln in read_lines(os.path.join(input_dir, "promote.txt")) if ln.strip()]
    demote_list = [ln.strip() for ln in read_lines(os.path.join(input_dir, "demote.txt")) if ln.strip()]
    glossary_seed = read_text(os.path.join(input_dir, "glossary_seed.md"))

    # Common paths
    claude_path = os.path.join(output_dir, "CLAUDE.md")
    memory_dir = os.path.join(output_dir, "memory")
    keywords_dir = os.path.join(memory_dir, "keywords")
    competitors_dir = os.path.join(memory_dir, "competitors")
    competitors_analysis_dir = os.path.join(competitors_dir, "analysis-history")
    audits_dir = os.path.join(memory_dir, "audits")
    content_calendar_dir = os.path.join(memory_dir, "content-calendar")
    reports_dir = os.path.join(memory_dir, "reports")

    # Check 1: Hot cache exists, <=150 lines, title string, Last Updated line with date, and exact cross-reference lines
    if os.path.isfile(claude_path):
        claude_lines = read_lines(claude_path)
        claude_content = "\n".join(claude_lines)
        line_count_ok = len(claude_lines) <= 150
        has_title = "Acme Analytics - SEO Memory (Hot Cache)" in claude_content
        last_updated_ok = any(
            (ln.strip().startswith("Last Updated:") and date_str in ln)
            for ln in claude_lines
        )
        cross_ref1 = "Full keyword database: memory/keywords/"
        cross_ref2 = "For project terminology, see: memory/glossary.md"
        has_cross1 = any(ln.strip() == cross_ref1 for ln in claude_lines)
        has_cross2 = any(ln.strip() == cross_ref2 for ln in claude_lines)
        if line_count_ok and has_title and last_updated_ok and has_cross1 and has_cross2:
            checks["check1_hot_cache_structure"] = True

    # Check 2: Directory structure
    dir_ok = True
    required_dirs = [
        memory_dir,
        keywords_dir,
        competitors_dir,
        competitors_analysis_dir,
        os.path.join(audits_dir, "technical"),
        os.path.join(audits_dir, "content"),
        os.path.join(audits_dir, "domain"),
        os.path.join(audits_dir, "backlink"),
        content_calendar_dir,
        os.path.join(content_calendar_dir, "archive"),
        os.path.join(reports_dir, "monthly"),
        os.path.join(reports_dir, "quarterly"),
        os.path.join(reports_dir, "campaign"),
    ]
    for d in required_dirs:
        if not os.path.isdir(d):
            dir_ok = False
            break
    # also require files: glossary.md, keyword files, content-calendar files
    required_files = [
        os.path.join(memory_dir, "glossary.md"),
        os.path.join(keywords_dir, "hero-keywords.md"),
        os.path.join(keywords_dir, "secondary-keywords.md"),
        os.path.join(keywords_dir, "long-tail-keywords.md"),
        os.path.join(keywords_dir, "historical-rankings.csv"),
        os.path.join(competitors_dir, "primary-competitors.md"),
        os.path.join(content_calendar_dir, "active-calendar.md"),
        os.path.join(content_calendar_dir, "published-content.md"),
    ]
    files_ok = all(os.path.isfile(p) for p in required_files)
    if dir_ok and files_ok:
        checks["check2_dir_structure"] = True

    # Check 3: keyword files Last Updated line
    kw_last_updated_ok = True
    for fname in ["hero-keywords.md", "secondary-keywords.md", "long-tail-keywords.md"]:
        pth = os.path.join(keywords_dir, fname)
        if not os.path.isfile(pth):
            kw_last_updated_ok = False
            break
        content_lines = read_lines(pth)
        if not any((ln.strip().startswith("Last Updated:") and date_str in ln) for ln in content_lines):
            kw_last_updated_ok = False
            break
    if kw_last_updated_ok:
        checks["check3_keyword_files_last_updated"] = True

    # Check 4: historical-rankings.csv content for hero keywords
    hist_path = os.path.join(keywords_dir, "historical-rankings.csv")
    hist_ok = False
    if os.path.isfile(hist_path):
        try:
            with open(hist_path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
            if lines:
                header_ok = lines[0].strip() == "date,keyword,current_rank"
                data_rows = []
                for ln in lines[1:]:
                    if not ln.strip():
                        continue
                    parts = [p.strip() for p in ln.split(",")]
                    if len(parts) != 3:
                        continue
                    data_rows.append(parts)
                # Build lookup of (keyword -> list of (date, rank))
                hist_map = {}
                for d, k, r in data_rows:
                    hist_map.setdefault(k, []).append((d, r))
                # Build ranking map
                rank_map = {}
                for r in ranking_rows:
                    k = r.get("keyword", "")
                    cr = r.get("current_rank", "")
                    rank_map[k] = cr
                # Validate each hero keyword that is present in ranking_check
                heroes = [row.get("keyword", "") for row in hero_csv]
                all_present = True
                for hk in heroes:
                    if hk in rank_map:
                        expected_rank = str(rank_map[hk])
                        rows_for_hk = hist_map.get(hk, [])
                        found = any((d == date_str and r == expected_rank) for d, r in rows_for_hk)
                        if not found:
                            all_present = False
                            break
                hist_ok = header_ok and all_present
        except Exception:
            hist_ok = False
    if hist_ok:
        checks["check4_historical_rankings"] = True

    # Check 5: Hot cache tables for hero and secondary keywords and promoted notes
    kw_tables_ok = False
    if os.path.isfile(claude_path):
        claude_lines = read_lines(claude_path)
        # Identify table blocks
        hero_start, hero_end = section_block(claude_lines, "Hero Keywords")
        sec_start, sec_end = section_block(claude_lines, "Secondary Keywords")
        if hero_start != -1 and hero_end != -1 and sec_start != -1 and sec_end != -1:
            hero_block = "\n".join(claude_lines[hero_start:hero_end])
            sec_block = "\n".join(claude_lines[sec_start:sec_end])

            # Build sets of expected keywords considering demote/promote rules
            promote_set = set(promote_list)
            demote_set = set(demote_list)
            # For presence checks: include any keyword not demoted OR promoted (promotion overrides demotion)
            heroes = [row.get("keyword", "") for row in hero_csv]
            seconds = [row.get("keyword", "") for row in secondary_csv]

            def should_include(k: str) -> bool:
                # If in promote list, must appear regardless
                if k in promote_set:
                    return True
                # If in demote and not in promote, then do not require
                if k in demote_set:
                    return False
                return True

            heroes_required = [k for k in heroes if should_include(k)]
            seconds_required = [k for k in seconds if should_include(k)]

            heroes_found = all(k in hero_block for k in heroes_required)
            seconds_found = all(k in sec_block for k in seconds_required)

            # Promoted keywords must appear in either table block and include note "(Promoted YYYY-MM-DD"
            promoted_ok = True
            for k in promote_set:
                # Some promoted keywords might come from long tail or secondary; ensure appears in either block
                in_hero = k in hero_block
                in_sec = k in sec_block
                if not (in_hero or in_sec):
                    promoted_ok = False
                    break
                # Check promoted note
                note_sub = f"(Promoted {date_str}"
                # Find in the relevant block lines
                blocks = []
                if in_hero:
                    blocks.append(hero_block)
                if in_sec:
                    blocks.append(sec_block)
                has_note = any((k in blk and note_sub in blk) for blk in blocks)
                if not has_note:
                    promoted_ok = False
                    break

            if heroes_found and seconds_found and promoted_ok:
                kw_tables_ok = True
    if kw_tables_ok:
        checks["check5_hot_cache_keywords_and_promotions"] = True

    # Check 6: Competitors presence in hot cache and cold storage list
    comp_ok = False
    if os.path.isfile(claude_path) and os.path.isfile(os.path.join(competitors_dir, "primary-competitors.md")):
        claude_lines = read_lines(claude_path)
        cold_lines = read_lines(os.path.join(competitors_dir, "primary-competitors.md"))
        # For each competitor, require presence
        all_hot = True
        all_cold = True
        for row in competitors_rows:
            domain = row.get("domain", "").strip()
            da = str(row.get("da", "")).strip()
            # Hot cache: a line containing domain and "(DA: da)"
            hot_found = any((domain in ln and f"(DA: {da})" in ln) for ln in claude_lines)
            if not hot_found:
                all_hot = False
                break
            cold_found = any((domain in ln and da in ln) for ln in cold_lines)
            if not cold_found:
                all_cold = False
                break
        if all_hot and all_cold:
            comp_ok = True
    if comp_ok:
        checks["check6_competitors_in_hot_and_cold"] = True

    # Check 7: analysis-history/YYYY-MM-DD-analysis.md exists and contains at least one position_note
    analysis_ok = False
    analysis_path = os.path.join(competitors_analysis_dir, f"{date_str}-analysis.md")
    if os.path.isfile(analysis_path):
        analysis_content = read_text(analysis_path)
        # At least one position_note present
        notes = [row.get("position_note", "") for row in competitors_rows if row.get("position_note", "")]
        contains_note = any((note and note in analysis_content) for note in notes)
        if contains_note:
            analysis_ok = True
    if analysis_ok:
        checks["check7_competitors_analysis_file"] = True

    # Check 8: Key Metrics Snapshot present and Last Metrics Update date
    metrics_ok = False
    if os.path.isfile(claude_path) and metrics_json:
        claude_lines = read_lines(claude_path)
        last_metrics_update_ok = any(("Last Metrics Update" in ln and date_str in ln) for ln in claude_lines)
        # For every metric key, ensure a line contains the key and both current and previous values
        all_metrics_present = True
        for metric_name, vals in metrics_json.items():
            cur = vals.get("current", None)
            prev = vals.get("previous", None)
            # require both to be non-None and present in a single line with the metric name
            if cur is None or prev is None:
                all_metrics_present = False
                break
            if not contains_metric_row(claude_lines, metric_name, cur, prev):
                all_metrics_present = False
                break
        if last_metrics_update_ok and all_metrics_present:
            metrics_ok = True
    if metrics_ok:
        checks["check8_metrics_snapshot"] = True

    # Check 9: Active Campaigns entries and progress
    campaigns_ok = False
    if os.path.isfile(claude_path) and campaigns:
        claude_lines = read_lines(claude_path)
        all_camps_present = True
        for c in campaigns:
            name = c.get("name", "")
            progress = str(c.get("progress", "")).strip()
            if not name:
                all_camps_present = False
                break
            # name present
            name_found = any(name in ln for ln in claude_lines)
            progress_found = any(f"Progress: {progress}%" in ln for ln in claude_lines)
            if not (name_found and progress_found):
                all_camps_present = False
                break
        if all_camps_present:
            campaigns_ok = True
    if campaigns_ok:
        checks["check9_active_campaigns"] = True

    # Check 10: Glossary exists, title, last updated, includes seed content, and custom segments names
    glossary_ok = False
    glossary_path = os.path.join(memory_dir, "glossary.md")
    if os.path.isfile(glossary_path):
        g_lines = read_lines(glossary_path)
        g_content = "\n".join(g_lines)
        title_ok = (len(g_lines) >= 1 and "Acme Analytics - SEO Glossary" in g_lines[0])
        last_updated_ok = any((ln.strip().startswith("Last Updated:") and date_str in ln) for ln in g_lines)
        # includes some content from seed verbatim: check any non-empty line from seed appears
        seed_included = False
        if glossary_seed:
            for ln in glossary_seed.splitlines():
                lns = ln.strip()
                if lns and lns in g_content:
                    seed_included = True
                    break
        segments_ok = all(seg in g_content for seg in ["Hero KWs", "Quick Wins", "Brand Defense"])
        if title_ok and last_updated_ok and seed_included and segments_ok:
            glossary_ok = True
    if glossary_ok:
        checks["check10_glossary"] = True

    # Compute reward: average of checks
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total if total > 0 else 0.0

    # Ensure no-op baseline: if output dir missing or empty, reward should be 0.0 implicitly by checks failing
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()