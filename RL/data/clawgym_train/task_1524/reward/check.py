import json
import sys
import re
from pathlib import Path
from typing import Tuple, Optional, Dict, List


def _read_text(path: Path) -> Tuple[bool, str]:
    try:
        return True, path.read_text(encoding="utf-8")
    except Exception as e:
        return False, str(e)


def _read_json(path: Path) -> Tuple[bool, object]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception as e:
        return False, str(e)


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except Exception:
        return 0


def _is_hex_color(s: str) -> bool:
    return bool(re.fullmatch(r"#([0-9a-fA-F]{6})", s or ""))


def _normalize_heading_line(line: str) -> str:
    s = line.strip()
    while s.startswith("#"):
        s = s[1:]
    return s.strip().lower()


def _parse_sections_by_markers(text: str, markers: List[str]) -> Dict[str, List[str]]:
    lines = text.splitlines()
    norm_markers = {m.lower(): m for m in markers}
    current_key: Optional[str] = None
    sections: Dict[str, List[str]] = {m: [] for m in markers}
    for line in lines:
        norm_line = _normalize_heading_line(line)
        matched: Optional[str] = None
        for nm in norm_markers:
            if norm_line.startswith(nm):
                matched = norm_markers[nm]
                break
        if matched is not None:
            current_key = matched
            continue
        if current_key is not None:
            sections[current_key].append(line)
    for k in sections:
        while sections[k] and sections[k][-1].strip() == "":
            sections[k].pop()
        while sections[k] and sections[k][0].strip() == "":
            sections[k].pop(0)
    return sections


def _find_verification_section(text: str) -> Tuple[Optional[Dict[str, object]], int, int]:
    lines = text.splitlines()
    verification_idx = -1
    for i, line in enumerate(lines):
        nl = _normalize_heading_line(line)
        if nl == "verification":
            verification_idx = i
    if verification_idx == -1:
        return None, -1, -1
    content_lines = lines[verification_idx + 1 :]
    content = "\n".join(content_lines).strip()
    last_heading_idx = -1
    for i, line in enumerate(lines):
        if line.strip().startswith("#"):
            last_heading_idx = i
    is_last_heading = (last_heading_idx == verification_idx)
    return {"content": content, "is_last_heading": is_last_heading}, verification_idx, len(lines)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_title_and_output_exact": 0.0,
        "config_fields_valid": 0.0,
        "report_exists_and_ok": 0.0,
        "report_consistency_with_files": 0.0,
        "svg_generated_and_contains_title": 0.0,
        "status_md_environment_section": 0.0,
        "status_md_test_artifact_section": 0.0,
        "status_md_next_steps_bullet_count": 0.0,
        "plan_verification_section_appended": 0.0,
        "plan_verification_references_artifacts": 0.0,
    }

    cfg_path = workspace / "config" / "visuals.json"
    report_path = workspace / "out" / "vischeck_report.json"
    svg_path = workspace / "out" / "test_plot.svg"
    status_md_path = workspace / "out" / "system_visuals_status.md"
    plan_md_path = workspace / "report" / "visuals_plan.md"

    required_title = "Visuals Check: Rendering OK"
    required_output = "out/test_plot.svg"

    cfg_ok, cfg_or_err = _read_json(cfg_path)
    cfg = cfg_or_err if cfg_ok and isinstance(cfg_or_err, dict) else None

    if cfg:
        title_ok = isinstance(cfg.get("title"), str) and cfg.get("title") == required_title
        output_ok = isinstance(cfg.get("output"), str) and cfg.get("output") == required_output
        if title_ok and output_ok:
            scores["config_title_and_output_exact"] = 1.0

        # Structural validity that depends on non-empty title to avoid rewarding baseline scaffold
        title_nonempty = isinstance(cfg.get("title"), str) and cfg.get("title").strip() != ""
        width_ok = isinstance(cfg.get("width"), int) and cfg.get("width", 0) > 0
        height_ok = isinstance(cfg.get("height"), int) and cfg.get("height", 0) > 0
        bg_ok = isinstance(cfg.get("bg_color"), str) and _is_hex_color(cfg.get("bg_color"))
        output_nonempty = isinstance(cfg.get("output"), str) and cfg.get("output").strip() != ""
        if title_nonempty and width_ok and height_ok and bg_ok and output_nonempty:
            scores["config_fields_valid"] = 1.0

    report_ok, report_or_err = _read_json(report_path)
    report = report_or_err if report_ok and isinstance(report_or_err, dict) else None

    if report:
        if (
            report.get("ok") is True
            and isinstance(report.get("python_version"), str)
            and isinstance(report.get("working_directory"), str)
            and isinstance(report.get("output_file"), str)
        ):
            scores["report_exists_and_ok"] = 1.0

    if report:
        rep_output_file = report.get("output_file")
        rep_output_exists = report.get("output_exists")
        rep_size = report.get("output_size_bytes")
        actual_svg_exists = svg_path.exists()
        actual_svg_size = _file_size(svg_path)
        conds = []
        conds.append(rep_output_file == required_output)
        conds.append(rep_output_exists is True)
        conds.append(isinstance(rep_size, int) and rep_size > 0)
        conds.append(actual_svg_exists)
        conds.append(actual_svg_size == rep_size if isinstance(rep_size, int) else False)
        cfg_in_report = report.get("config", {})
        conds.append(isinstance(cfg_in_report, dict))
        if isinstance(cfg_in_report, dict):
            conds.append(cfg_in_report.get("title") == required_title)
            conds.append(cfg_in_report.get("output") == required_output)
        if all(conds):
            scores["report_consistency_with_files"] = 1.0

    if svg_path.exists():
        svg_size = _file_size(svg_path)
        ok_text, svg_text_or_err = _read_text(svg_path)
        has_title = False
        if ok_text and isinstance(svg_text_or_err, str):
            has_title = required_title in svg_text_or_err
        if svg_size > 0 and has_title:
            scores["svg_generated_and_contains_title"] = 1.0

    status_ok, status_text_or_err = _read_text(status_md_path)
    if status_ok and isinstance(status_text_or_err, str):
        markers = [
            "Environment check:",
            "Test artifact:",
            "Next steps for project visuals:",
        ]
        sections = _parse_sections_by_markers(status_text_or_err, markers)

        if report:
            env_lines = "\n".join(sections.get("Environment check:", []))
            if isinstance(env_lines, str):
                has_py = report.get("python_version", "") in env_lines
                has_wd = report.get("working_directory", "") in env_lines
                if has_py and has_wd:
                    scores["status_md_environment_section"] = 1.0

        test_lines = "\n".join(sections.get("Test artifact:", []))
        if isinstance(test_lines, str) and report:
            has_path = required_output in test_lines
            rep_size_val = report.get("output_size_bytes")
            size_str_ok = isinstance(rep_size_val, int) and str(rep_size_val) in test_lines
            has_title = required_title in test_lines
            if has_path and size_str_ok and has_title:
                scores["status_md_test_artifact_section"] = 1.0

        next_lines_list = sections.get("Next steps for project visuals:", [])
        if isinstance(next_lines_list, list):
            bullet_count = 0
            for ln in next_lines_list:
                s = ln.lstrip()
                if s.startswith("- ") or s.startswith("* "):
                    if s.strip() not in {"- ", "* "}:
                        bullet_count += 1
            if 2 <= bullet_count <= 4:
                scores["status_md_next_steps_bullet_count"] = 1.0

    plan_ok, plan_text_or_err = _read_text(plan_md_path)
    if plan_ok and isinstance(plan_text_or_err, str):
        section_info, _, _ = _find_verification_section(plan_text_or_err)
        if section_info is not None:
            if section_info.get("is_last_heading", False):
                scores["plan_verification_section_appended"] = 1.0

            content = section_info.get("content", "")
            content_lc = content.lower()
            has_render_static_fig = ("render" in content_lc) and ("static" in content_lc) and ("figure" in content_lc)
            has_svg_path = required_output in content
            has_title = required_title in content
            has_python_version = False
            if report:
                has_python_version = report.get("python_version", "") in content
            if has_render_static_fig and has_svg_path and has_title and has_python_version:
                scores["plan_verification_references_artifacts"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()