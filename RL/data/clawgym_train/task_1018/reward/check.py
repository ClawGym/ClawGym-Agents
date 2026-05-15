import json
import csv
import sys
import re
from pathlib import Path
from typing import Optional, Tuple, List, Dict


def read_text(path: Path) -> Optional[str]:
    try:
        if not path.exists() or not path.is_file():
            return None
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None


def load_json(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    try:
        if not path.exists() or not path.is_file():
            return None, "missing"
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data, None
    except Exception as e:
        return None, str(e)


def parse_csv_dicts(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        if not path.exists() or not path.is_file():
            return None, None
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = list(reader)
            return header, rows
    except Exception:
        return None, None


def is_lowercase_text(text: str) -> bool:
    for ch in text:
        if ch.isalpha() and ch.upper() == ch and ch.lower() != ch:
            return False
    return True


def looks_stripped_text(text: str) -> bool:
    low = text.lower()
    unwanted = ["<html", "</html", "<script", "</script", "<style", "</style", "<head", "</head", "<body", "</body"]
    for u in unwanted:
        if u in low:
            return False
    # Detect HTML-like tags
    if re.search(r"<\s*[a-zA-Z/!][^>]*>", text):
        return False
    return True


def baseline_load(workspace: Path) -> Tuple[Optional[dict], Optional[str]]:
    baseline_path = workspace / "input" / "baseline_tasks.json"
    return load_json(baseline_path)


def unique_keywords_from_baseline(baseline: dict) -> List[str]:
    kws: List[str] = []
    for task in baseline.get("tasks", []):
        for kw in task.get("keywords", []):
            if kw not in kws:
                kws.append(kw)
    return kws


def compute_counts_from_texts(workspace: Path, domains: List[str], keywords: List[str]) -> Tuple[Optional[Dict[str, Dict[str, int]]], Optional[str]]:
    counts: Dict[str, Dict[str, int]] = {}
    for domain in domains:
        txt_path = workspace / "web" / "text" / f"{domain}.txt"
        text = read_text(txt_path)
        if text is None:
            return None, f"missing_text_{domain}"
        lowered = text.lower()
        domain_counts: Dict[str, int] = {}
        for kw in keywords:
            domain_counts[kw] = lowered.count(kw.lower())
        counts[domain] = domain_counts
    return counts, None


def compute_task_aggregates(baseline: dict, counts_by_domain: Dict[str, Dict[str, int]], domains: List[str]) -> Dict[str, Dict]:
    result: Dict[str, Dict] = {}
    for task in baseline.get("tasks", []):
        tid = task.get("id")
        tname = task.get("name")
        freq = task.get("frequency")
        tkeywords = task.get("keywords", [])
        total = 0
        domains_hits_set = set()
        for dom in domains:
            dom_sum = 0
            for kw in tkeywords:
                dom_sum += counts_by_domain.get(dom, {}).get(kw, 0)
            if dom_sum > 0:
                domains_hits_set.add(dom)
            total += dom_sum
        result[tid] = {
            "task_name": tname,
            "frequency": freq,
            "total_matches": total,
            "domains_with_hits": domains_hits_set,
        }
    return result


def parse_domains_with_hits(value: str) -> List[str]:
    val = value.strip()
    if not val:
        return []
    parts = [p.strip() for p in val.split(";") if p.strip()]
    return parts


def check_sections_order(report_text: str, sections: List[str]) -> bool:
    idxs = []
    for sec in sections:
        idx = report_text.find(sec)
        if idx == -1:
            return False
        idxs.append(idx)
    return all(idxs[i] < idxs[i + 1] for i in range(len(idxs) - 1))


def extract_section(report_text: str, section_title: str, next_title: Optional[str]) -> str:
    start = report_text.find(section_title)
    if start == -1:
        return ""
    start += len(section_title)
    if next_title is None:
        return report_text[start:]
    end = report_text.find(next_title, start)
    if end == -1:
        end = len(report_text)
    return report_text[start:end]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "raw_html_files_ok": 0.0,
        "text_files_normalized": 0.0,
        "keyword_counts_json_valid": 0.0,
        "task_scores_csv_valid": 0.0,
        "status_report_valid": 0.0,
        "run_pipeline_script_exists": 0.0,
        "run_pipeline_script_covers_paths": 0.0,
    }

    domains = ["epa.gov", "energy.gov", "ready.gov"]

    # Check raw HTML files existence and non-empty
    raw_checks = []
    for dom in domains:
        p = workspace / "web" / "raw" / f"{dom}.html"
        content = read_text(p)
        raw_checks.append(content is not None and len(content.strip()) > 0)
    if raw_checks:
        scores["raw_html_files_ok"] = sum(1.0 for b in raw_checks if b) / len(raw_checks)
    else:
        scores["raw_html_files_ok"] = 0.0

    # Check text files: existence, non-empty, lowercased, stripped of tags
    text_checks = []
    for dom in domains:
        p = workspace / "web" / "text" / f"{dom}.txt"
        content = read_text(p)
        if content is None or len(content.strip()) == 0:
            text_checks.append(False)
            continue
        if not is_lowercase_text(content):
            text_checks.append(False)
            continue
        if not looks_stripped_text(content):
            text_checks.append(False)
            continue
        text_checks.append(True)
    if text_checks:
        scores["text_files_normalized"] = sum(1.0 for b in text_checks if b) / len(text_checks)
    else:
        scores["text_files_normalized"] = 0.0

    # Load baseline
    baseline, baseline_err = baseline_load(workspace)
    baseline_valid = baseline is not None and isinstance(baseline, dict) and isinstance(baseline.get("tasks"), list)

    # Validate analytics/keyword_counts.json structure and values
    keyword_counts_path = workspace / "analytics" / "keyword_counts.json"
    kc_data, kc_err = load_json(keyword_counts_path)
    keyword_counts_ok = False
    counts_by_domain_expected: Optional[Dict[str, Dict[str, int]]] = None
    if baseline_valid and kc_data is not None and isinstance(kc_data, dict):
        # Structure check: domains present
        domains_present = all(dom in kc_data for dom in domains)
        # Keys check: each domain map keys equal to baseline keywords (unique)
        baseline_keywords = unique_keywords_from_baseline(baseline)  # type: ignore
        kws_set = set(baseline_keywords)
        per_domain_keys_ok = True
        values_ok_nonneg = True
        for dom in domains:
            dom_map = kc_data.get(dom)
            if not isinstance(dom_map, dict):
                per_domain_keys_ok = False
                values_ok_nonneg = False
                break
            if set(dom_map.keys()) != kws_set:
                per_domain_keys_ok = False
            for _, v in dom_map.items():
                if not isinstance(v, int) or v < 0:
                    values_ok_nonneg = False
                    break
        # Recompute counts from text and compare
        recomputed, comp_err = compute_counts_from_texts(workspace, domains, baseline_keywords)
        if recomputed is not None:
            counts_by_domain_expected = recomputed
            recomputed_match = True
            for dom in domains:
                for kw in baseline_keywords:
                    if kc_data.get(dom, {}).get(kw) != recomputed.get(dom, {}).get(kw):
                        recomputed_match = False
                        break
                if not recomputed_match:
                    break
        else:
            recomputed_match = False
        keyword_counts_ok = domains_present and per_domain_keys_ok and values_ok_nonneg and recomputed_match
    else:
        keyword_counts_ok = False

    scores["keyword_counts_json_valid"] = 1.0 if keyword_counts_ok else 0.0

    # Validate analytics/task_scores.csv
    task_scores_csv = workspace / "analytics" / "task_scores.csv"
    header, rows = parse_csv_dicts(task_scores_csv)
    csv_ok = False
    if baseline_valid and header is not None and rows is not None:
        expected_header = ["task_id", "task_name", "frequency", "total_matches", "domains_with_hits"]
        header_ok = header == expected_header
        # Determine counts source
        counts_source: Optional[Dict[str, Dict[str, int]]] = None
        if counts_by_domain_expected is not None:
            counts_source = counts_by_domain_expected
        elif kc_data is not None and isinstance(kc_data, dict):
            try:
                baseline_keywords = unique_keywords_from_baseline(baseline)  # type: ignore
                if all(isinstance(kc_data.get(dom), dict) for dom in domains):
                    counts_source = {}
                    for dom in domains:
                        dom_map = kc_data.get(dom, {})
                        counts_source[dom] = {}
                        for kw in baseline_keywords:
                            val = dom_map.get(kw)
                            if isinstance(val, int) and val >= 0:
                                counts_source[dom][kw] = val
                            else:
                                counts_source = None
                                break
                        if counts_source is None:
                            break
            except Exception:
                counts_source = None
        total_rows_needed = len(baseline.get("tasks", [])) if baseline_valid else 0
        expected_aggs = None
        if counts_source is not None:
            expected_aggs = compute_task_aggregates(baseline, counts_source, domains)  # type: ignore

        actual_list = []
        for r in rows:
            if not all(k in r for k in expected_header):
                continue
            tid = (r.get("task_id") or "").strip()
            tname = (r.get("task_name") or "").strip()
            freq = (r.get("frequency") or "").strip()
            try:
                tmatches = int(r.get("total_matches") or "")
            except Exception:
                tmatches = None  # type: ignore
            doms_hit_list = parse_domains_with_hits(r.get("domains_with_hits") or "")
            actual_list.append({
                "task_id": tid,
                "task_name": tname,
                "frequency": freq,
                "total_matches": tmatches,
                "domains_with_hits": set(doms_hit_list),
            })

        rows_count_ok = (len(rows) == total_rows_needed) if baseline_valid else False

        content_ok = False
        if expected_aggs is not None:
            per_row_correct = 0
            for item in actual_list:
                tid = item["task_id"]
                if tid not in expected_aggs:
                    continue
                exp = expected_aggs[tid]
                ok = (
                    item["task_name"] == exp["task_name"]
                    and item["frequency"] == exp["frequency"]
                    and isinstance(item["total_matches"], int)
                    and item["total_matches"] == exp["total_matches"]
                    and item["domains_with_hits"] == exp["domains_with_hits"]
                )
                if ok:
                    per_row_correct += 1
            content_ok = (per_row_correct == total_rows_needed)

        sorting_ok = False
        try:
            sort_keys = [(-int(item["total_matches"]), item["task_id"]) for item in actual_list]  # type: ignore
            sorting_ok = all(sort_keys[i] <= sort_keys[i + 1] for i in range(len(sort_keys) - 1))
        except Exception:
            sorting_ok = False

        csv_ok = header_ok and rows_count_ok and content_ok and sorting_ok
    else:
        csv_ok = False

    scores["task_scores_csv_valid"] = 1.0 if csv_ok else 0.0

    # Validate outputs/maintenance_status.md
    status_path = workspace / "outputs" / "maintenance_status.md"
    status_text = read_text(status_path)
    status_ok = False
    if status_text is not None and len(status_text.strip()) > 0 and baseline_valid:
        sections = [
            "Sources:",
            "Fetch results:",
            "Keyword signal (by domain):",
            "Top 3 chores to prioritize:",
            "Artifacts:",
        ]
        sections_order_ok = check_sections_order(status_text, sections)
        sources_sec = extract_section(status_text, "Sources:", "Fetch results:")
        fetch_sec = extract_section(status_text, "Fetch results:", "Keyword signal (by domain):")
        keyword_sec = extract_section(status_text, "Keyword signal (by domain):", "Top 3 chores to prioritize:")
        top3_sec = extract_section(status_text, "Top 3 chores to prioritize:", "Artifacts:")
        artifacts_sec = extract_section(status_text, "Artifacts:", None)

        sources_ok = all(dom in sources_sec for dom in domains)

        fetch_ok = True
        for dom in domains:
            raw_path = workspace / "web" / "raw" / f"{dom}.html"
            raw_content = read_text(raw_path)
            expected_ok = raw_content is not None and len(raw_content.strip()) > 0
            found_line_ok = False
            for line in fetch_sec.splitlines():
                if dom in line:
                    if expected_ok and ("OK" in line):
                        found_line_ok = True
                        break
                    if (not expected_ok) and ("FAILED" in line):
                        found_line_ok = True
                        break
            if not found_line_ok:
                fetch_ok = False
                break

        link_ok = "analytics/keyword_counts.json" in keyword_sec
        nonzero_ok = True
        nz_domains_expected = set()
        if kc_data and isinstance(kc_data, dict):
            for dom in domains:
                dmap = kc_data.get(dom, {})
                if isinstance(dmap, dict):
                    total = sum(v for v in dmap.values() if isinstance(v, int))
                    if total > 0:
                        nz_domains_expected.add(dom)
        else:
            if baseline_valid:
                baseline_keywords = unique_keywords_from_baseline(baseline)  # type: ignore
                recomputed, _ = compute_counts_from_texts(workspace, domains, baseline_keywords)
                if recomputed is not None:
                    for dom in domains:
                        if sum(recomputed.get(dom, {}).values()) > 0:
                            nz_domains_expected.add(dom)
        for dom in nz_domains_expected:
            if dom not in keyword_sec:
                nonzero_ok = False
                break
        keyword_sec_ok = link_ok and nonzero_ok

        top3_ok = False
        top_expected = []
        if header is not None and rows is not None and csv_ok:
            items = []
            for r in rows:
                tid = (r.get("task_id") or "").strip()
                tname = (r.get("task_name") or "").strip()
                freq = (r.get("frequency") or "").strip()
                try:
                    tmatches = int(r.get("total_matches") or "")
                except Exception:
                    tmatches = 0
                doms = set(parse_domains_with_hits(r.get("domains_with_hits") or ""))
                items.append((tid, tname, freq, tmatches, doms))
            items_sorted = sorted(items, key=lambda x: (-x[3], x[0]))
            top_expected = items_sorted[:3]
        elif baseline_valid:
            baseline_keywords = unique_keywords_from_baseline(baseline)  # type: ignore
            counts_src = counts_by_domain_expected
            if counts_src is None:
                rec, _ = compute_counts_from_texts(workspace, domains, baseline_keywords)
                counts_src = rec
            if counts_src is not None:
                aggs = compute_task_aggregates(baseline, counts_src, domains)  # type: ignore
                items = []
                for task in baseline.get("tasks", []):
                    tid = task.get("id")
                    entry = aggs.get(tid, {})
                    items.append((
                        tid,
                        task.get("name"),
                        task.get("frequency"),
                        entry.get("total_matches", 0),
                        entry.get("domains_with_hits", set())
                    ))
                items_sorted = sorted(items, key=lambda x: (-x[3], x[0]))
                top_expected = items_sorted[:3]
        if top_expected:
            all_three_ok = True
            for (_, tname, freq, tmatches, doms) in top_expected:
                found_name = isinstance(tname, str) and (tname in top3_sec)
                found_freq = isinstance(freq, str) and (freq in top3_sec)
                found_total = str(tmatches) in top3_sec
                doms_ok = True
                for d in doms:
                    if d not in top3_sec:
                        doms_ok = False
                        break
                if not (found_name and found_freq and found_total and doms_ok):
                    all_three_ok = False
                    break
            top3_ok = all_three_ok
        else:
            top3_ok = False

        artifact_lines = []
        for line in artifacts_sec.splitlines():
            stripped = line.strip()
            if stripped.startswith("- ") or stripped.startswith("* "):
                artifact_lines.append(stripped[2:].strip())
            elif stripped.startswith("-") and len(stripped) > 1 and stripped[1] != "-":
                artifact_lines.append(stripped[1:].strip())
            elif stripped.startswith("*") and len(stripped) > 1 and stripped[1] != "*":
                artifact_lines.append(stripped[1:].strip())
        artifact_set = set(artifact_lines)
        required_artifacts = {
            "web/raw/epa.gov.html",
            "web/raw/energy.gov.html",
            "web/raw/ready.gov.html",
            "web/text/epa.gov.txt",
            "web/text/energy.gov.txt",
            "web/text/ready.gov.txt",
            "analytics/keyword_counts.json",
            "analytics/task_scores.csv",
        }
        artifacts_ok = required_artifacts.issubset(artifact_set)

        checks = [
            sections_order_ok,
            sources_ok,
            fetch_ok,
            keyword_sec_ok,
            top3_ok,
            artifacts_ok,
        ]
        status_ok = all(checks)
    else:
        status_ok = False

    scores["status_report_valid"] = 1.0 if status_ok else 0.0

    # Run pipeline script presence
    run_sh = workspace / "scripts" / "run_pipeline.sh"
    run_py = workspace / "scripts" / "run_pipeline.py"
    script_exists = run_sh.exists() or run_py.exists()
    scores["run_pipeline_script_exists"] = 1.0 if script_exists else 0.0

    # Script coverage of paths: ensure it references key paths
    script_paths_ok = False
    if script_exists:
        script_path = run_py if run_py.exists() else run_sh
        script_text = read_text(script_path) or ""
        needed_snippets = [
            "web/raw/epa.gov.html",
            "web/raw/energy.gov.html",
            "web/raw/ready.gov.html",
            "web/text/epa.gov.txt",
            "web/text/energy.gov.txt",
            "web/text/ready.gov.txt",
            "analytics/keyword_counts.json",
            "analytics/task_scores.csv",
            "input/baseline_tasks.json",
            "epa.gov",
            "energy.gov",
            "ready.gov",
        ]
        script_paths_ok = all(snippet in script_text for snippet in needed_snippets)
    scores["run_pipeline_script_covers_paths"] = 1.0 if script_paths_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    # Preserve insertion order without sorting keys
    print(json.dumps(result))


if __name__ == "__main__":
    main()