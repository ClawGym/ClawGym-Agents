import json
import csv
import sys
import re
from pathlib import Path
from datetime import datetime


def _read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            if reader.fieldnames is None:
                return None
            for row in reader:
                rows.append({k: v for k, v in row.items()})
            return {"fieldnames": reader.fieldnames, "rows": rows}
    except Exception:
        return None


def _split_paragraphs(text: str):
    paras = []
    current = []
    for line in text.splitlines():
        if line.strip() == "":
            if current:
                paras.append("\n".join(current).strip())
                current = []
        else:
            current.append(line.rstrip("\n"))
    if current:
        paras.append("\n".join(current).strip())
    return paras


def _count_sentences(text: str):
    return len(re.findall(r'[\.!\?]', text))


def _extract_yaml_block(lines, start_idx):
    base_indent = len(lines[start_idx]) - len(lines[start_idx].lstrip(' '))
    block = []
    for i in range(start_idx + 1, len(lines)):
        line = lines[i]
        if line.strip() == "":
            block.append(line)
            continue
        indent = len(line) - len(line.lstrip(' '))
        if indent <= base_indent:
            break
        block.append(line)
    return block


def _find_line_index_startswith(lines, pattern, start=0):
    for i in range(start, len(lines)):
        if lines[i].strip().startswith(pattern):
            return i
    return -1


def _parse_pipeline_branches_and_env(text: str):
    if text is None:
        return None, None
    lines = text.splitlines()
    branches = None
    node_version = None

    env_idx = _find_line_index_startswith(lines, "env:")
    if env_idx != -1:
        env_block = _extract_yaml_block(lines, env_idx)
        for ln in env_block:
            stripped = ln.strip()
            m = re.match(r'node_version:\s*(.+)$', stripped)
            if m:
                val = m.group(1).strip()
                try:
                    node_version = int(val)
                except Exception:
                    val_clean = val.strip('\'"')
                    try:
                        node_version = int(val_clean)
                    except Exception:
                        node_version = None

    on_idx = _find_line_index_startswith(lines, "on:")
    if on_idx != -1:
        on_block = _extract_yaml_block(lines, on_idx)
        push_idx = -1
        for i, ln in enumerate(on_block):
            if ln.strip().startswith("push:"):
                push_idx = i
                break
        if push_idx != -1:
            push_block = _extract_yaml_block(on_block, push_idx)
            branches_idx = -1
            for i, ln in enumerate(push_block):
                if ln.strip().startswith("branches:"):
                    branches_idx = i
                    break
            if branches_idx != -1:
                branches_block = _extract_yaml_block(push_block, branches_idx)
                items = []
                for ln in branches_block:
                    s = ln.strip()
                    if s.startswith("- "):
                        items.append(s[2:].strip())
                branches = items

    return branches, node_version


def _compute_ci_main_metrics(ci_rows):
    main_rows = [r for r in ci_rows if r.get("branch") == "main"]
    total_runs = len(main_rows)
    succeeded = sum(1 for r in main_rows if r.get("status") == "success")
    failed = sum(1 for r in main_rows if r.get("status") == "failure")
    latest_id = None
    latest_ts = None
    for r in main_rows:
        ts_str = r.get("timestamp")
        try:
            ts = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except Exception:
                ts = None
        if ts is not None:
            if latest_ts is None or ts > latest_ts:
                latest_ts = ts
                latest_id = r.get("build_id")
    return {
        "branch": "main",
        "total_runs": total_runs,
        "succeeded": succeeded,
        "failed": failed,
        "latest_build_id": latest_id if latest_id is not None else ""
    }


def _safe_int(s, default=None):
    try:
        return int(s)
    except Exception:
        return default


def _top_passing_tests(rows, top_n):
    passing = []
    for r in rows:
        if r.get("status") == "pass":
            d = _safe_int(r.get("duration_ms"))
            if d is None:
                return None
            passing.append({
                "test_name": r.get("test_name"),
                "job": r.get("job"),
                "duration_ms": d
            })
    passing.sort(key=lambda x: (-x["duration_ms"], x["test_name"] if x["test_name"] is not None else ""))
    return passing[:top_n]


def _failing_tests_ranked(rows):
    counts = {}
    for r in rows:
        if r.get("status") == "fail":
            name = r.get("test_name")
            if name is None:
                return None
            counts[name] = counts.get(name, 0) + 1
    items = [{"test_name": k, "failures": v} for k, v in counts.items() if v > 0]
    items.sort(key=lambda x: (-x["failures"], x["test_name"]))
    return items


def _extract_section(text: str, title: str):
    if text is None:
        return None
    lines = text.splitlines()
    section_start = None
    for i, ln in enumerate(lines):
        if ln.strip().startswith("#"):
            heading = ln.strip().lstrip("#").strip()
            if heading == title:
                section_start = i
                break
    if section_start is None:
        return None
    content = []
    for j in range(section_start + 1, len(lines)):
        if lines[j].strip().startswith("#"):
            break
        content.append(lines[j])
    return content


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_json_version_updated": 0.0,
        "config_json_node_major_updated": 0.0,
        "pipeline_branches_updated": 0.0,
        "pipeline_env_node_version_updated": 0.0,
        "readme_current_version_matches": 0.0,
        "readme_second_paragraph_rewritten_valid": 0.0,
        "release_notes_version_replaced": 0.0,
        "release_notes_main_summary_correct": 0.0,
        "release_notes_top_slow_tests_correct": 0.0,
        "metrics_top_slowest_passing_tests_csv": 0.0,
        "metrics_failing_tests_ranked_csv": 0.0,
        "metrics_ci_main_summary_json": 0.0,
        "report_cd_status_sections_present": 0.0,
        "report_overview_mentions_version_and_phrase": 0.0,
        "report_pipeline_changes_mentioned": 0.0,
        "report_key_metrics_summary_correct": 0.0,
        "report_key_metrics_top_tests_listed": 0.0,
        "report_next_steps_bullets_count": 0.0,
    }

    expected_version = "1.4.3"
    config_path = workspace / "input" / "site" / "config.json"
    pipeline_path = workspace / "input" / ".ci" / "pipeline.yml"
    readme_path = workspace / "input" / "docs" / "README.md"
    relnotes_path = workspace / "input" / "docs" / "RELEASE_NOTES.md"
    test_results_path = workspace / "input" / "data" / "test_results.csv"
    ci_runs_path = workspace / "input" / "data" / "ci_runs.csv"

    config_json = _load_json(config_path)
    pipeline_text = _read_text(pipeline_path)
    readme_text = _read_text(readme_path)
    relnotes_text = _read_text(relnotes_path)
    test_results_csv = _load_csv_dicts(test_results_path)
    ci_runs_csv = _load_csv_dicts(ci_runs_path)

    computed_top3 = None
    computed_top5 = None
    computed_failing_ranked = None
    computed_ci_summary = None

    if test_results_csv is not None and test_results_csv.get("rows") is not None:
        rows = test_results_csv["rows"]
        computed_top5 = _top_passing_tests(rows, 5)
        if computed_top5 is not None:
            computed_top3 = computed_top5[:3]
        computed_failing_ranked = _failing_tests_ranked(rows)

    if ci_runs_csv is not None and ci_runs_csv.get("rows") is not None:
        computed_ci_summary = _compute_ci_main_metrics(ci_runs_csv["rows"])

    if isinstance(config_json, dict):
        if config_json.get("version") == expected_version:
            scores["config_json_version_updated"] = 1.0
        if config_json.get("nodeMajor") == 18:
            scores["config_json_node_major_updated"] = 1.0

    branches_list, node_version_val = _parse_pipeline_branches_and_env(pipeline_text)
    if branches_list is not None:
        has_main = "main" in branches_list
        has_releases = "releases/*" in branches_list
        if has_main and has_releases:
            scores["pipeline_branches_updated"] = 1.0
    if node_version_val is not None and node_version_val == 18:
        scores["pipeline_env_node_version_updated"] = 1.0

    if readme_text is not None:
        paras = _split_paragraphs(readme_text)
        current_version_lines = [ln for ln in readme_text.splitlines() if ln.strip().startswith("Current Version:")]
        if len(current_version_lines) >= 1 and any(ln.strip() == f"Current Version: {expected_version}" for ln in current_version_lines):
            scores["readme_current_version_matches"] = 1.0
        if len(paras) >= 4:
            header_ok = (paras[0].strip() == "# DarkSkies Community Site")
            first_para_ok = (paras[1].strip() == "This small website supports our park rangers and neighbors.")
            second_para = paras[2].strip()
            phrase_count = second_para.count("star-filled nights")
            sent_count = _count_sentences(second_para)
            second_para_valid = (2 <= sent_count <= 3) and (phrase_count == 1)
            if header_ok and first_para_ok and second_para_valid:
                scores["readme_second_paragraph_rewritten_valid"] = 1.0

    if relnotes_text is not None:
        first_line = relnotes_text.splitlines()[0].strip() if relnotes_text.splitlines() else ""
        if first_line == f"# Release {expected_version}":
            scores["release_notes_version_replaced"] = 1.0
        if computed_ci_summary is not None:
            expected_summary_line = f"main: {computed_ci_summary['total_runs']} runs, {computed_ci_summary['succeeded']} succeeded, {computed_ci_summary['failed']} failed, latest build ID {computed_ci_summary['latest_build_id']}"
            lines = [ln.strip() for ln in relnotes_text.splitlines()]
            if expected_summary_line in lines:
                scores["release_notes_main_summary_correct"] = 1.0
        if computed_top3 is not None:
            lines = relnotes_text.splitlines()
            header_idx = -1
            for i, ln in enumerate(lines):
                if ln.strip().startswith("Top slow passing tests"):
                    header_idx = i
                    break
            bullets = []
            if header_idx != -1:
                for j in range(header_idx + 1, len(lines)):
                    s = lines[j].strip()
                    if s.startswith("- "):
                        bullets.append(s)
                    elif s == "":
                        break
                    else:
                        continue
            expected_bullets = [f"- {t['test_name']} ({t['duration_ms']} ms)" for t in computed_top3]
            if bullets == expected_bullets:
                scores["release_notes_top_slow_tests_correct"] = 1.0

    out_top5_path = workspace / "output" / "metrics" / "top_slowest_passing_tests.csv"
    out_top5_csv = _load_csv_dicts(out_top5_path)
    if out_top5_csv is not None and computed_top5 is not None:
        headers_ok = out_top5_csv.get("fieldnames") == ["test_name", "job", "duration_ms"]
        rows = out_top5_csv.get("rows", [])
        content_ok = False
        if headers_ok and len(rows) == len(computed_top5):
            match_all = True
            for r, exp in zip(rows, computed_top5):
                if r.get("test_name") != exp["test_name"]:
                    match_all = False
                    break
                if r.get("job") != exp["job"]:
                    match_all = False
                    break
                if _safe_int(r.get("duration_ms")) != exp["duration_ms"]:
                    match_all = False
                    break
            content_ok = match_all
        if headers_ok and content_ok:
            scores["metrics_top_slowest_passing_tests_csv"] = 1.0

    out_fails_path = workspace / "output" / "metrics" / "failing_tests_ranked.csv"
    out_fails_csv = _load_csv_dicts(out_fails_path)
    if out_fails_csv is not None and computed_failing_ranked is not None:
        headers_ok = out_fails_csv.get("fieldnames") == ["test_name", "failures"]
        rows = out_fails_csv.get("rows", [])
        content_ok = False
        if headers_ok and len(rows) == len(computed_failing_ranked):
            match_all = True
            for r, exp in zip(rows, computed_failing_ranked):
                if r.get("test_name") != exp["test_name"]:
                    match_all = False
                    break
                if _safe_int(r.get("failures")) != exp["failures"]:
                    match_all = False
                    break
            content_ok = match_all
        if headers_ok and content_ok:
            scores["metrics_failing_tests_ranked_csv"] = 1.0

    out_ci_json_path = workspace / "output" / "metrics" / "ci_main_summary.json"
    out_ci_json = _load_json(out_ci_json_path)
    if out_ci_json is not None and computed_ci_summary is not None:
        expected_keys = {"branch", "total_runs", "succeeded", "failed", "latest_build_id"}
        keys_ok = set(out_ci_json.keys()) == expected_keys
        values_ok = (
            out_ci_json.get("branch") == "main" and
            out_ci_json.get("total_runs") == computed_ci_summary["total_runs"] and
            out_ci_json.get("succeeded") == computed_ci_summary["succeeded"] and
            out_ci_json.get("failed") == computed_ci_summary["failed"] and
            out_ci_json.get("latest_build_id") == computed_ci_summary["latest_build_id"]
        )
        if keys_ok and values_ok:
            scores["metrics_ci_main_summary_json"] = 1.0

    cd_status_path = workspace / "output" / "reports" / "CD_status.md"
    cd_status_text = _read_text(cd_status_path)
    if cd_status_text is not None:
        sections = {}
        for title in ["Overview", "Pipeline changes", "Key metrics", "Next steps"]:
            sections[title] = _extract_section(cd_status_text, title)
        if all(sections[t] is not None for t in sections):
            scores["report_cd_status_sections_present"] = 1.0

        overview = sections.get("Overview")
        if overview is not None:
            ov_text = "\n".join([ln.strip() for ln in overview]).strip()
            if expected_version in ov_text and "star-filled nights" in ov_text:
                scores["report_overview_mentions_version_and_phrase"] = 1.0

        pipeline_changes = sections.get("Pipeline changes")
        if pipeline_changes is not None:
            pc_text = "\n".join([ln.strip() for ln in pipeline_changes])
            has_config = "config.json" in pc_text
            has_pipeline = "pipeline.yml" in pc_text
            has_node_18 = "18" in pc_text and ("node" in pc_text or "node_version" in pc_text)
            has_main = "main" in pc_text
            has_releases = "releases/*" in pc_text
            if has_config and has_pipeline and has_node_18 and has_main and has_releases:
                scores["report_pipeline_changes_mentioned"] = 1.0

        key_metrics = sections.get("Key metrics")
        if key_metrics is not None and computed_ci_summary is not None and computed_top3 is not None:
            km_lines = [ln.strip() for ln in key_metrics if ln.strip() != ""]
            expected_summary_line = f"main: {computed_ci_summary['total_runs']} runs, {computed_ci_summary['succeeded']} succeeded, {computed_ci_summary['failed']} failed, latest build ID {computed_ci_summary['latest_build_id']}"
            summary_ok = any(ln == expected_summary_line for ln in km_lines)
            bullets = [ln for ln in km_lines if ln.startswith("- ")]
            expected_bullets = [f"- {t['test_name']} ({t['duration_ms']} ms)" for t in computed_top3]
            bullets_ok = bullets[:len(expected_bullets)] == expected_bullets and len(bullets) >= 3
            if summary_ok:
                scores["report_key_metrics_summary_correct"] = 1.0
            if bullets_ok:
                scores["report_key_metrics_top_tests_listed"] = 1.0

        next_steps = sections.get("Next steps")
        if next_steps is not None:
            ns_bullets = [ln for ln in next_steps if ln.strip().startswith("- ")]
            if 1 <= len(ns_bullets) <= 2:
                scores["report_next_steps_bullets_count"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()