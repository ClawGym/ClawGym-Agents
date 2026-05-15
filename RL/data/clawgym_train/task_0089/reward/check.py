import sys
import json
import csv
import re
import os
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any


def _read_text_safe(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(p: Path) -> Optional[Any]:
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv_safe(p: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with p.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = [row for row in reader]
            return header, rows
    except Exception:
        return None, None


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[A-Za-z]+", text.lower())


def _parse_yaml_front_matter(md_text: str) -> Tuple[Dict[str, str], str]:
    lines = md_text.splitlines()
    fm: Dict[str, str] = {}
    body_lines: List[str] = []
    if not lines:
        return fm, ""
    i = 0
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    if i < len(lines) and lines[i].strip() == "---":
        i += 1
        while i < len(lines) and lines[i].strip() != "---":
            line = lines[i]
            if ":" in line:
                key, val = line.split(":", 1)
                key = key.strip()
                val = val.strip()
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                fm[key] = val
            i += 1
        if i < len(lines) and lines[i].strip() == "---":
            i += 1
        body_lines = lines[i:]
    else:
        body_lines = lines[i:]
    body = "\n".join(body_lines).strip()
    return fm, body


def _collect_posts(workspace: Path) -> List[Path]:
    return sorted((workspace / "content" / "posts").glob("*.md"))


def _load_theme_terms(workspace: Path) -> Optional[List[Dict[str, str]]]:
    p = workspace / "input" / "themes.csv"
    header, rows = _load_csv_safe(p)
    if header is None or rows is None:
        return None
    if [h.strip() for h in header] != ["term", "category"]:
        cols = set(h.strip() for h in header)
        if not ({"term", "category"} <= cols):
            return None
    terms = []
    for r in rows:
        term = (r.get("term") or "").strip()
        category = (r.get("category") or "").strip()
        if not term or not category:
            return None
        terms.append({"term": term, "category": category})
    return terms


def _compute_post_metrics_for_file(p: Path, terms: List[str]) -> Optional[Dict[str, Any]]:
    txt = _read_text_safe(p)
    if txt is None:
        return None
    fm, body = _parse_yaml_front_matter(txt)
    title = fm.get("title")
    date = fm.get("date")
    if title is None or date is None:
        return None
    tokens = _tokenize(body)
    word_count = len(tokens)
    counts: Dict[str, int] = {t: 0 for t in terms}
    for tok in tokens:
        if tok in counts:
            counts[tok] += 1
    slug = p.stem
    m: Dict[str, Any] = {
        "slug": slug,
        "title": title,
        "date": date,
        "word_count": word_count,
    }
    for t in terms:
        m[t] = counts[t]
    return m


def _compute_all_post_metrics(workspace: Path, required_terms: List[str]) -> Optional[List[Dict[str, Any]]]:
    posts = _collect_posts(workspace)
    metrics: List[Dict[str, Any]] = []
    for p in posts:
        m = _compute_post_metrics_for_file(p, required_terms)
        if m is None:
            return None
        metrics.append(m)
    return metrics


def _median(values: List[float]) -> float:
    n = len(values)
    if n == 0:
        return 0.0
    s = sorted(values)
    mid = n // 2
    if n % 2 == 1:
        return float(s[mid])
    else:
        return (float(s[mid - 1]) + float(s[mid])) / 2.0


def _float_equal(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol


def _parse_release_yaml(workspace: Path) -> Optional[Dict[str, str]]:
    p = workspace / "input" / "release.yaml"
    txt = _read_text_safe(p)
    if txt is None:
        return None
    fm: Dict[str, str] = {}
    for line in txt.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            k = k.strip()
            v = v.strip()
            if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                v = v[1:-1]
            fm[k] = v
    if "release_version" in fm and "meeting_date" in fm:
        return fm
    return None


def _extract_section(text: str, header: str) -> Optional[str]:
    lines = text.splitlines()
    start_idx = None
    header_line = f"## {header}"
    for i, line in enumerate(lines):
        if line.strip() == header_line:
            start_idx = i + 1
            break
    if start_idx is None:
        return None
    collected: List[str] = []
    for j in range(start_idx, len(lines)):
        if lines[j].startswith("## "):
            break
        collected.append(lines[j])
    return "\n".join(collected).strip()


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "runner_script_exists": 0.0,
        "runner_script_executable_and_shebang": 0.0,
        "runner_script_exit_on_error_configured": 0.0,
        "macbeth_file_present_and_validated_title": 0.0,
        "macbeth_file_project_gutenberg_indicator": 0.0,
        "post_metrics_csv_present_and_columns": 0.0,
        "post_metrics_csv_rows_match_posts": 0.0,
        "post_metrics_word_counts_correct": 0.0,
        "post_metrics_theme_counts_correct": 0.0,
        "aggregate_json_present_and_keys": 0.0,
        "aggregate_totals_correct": 0.0,
        "aggregate_term_totals_correct": 0.0,
        "macbeth_theme_counts_csv_present_and_columns": 0.0,
        "macbeth_theme_counts_correct": 0.0,
        "meeting_notes_present": 0.0,
        "meeting_notes_release_fields_filled": 0.0,
        "meeting_notes_summary_metrics_present": 0.0,
        "meeting_notes_theme_table_coverage": 0.0,
        "meeting_notes_gap_terms_listed": 0.0,
        "meeting_notes_action_items_count": 0.0,
        "meeting_notes_gap_action_included": 0.0,
    }

    runner = workspace / "scripts" / "release_prep.sh"
    if runner.exists() and runner.is_file():
        scores["runner_script_exists"] = 1.0
        content = _read_text_safe(runner) or ""
        shebang_ok = content.startswith("#!")
        try:
            is_exec = os.access(runner, os.X_OK)
        except Exception:
            is_exec = False
        if is_exec and shebang_ok:
            scores["runner_script_executable_and_shebang"] = 1.0
        exit_on_error = False
        for line in content.splitlines():
            line_stripped = line.strip()
            if line_stripped.startswith("set "):
                if re.search(r"\b-+.*e", line_stripped):
                    exit_on_error = True
                if "errexit" in line_stripped:
                    exit_on_error = True
        if exit_on_error:
            scores["runner_script_exit_on_error_configured"] = 1.0

    required_terms_order = ["blood", "fate", "honor", "duty", "command", "soldier"]

    macbeth_path = workspace / "cache" / "macbeth.txt"
    macbeth_text = _read_text_safe(macbeth_path)
    if macbeth_text is not None and macbeth_text.strip():
        if "the tragedy of macbeth" in macbeth_text.lower():
            scores["macbeth_file_present_and_validated_title"] = 1.0
        if "project gutenberg" in macbeth_text.lower():
            scores["macbeth_file_project_gutenberg_indicator"] = 1.0

    post_metrics_csv = workspace / "dist" / "stats" / "post_metrics.csv"
    header, rows = _load_csv_safe(post_metrics_csv)
    if header is not None and rows is not None:
        expected_header = ["slug", "title", "date", "word_count"] + required_terms_order
        if [h.strip() for h in header] == expected_header:
            scores["post_metrics_csv_present_and_columns"] = 1.0

        csv_slugs = [r.get("slug", "") for r in rows]
        posts = _collect_posts(workspace)
        expected_slugs = [p.stem for p in posts]
        if csv_slugs and sorted(csv_slugs) == sorted(expected_slugs) and len(csv_slugs) == len(expected_slugs):
            scores["post_metrics_csv_rows_match_posts"] = 1.0

        theme_terms_spec = _load_theme_terms(workspace)
        terms_to_use = required_terms_order
        computed_metrics = _compute_all_post_metrics(workspace, terms_to_use)
        if computed_metrics is not None:
            expected_by_slug = {m["slug"]: m for m in computed_metrics}

            wc_ok = True
            tc_ok = True
            for r in rows:
                slug = r.get("slug", "")
                exp = expected_by_slug.get(slug)
                if exp is None:
                    wc_ok = False
                    tc_ok = False
                    break
                try:
                    wc_val = int(str(r.get("word_count", "")).strip())
                except Exception:
                    wc_val = None
                if wc_val is None or wc_val != int(exp["word_count"]):
                    wc_ok = False
                for t in required_terms_order:
                    try:
                        cnt_val = int(str(r.get(t, "")).strip())
                    except Exception:
                        cnt_val = None
                    if cnt_val is None or cnt_val != int(exp[t]):
                        tc_ok = False
            if wc_ok:
                scores["post_metrics_word_counts_correct"] = 1.0
            if tc_ok:
                scores["post_metrics_theme_counts_correct"] = 1.0

            aggregate_json = workspace / "dist" / "stats" / "aggregate.json"
            agg = _load_json_safe(aggregate_json)
            if isinstance(agg, dict):
                if (
                    "total_posts" in agg
                    and "mean_post_word_count" in agg
                    and "median_post_word_count" in agg
                    and "total_counts_per_term" in agg
                    and isinstance(agg["total_counts_per_term"], dict)
                ):
                    scores["aggregate_json_present_and_keys"] = 1.0

                    wc_list = [int(m["word_count"]) for m in computed_metrics]
                    total_posts = len(computed_metrics)
                    mean_wc = float(sum(wc_list) / total_posts) if total_posts > 0 else 0.0
                    median_wc = _median([float(x) for x in wc_list])
                    totals_per_term: Dict[str, int] = {t: 0 for t in required_terms_order}
                    for m in computed_metrics:
                        for t in required_terms_order:
                            totals_per_term[t] += int(m[t])

                    totals_ok = int(agg.get("total_posts", -1)) == total_posts
                    mean_ok = False
                    try:
                        mean_val = float(agg.get("mean_post_word_count"))
                        mean_ok = _float_equal(mean_val, mean_wc, tol=1e-6)
                    except Exception:
                        mean_ok = False
                    median_ok = False
                    try:
                        median_val = float(agg.get("median_post_word_count"))
                        median_ok = _float_equal(median_val, median_wc, tol=1e-6)
                    except Exception:
                        median_ok = False

                    if totals_ok and mean_ok and median_ok:
                        scores["aggregate_totals_correct"] = 1.0

                    term_totals_ok = True
                    agg_terms_map = agg.get("total_counts_per_term", {})
                    if set(agg_terms_map.keys()) != set(required_terms_order):
                        term_totals_ok = False
                    else:
                        for t in required_terms_order:
                            try:
                                if int(agg_terms_map.get(t)) != int(totals_per_term[t]):
                                    term_totals_ok = False
                                    break
                            except Exception:
                                term_totals_ok = False
                                break
                    if term_totals_ok:
                        scores["aggregate_term_totals_correct"] = 1.0

            macbeth_theme_csv = workspace / "dist" / "macbeth_theme_counts.csv"
            m_header, m_rows = _load_csv_safe(macbeth_theme_csv)
            if m_header is not None and m_rows is not None:
                if [h.strip() for h in m_header] == ["term", "category", "macbeth_count"]:
                    scores["macbeth_theme_counts_csv_present_and_columns"] = 1.0

                if macbeth_text is not None:
                    tokens = _tokenize(macbeth_text)
                    token_counts: Dict[str, int] = {}
                    for t in required_terms_order:
                        token_counts[t] = sum(1 for tok in tokens if tok == t)
                    csv_map: Dict[str, Tuple[str, int]] = {}
                    all_rows_valid = True
                    for r in m_rows:
                        term = (r.get("term") or "").strip()
                        category = (r.get("category") or "").strip()
                        try:
                            cnt = int(str(r.get("macbeth_count", "")).strip())
                        except Exception:
                            all_rows_valid = False
                            break
                        if not term:
                            all_rows_valid = False
                            break
                        csv_map[term] = (category, cnt)
                    cats_from_theme = {}
                    theme_terms_spec = _load_theme_terms(workspace)
                    if theme_terms_spec is not None:
                        cats_from_theme = {d["term"]: d["category"] for d in theme_terms_spec}

                    if all_rows_valid:
                        ok = True
                        for t in required_terms_order:
                            if t not in csv_map:
                                ok = False
                                break
                            cat, cnt = csv_map[t]
                            if cnt != token_counts[t]:
                                ok = False
                                break
                            if t in cats_from_theme:
                                if cat != cats_from_theme[t]:
                                    ok = False
                                    break
                        if ok:
                            scores["macbeth_theme_counts_correct"] = 1.0

            notes_path = workspace / "dist" / "meeting_notes.md"
            notes_text = _read_text_safe(notes_path)
            if notes_text is not None and notes_text.strip():
                scores["meeting_notes_present"] = 1.0

                release_info = _parse_release_yaml(workspace)
                release_ok = False
                if release_info is not None:
                    rv = release_info.get("release_version", "")
                    md = release_info.get("meeting_date", "")
                    if f"Release: {rv}" in notes_text and f"Meeting Date: {md}" in notes_text:
                        release_ok = True
                if release_ok:
                    scores["meeting_notes_release_fields_filled"] = 1.0

                summary_sec = _extract_section(notes_text, "Summary metrics")
                summary_ok = False
                if summary_sec is not None:
                    labels_present = all(lbl in summary_sec for lbl in ["total_posts", "mean_post_word_count", "median_post_word_count"])
                    wc_list = [int(m["word_count"]) for m in computed_metrics]
                    total_posts = len(computed_metrics)
                    mean_wc = float(sum(wc_list) / total_posts) if total_posts > 0 else 0.0
                    median_wc = _median([float(x) for x in wc_list])
                    def _num_in_text(val: float, text: str) -> bool:
                        candidates = {str(val), f"{val:.6f}".rstrip("0").rstrip("."), f"{val:.3f}".rstrip("0").rstrip(".")}
                        return any(c in text for c in candidates)
                    values_present = (
                        str(total_posts) in summary_sec
                        and _num_in_text(mean_wc, summary_sec)
                        and _num_in_text(median_wc, summary_sec)
                    )
                    if labels_present or values_present:
                        summary_ok = True
                if summary_ok:
                    scores["meeting_notes_summary_metrics_present"] = 1.0

                totals_per_term: Dict[str, int] = {t: 0 for t in required_terms_order}
                for m in computed_metrics:
                    for t in required_terms_order:
                        totals_per_term[t] += int(m[t])
                tokens_macbeth = _tokenize(macbeth_text or "")
                macbeth_counts: Dict[str, int] = {t: sum(1 for tok in tokens_macbeth if tok == t) for t in required_terms_order}
                coverage_ok = True
                lines = notes_text.splitlines()
                for t in required_terms_order:
                    pt = totals_per_term[t]
                    mc = macbeth_counts[t]
                    found_line = False
                    for line in lines:
                        if t in line and str(pt) in line and str(mc) in line:
                            found_line = True
                            break
                    if not found_line:
                        coverage_ok = False
                        break
                if coverage_ok:
                    scores["meeting_notes_theme_table_coverage"] = 1.0

                gap_terms = [t for t in required_terms_order if macbeth_counts[t] > 0 and totals_per_term[t] == 0]
                gaps_sec = _extract_section(notes_text, "Theme coverage gaps and observations")
                gaps_ok = False
                if gaps_sec is not None:
                    if not gap_terms:
                        gaps_ok = True
                    else:
                        gaps_ok = all(t in gaps_sec for t in gap_terms)
                if gaps_ok:
                    scores["meeting_notes_gap_terms_listed"] = 1.0

                action_sec = _extract_section(notes_text, "Action items")
                action_count_ok = False
                gap_action_ok = False
                if action_sec is not None:
                    bullets = [ln for ln in action_sec.splitlines() if ln.strip().startswith("- ") or ln.strip().startswith("* ")]
                    if len(bullets) >= 3:
                        action_count_ok = True
                    if not gap_terms:
                        gap_action_ok = True
                    else:
                        gap_action_ok = any(any(t in b for t in gap_terms) for b in bullets)
                if action_count_ok:
                    scores["meeting_notes_action_items_count"] = 1.0
                if gap_action_ok:
                    scores["meeting_notes_gap_action_included"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()