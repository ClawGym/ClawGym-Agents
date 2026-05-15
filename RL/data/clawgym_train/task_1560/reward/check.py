import json
import csv
import sys
from pathlib import Path


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_read_csv(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, None
        header = rows[0]
        data = rows[1:]
        return header, data
    except Exception:
        return None, None


def _sorted_txt_files(dir_path: Path):
    try:
        if not dir_path.is_dir():
            return []
        return sorted([p for p in dir_path.glob("*.txt")], key=lambda p: p.name)
    except Exception:
        return []


def _strip_lines(text: str):
    return [line.strip("\n").rstrip("\r") for line in text.splitlines()]


def _normalize_path_str(p: str) -> str:
    return p.replace("\\", "/")


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_has_required_keys": 0.0,
        "config_values_correct_for_inputs": 0.0,
        "schedule_md_exists_and_exact_content": 0.0,
        "schedule_md_structure_labels": 0.0,
        "index_csv_exists_and_headers": 0.0,
        "index_csv_rows_correct": 0.0,
        "diagnostics_contains_two_run_commands": 0.0,
        "diagnostics_initial_error_logged": 0.0,
        "diagnostics_success_message_logged": 0.0,
    }

    # Paths
    config_path = workspace / "config" / "curriculum.json"
    tool_path = workspace / "tools" / "make_curriculum.py"
    md_path = workspace / "output" / "week1_evening_companion.md"
    idx_path = workspace / "output" / "week1_evening_companion_segments_index.csv"
    diagnostics_path = workspace / "diagnostics" / "run.txt"

    # Load config and validate keys/values
    cfg = _safe_load_json(config_path)
    required_keys = ['week_name', 'output_dir', 'news_dir', 'stories_dir', 'prompts_file', 'nights']
    if isinstance(cfg, dict) and all(k in cfg for k in required_keys):
        scores["config_has_required_keys"] = 1.0
        # Check values strictly per task/request and actual inputs
        expected_cfg = {
            "week_name": "week1_evening_companion",
            "output_dir": "output",
            "news_dir": "input/news",
            "stories_dir": "input/stories",
            "prompts_file": "input/prompts.txt",
            "nights": 7,
        }
        values_ok = True
        for k, v in expected_cfg.items():
            if k == "nights":
                try:
                    if int(cfg.get(k)) != v:
                        values_ok = False
                        break
                except Exception:
                    values_ok = False
                    break
            else:
                if cfg.get(k) != v:
                    values_ok = False
                    break
        scores["config_values_correct_for_inputs"] = 1.0 if values_ok else 0.0
    else:
        scores["config_has_required_keys"] = 0.0
        scores["config_values_correct_for_inputs"] = 0.0

    # Prepare expected inputs
    news_files = _sorted_txt_files(workspace / "input" / "news")
    story_files = _sorted_txt_files(workspace / "input" / "stories")
    prompts_txt = _safe_read_text(workspace / "input" / "prompts.txt")

    expected_available = True
    if not news_files or not story_files or prompts_txt is None:
        expected_available = False

    prompts_list = []
    if prompts_txt is not None:
        try:
            prompts_list = [line.strip() for line in prompts_txt.splitlines() if line.strip() != ""]
        except Exception:
            expected_available = False

    nights = 7

    expected_md_content = None
    expected_csv_rows = None
    if expected_available and len(prompts_list) > 0:
        try:
            # Build expected content
            md_lines = []
            csv_rows = []
            for i in range(nights):
                day = i + 1
                news_p = news_files[i % len(news_files)]
                story_p = story_files[i % len(story_files)]
                # Read file contents
                news_text = _safe_read_text(news_p)
                story_text = _safe_read_text(story_p)
                if news_text is None or story_text is None:
                    expected_available = False
                    break
                news_text = news_text.strip()
                story_text = story_text.strip()
                prompt_text = prompts_list[i % len(prompts_list)]

                md_lines.append(f"Day {day}")
                md_lines.append(f"News: {news_text}")
                md_lines.append(f"Story: {story_text}")
                md_lines.append(f"Reflection: {prompt_text}")
                md_lines.append("")  # blank line after each day

                # CSV rows, normalize to forward slashes for internal expected
                csv_rows.append([str(day), "news", _normalize_path_str(str(Path('input') / 'news' / news_p.name))])
                csv_rows.append([str(day), "story", _normalize_path_str(str(Path('input') / 'stories' / story_p.name))])
                csv_rows.append([str(day), "reflection", f"prompts:{(i % len(prompts_list)) + 1}"])
            if expected_available:
                expected_md_content = "\n".join(md_lines)
                expected_csv_rows = csv_rows
        except Exception:
            expected_available = False

    # Schedule MD checks
    md_text = _safe_read_text(md_path)
    if md_text is not None:
        # Exact content check
        if expected_md_content is not None and md_text == expected_md_content:
            scores["schedule_md_exists_and_exact_content"] = 1.0
        else:
            scores["schedule_md_exists_and_exact_content"] = 0.0

        # Structural check: 7 days, labels in order
        md_lines = _strip_lines(md_text)
        structure_ok = True
        # Expect 5 lines per day (Day, News, Story, Reflection, blank)
        if len(md_lines) != nights * 5:
            structure_ok = False
        else:
            for i in range(nights):
                base = i * 5
                expected_day = f"Day {i+1}"
                if md_lines[base] != expected_day:
                    structure_ok = False
                    break
                if not md_lines[base + 1].startswith("News: "):
                    structure_ok = False
                    break
                if not md_lines[base + 2].startswith("Story: "):
                    structure_ok = False
                    break
                if not md_lines[base + 3].startswith("Reflection: "):
                    structure_ok = False
                    break
                if md_lines[base + 4] != "":
                    structure_ok = False
                    break
        scores["schedule_md_structure_labels"] = 1.0 if structure_ok else 0.0
    else:
        scores["schedule_md_exists_and_exact_content"] = 0.0
        scores["schedule_md_structure_labels"] = 0.0

    # Index CSV checks
    header, rows = _safe_read_csv(idx_path)
    if header is not None:
        scores["index_csv_exists_and_headers"] = 1.0 if header == ["day", "segment_type", "source_file"] else 0.0
        rows_ok = False
        if expected_csv_rows is not None and rows is not None:
            # Normalize source_file paths for comparison
            act_rows = []
            for r in rows:
                if len(r) != 3:
                    act_rows = None
                    break
                day_val, seg, src = r[0], r[1], r[2]
                act_rows.append([str(day_val), seg, _normalize_path_str(src)])
            if act_rows is not None and len(act_rows) == nights * 3:
                rows_ok = (act_rows == expected_csv_rows)
        scores["index_csv_rows_correct"] = 1.0 if rows_ok else 0.0
    else:
        scores["index_csv_exists_and_headers"] = 0.0
        scores["index_csv_rows_correct"] = 0.0

    # Diagnostics checks
    diag_text = _safe_read_text(diagnostics_path)
    if diag_text is not None:
        norm_text = _normalize_path_str(diag_text)
        # Count occurrences of tool invocation mention
        cmd_occurrences = norm_text.count("tools/make_curriculum.py")
        scores["diagnostics_contains_two_run_commands"] = 1.0 if cmd_occurrences >= 2 else 0.0

        # Initial error check: accept either missing key or stories dir not found
        initial_error_ok = False
        # Find indices to ensure ordering: command before error
        first_cmd_idx = norm_text.find("tools/make_curriculum.py")
        err_candidates = [
            "Missing required config key: stories_dir",
            "Stories directory not found:",
        ]
        err_pos = -1
        for e in err_candidates:
            pos = norm_text.find(e)
            if pos != -1:
                err_pos = pos
                break
        if first_cmd_idx != -1 and err_pos != -1 and first_cmd_idx <= err_pos:
            initial_error_ok = True
        scores["diagnostics_initial_error_logged"] = 1.0 if initial_error_ok else 0.0

        # Success message check
        expected_success = "Wrote schedule to output/week1_evening_companion.md and index to output/week1_evening_companion_segments_index.csv."
        success_pos = norm_text.find(expected_success)
        # ensure a command appears before success message
        success_ok = success_pos != -1 and first_cmd_idx != -1 and first_cmd_idx <= success_pos
        scores["diagnostics_success_message_logged"] = 1.0 if success_ok else 0.0
    else:
        scores["diagnostics_contains_two_run_commands"] = 0.0
        scores["diagnostics_initial_error_logged"] = 0.0
        scores["diagnostics_success_message_logged"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()