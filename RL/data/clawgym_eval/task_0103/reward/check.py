import sys
import json
import csv
import re
from html import unescape
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def _load_csv_dicts_safe(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return rows, reader.fieldnames
    except Exception:
        return None, None


def _normalize_whitespace(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _html_to_text_normalized(html_content: str) -> str:
    # Remove script and style content
    content = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html_content)
    # Remove all tags
    content = re.sub(r"(?is)<[^>]+>", " ", content)
    # Unescape HTML entities
    content = unescape(content)
    # Normalize whitespace and lower-case
    return _normalize_whitespace(content).lower()


def _string_normalized(s: str) -> str:
    return _normalize_whitespace(unescape(s)).lower()


def _approx_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _parse_config(workspace: Path) -> Tuple[Optional[List[str]], Optional[int]]:
    cfg_path = workspace / "input" / "config.json"
    cfg = _load_json_safe(cfg_path)
    if not isinstance(cfg, dict):
        return None, None
    selected = cfg.get("selected_tags")
    top_n = cfg.get("top_n")
    if not isinstance(selected, list) or not all(isinstance(t, str) for t in selected):
        return None, None
    if not isinstance(top_n, int) or top_n <= 0:
        return None, None
    return selected, top_n


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "raw_html_mdn_en_us": 0.0,
        "elements_all_json_valid": 0.0,
        "elements_all_summaries_in_html": 0.0,
        "filtered_csv_valid_and_consistent": 0.0,
        "stats_json_correct": 0.0,
        "topn_md_matches_stats": 0.0,
        "topn_stats_consistent_with_csv": 0.0,
    }

    # Paths
    raw_html_path = workspace / "output" / "raw" / "elements_reference.html"
    elements_json_path = workspace / "output" / "data" / "elements_all.json"
    filtered_csv_path = workspace / "output" / "data" / "elements_filtered.csv"
    stats_json_path = workspace / "output" / "reports" / "stats.json"
    topn_md_path = workspace / "output" / "reports" / "topN.md"

    # Config
    selected_tags, top_n = _parse_config(workspace)

    # Check raw HTML presence and MDN en-US characteristics
    raw_html_text = _read_text_safe(raw_html_path)
    if isinstance(raw_html_text, str):
        cond_domain = "developer.mozilla.org" in raw_html_text
        cond_locale = ('lang="en-US"' in raw_html_text) or ("/en-US/" in raw_html_text)
        cond_title = re.search(r"HTML elements reference", raw_html_text, flags=re.IGNORECASE) is not None
        if cond_domain and cond_locale and cond_title:
            scores["raw_html_mdn_en_us"] = 1.0

    # Load elements_all.json and validate structure
    elements_data = _load_json_safe(elements_json_path)
    elements_valid = False
    elements_list: List[Dict[str, Any]] = []
    tag_to_summary: Dict[str, str] = {}
    if isinstance(elements_data, list) and len(elements_data) > 0:
        ok = True
        for item in elements_data:
            if not isinstance(item, dict):
                ok = False
                break
            tag = item.get("tag")
            summary = item.get("summary")
            if not isinstance(tag, str) or not isinstance(summary, str):
                ok = False
                break
            if len(tag.strip()) == 0 or len(summary.strip()) == 0:
                ok = False
                break
            elements_list.append({"tag": tag, "summary": summary})
            tag_to_summary[tag] = summary
        if ok:
            elements_valid = True
            scores["elements_all_json_valid"] = 1.0

    # Cross-check that summaries appear in the raw HTML (derived from saved page)
    if elements_valid and isinstance(raw_html_text, str):
        html_norm = _html_to_text_normalized(raw_html_text)
        all_match = True
        for item in elements_list:
            summ_norm = _string_normalized(item["summary"])
            if summ_norm and summ_norm not in html_norm:
                all_match = False
                break
        if all_match:
            scores["elements_all_summaries_in_html"] = 1.0

    # Validate filtered CSV against config and elements_all.json
    filtered_rows, filtered_headers = _load_csv_dicts_safe(filtered_csv_path)
    csv_ok = False
    if elements_valid and isinstance(filtered_rows, list) and isinstance(filtered_headers, list) and selected_tags is not None:
        # Check exact headers order and names
        if filtered_headers == ["tag", "summary_length"]:
            # Build expected tag set (intersection)
            present_selected = [t for t in selected_tags if t in tag_to_summary]
            expected_set = set(present_selected)
            # Parse CSV content
            csv_set = set()
            ok_rows = True
            for row in filtered_rows:
                if set(row.keys()) != set(filtered_headers):
                    ok_rows = False
                    break
                tag = row.get("tag")
                slen_str = row.get("summary_length")
                if not isinstance(tag, str) or tag not in selected_tags:
                    ok_rows = False
                    break
                try:
                    slen_val = int(slen_str)
                except Exception:
                    ok_rows = False
                    break
                # Must match summary length from elements_all.json for this tag
                if tag not in tag_to_summary:
                    ok_rows = False
                    break
                expected_len = len(tag_to_summary[tag])
                if slen_val != expected_len:
                    ok_rows = False
                    break
                csv_set.add(tag)
            if ok_rows and csv_set == expected_set:
                csv_ok = True
                scores["filtered_csv_valid_and_consistent"] = 1.0

    # Validate stats.json correctness against recomputation
    stats = _load_json_safe(stats_json_path)
    stats_ok = False
    if elements_valid and isinstance(stats, dict) and selected_tags is not None and isinstance(top_n, int):
        # Compute expected metrics
        # total_elements
        total_elements_exp = len(elements_list)
        # counts_by_initial_letter
        counts_exp: Dict[str, int] = {}
        for item in elements_list:
            tag = item["tag"]
            if not tag:
                continue
            initial = tag[0].lower()
            counts_exp[initial] = counts_exp.get(initial, 0) + 1
        # average_summary_length_all
        lengths = [len(item["summary"]) for item in elements_list]
        avg_len_exp = (sum(lengths) / len(lengths)) if lengths else 0.0
        # filtered block
        present_tags = [t for t in selected_tags if t in tag_to_summary]
        total_filtered_exp = len(present_tags)
        coverage_rate_exp = (total_filtered_exp / len(selected_tags)) if selected_tags else 0.0
        missing_exp = [t for t in selected_tags if t not in tag_to_summary]
        # top_n_by_summary_length among present_tags
        tagged_lengths = [{"tag": t, "summary_length": len(tag_to_summary[t])} for t in present_tags]
        tagged_lengths_sorted = sorted(tagged_lengths, key=lambda x: (-x["summary_length"], x["tag"]))
        topn_exp = tagged_lengths_sorted[:top_n]

        # Extract stats fields
        try:
            total_elements_act = stats.get("total_elements")
            counts_act = stats.get("counts_by_initial_letter")
            avg_len_act = stats.get("average_summary_length_all")
            filtered_act = stats.get("filtered")
            ok = True
            if not isinstance(total_elements_act, int) or total_elements_act != total_elements_exp:
                ok = False
            if not isinstance(counts_act, dict) or {str(k): int(v) for k, v in counts_act.items()} != {k: v for k, v in counts_exp.items()}:
                ok = False
            if not (isinstance(avg_len_act, (int, float)) and _approx_equal(float(avg_len_act), float(avg_len_exp))):
                ok = False
            if not isinstance(filtered_act, dict):
                ok = False
            else:
                tf_act = filtered_act.get("total_filtered")
                cr_act = filtered_act.get("coverage_rate")
                miss_act = filtered_act.get("missing_selected_tags")
                topn_act = filtered_act.get("top_n_by_summary_length")
                if not isinstance(tf_act, int) or tf_act != total_filtered_exp:
                    ok = False
                if not isinstance(cr_act, (int, float)) or not _approx_equal(float(cr_act), float(coverage_rate_exp)):
                    ok = False
                if not isinstance(miss_act, list) or set(miss_act) != set(missing_exp):
                    ok = False
                if not isinstance(topn_act, list):
                    ok = False
                else:
                    # Require exact length equal to top_n from config
                    if len(topn_act) != len(topn_exp):
                        ok = False
                    else:
                        # Compare list of dicts
                        for exp_item, act_item in zip(topn_exp, topn_act):
                            if not isinstance(act_item, dict):
                                ok = False
                                break
                            if act_item.get("tag") != exp_item.get("tag"):
                                ok = False
                                break
                            if act_item.get("summary_length") != exp_item.get("summary_length"):
                                ok = False
                                break
            if ok:
                stats_ok = True
                scores["stats_json_correct"] = 1.0
        except Exception:
            stats_ok = False

    # Validate topN.md corresponds to stats.filtered.top_n_by_summary_length
    if stats_ok:
        md_text = _read_text_safe(topn_md_path)
        filtered_block = stats.get("filtered", {}) if isinstance(stats, dict) else {}
        topn_list = filtered_block.get("top_n_by_summary_length") if isinstance(filtered_block, dict) else None
        if isinstance(md_text, str) and isinstance(topn_list, list):
            lines = md_text.splitlines()
            # Build expected sequence of (rank, tag, summary_length)
            expected_seq = []
            for idx, item in enumerate(topn_list, start=1):
                if isinstance(item, dict) and "tag" in item and "summary_length" in item:
                    expected_seq.append((idx, str(item["tag"]), int(item["summary_length"])))
                else:
                    expected_seq = []
                    break
            if expected_seq:
                ok = True
                line_index = 0
                for rank, tag, slen in expected_seq:
                    # Find next line starting with the rank and containing tag and slen
                    found = False
                    rank_pattern = re.compile(rf"^\s*{rank}[\.\)]?\s*")
                    tag_pattern = re.compile(rf"\b{re.escape(tag)}\b")
                    slen_pattern = re.compile(rf"\b{slen}\b")
                    while line_index < len(lines):
                        line = lines[line_index]
                        line_index += 1
                        if rank_pattern.search(line):
                            # Check same line contains tag and slen
                            if tag_pattern.search(line) and slen_pattern.search(line):
                                found = True
                                break
                            else:
                                # If rank matched but not tag/length, fail
                                found = False
                                break
                    if not found:
                        ok = False
                        break
                if ok:
                    scores["topn_md_matches_stats"] = 1.0

    # Validate that stats.top_n_by_summary_length is consistent with filtered CSV
    if stats_ok and csv_ok:
        filtered_block = stats.get("filtered", {}) if isinstance(stats, dict) else {}
        topn_list = filtered_block.get("top_n_by_summary_length") if isinstance(filtered_block, dict) else None
        if isinstance(topn_list, list):
            # Compute ranking from CSV
            try:
                csv_items = []
                for row in filtered_rows:  # type: ignore
                    tag = row["tag"]
                    slen = int(row["summary_length"])
                    csv_items.append({"tag": tag, "summary_length": slen})
                csv_sorted = sorted(csv_items, key=lambda x: (-x["summary_length"], x["tag"]))
                csv_topn = csv_sorted[:top_n]  # type: ignore
                # Compare to stats topn_list
                ok = True
                if len(csv_topn) != len(topn_list):
                    ok = False
                else:
                    for exp_item, act_item in zip(csv_topn, topn_list):
                        if not isinstance(act_item, dict):
                            ok = False
                            break
                        if act_item.get("tag") != exp_item.get("tag") or act_item.get("summary_length") != exp_item.get("summary_length"):
                            ok = False
                            break
                if ok:
                    scores["topn_stats_consistent_with_csv"] = 1.0
            except Exception:
                pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()