import json
import sys
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


ALLOWED_CATEGORIES = {
    "unsafe_network_script_execution",
    "unpinned_or_dynamic_dependency",
    "hardcoded_or_weak_credential",
    "command_injection_or_shell_use",
    "insecure_telemetry_or_remote_endpoint",
    "auto_update_risk",
    "other",
}
ALLOWED_SEVERITY = {"low", "medium", "high"}


def _read_text_safe(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _load_json_safe(p: Path) -> Optional[Any]:
    try:
        txt = _read_text_safe(p)
        if txt is None:
            return None
        return json.loads(txt)
    except Exception:
        return None


def _normalize_rel_path(path_str: str) -> str:
    s = path_str.strip()
    if s.startswith("./"):
        s = s[2:]
    if s.startswith("project/"):
        s = s[len("project/"):]
    return s.replace("\\", "/")


def _posix_rel_path(p: Path, root: Path) -> str:
    return p.relative_to(root).as_posix()


def _list_project_paths(project_root: Path) -> List[str]:
    paths = set()
    if not project_root.exists():
        return []
    for dirpath, dirnames, filenames in _os_walk(project_root):
        rel_dir = Path(dirpath).relative_to(project_root).as_posix()
        if rel_dir != ".":
            paths.add(rel_dir)
        for f in filenames:
            rel_file = Path(dirpath, f).relative_to(project_root).as_posix()
            paths.add(rel_file)
    return sorted(paths)


def _os_walk(root: Path):
    # small wrapper for os.walk-style iteration using pathlib
    import os
    for dirpath, dirnames, filenames in os.walk(str(root)):
        yield dirpath, dirnames, filenames


def _is_valid_line_field(val: Any) -> bool:
    if isinstance(val, int):
        return val >= 1
    if isinstance(val, str):
        return bool(re.match(r"^\d+(-\d+)?$", val.strip()))
    return False


def _line_field_covers(line_field: Any, expected_line: int) -> bool:
    if not isinstance(expected_line, int) or expected_line < 1:
        return False
    if isinstance(line_field, int):
        return line_field == expected_line
    if isinstance(line_field, str):
        m = re.match(r"^\s*(\d+)(?:-(\d+))?\s*$", line_field)
        if m:
            a = int(m.group(1))
            b = int(m.group(2)) if m.group(2) else a
            return a <= expected_line <= b
    return False


def _extract_line_with_substring(text: str, substring: str) -> Optional[int]:
    lines = text.splitlines()
    for idx, line in enumerate(lines, start=1):
        if substring in line:
            return idx
    return None


def _expected_findings_from_project(project_root: Path) -> List[Dict[str, Any]]:
    expected: List[Dict[str, Any]] = []

    # site/package.json
    pkg_path = project_root / "site" / "package.json"
    pkg_text = _read_text_safe(pkg_path)
    if pkg_text is not None:
        try:
            pkg = json.loads(pkg_text)
        except Exception:
            pkg = None
        if isinstance(pkg, dict):
            # unsafe postinstall curl | sh
            scripts = pkg.get("scripts", {}) if isinstance(pkg.get("scripts"), dict) else {}
            postinstall = scripts.get("postinstall", "")
            if isinstance(postinstall, str) and re.search(r"\b(curl|wget)\b.*\|\s*(sh|bash)\b", postinstall):
                # find line number where this appears
                ln = _extract_line_with_substring(pkg_text, '"postinstall"')
                snippet = postinstall
                expected.append({
                    "file_path": "site/package.json",
                    "category": "unsafe_network_script_execution",
                    "evidence_substrings": [snippet, "curl", "| sh", "http://example.com/install.sh"],
                    "expected_line": ln if ln else 1,
                })
            # unpinned dependencies
            deps = pkg.get("dependencies", {}) if isinstance(pkg.get("dependencies"), dict) else {}
            for name, ver in deps.items():
                if isinstance(ver, str) and (ver.strip().startswith("^") or ver.strip().startswith("~") or ver.strip().lower() == "latest"):
                    # Build evidence as "name": "ver"
                    search_token = f'"{name}"'
                    ln = _extract_line_with_substring(pkg_text, search_token)
                    ev = f'"{name}": "{ver}"'
                    expected.append({
                        "file_path": "site/package.json",
                        "category": "unpinned_or_dynamic_dependency",
                        "evidence_substrings": [name, ver],
                        "expected_line": ln if ln else 1,
                    })

    # site/build.sh
    build_path = project_root / "site" / "build.sh"
    build_txt = _read_text_safe(build_path)
    if build_txt is not None:
        # detect curl | bash
        for idx, line in enumerate(build_txt.splitlines(), start=1):
            if re.search(r"\b(curl|wget)\b.*\|\s*(sh|bash)\b", line):
                expected.append({
                    "file_path": "site/build.sh",
                    "category": "unsafe_network_script_execution",
                    "evidence_substrings": ["curl", "| bash", "http://files.local/helper.sh"],
                    "expected_line": idx,
                })
                break

    # site/.env.example
    env_path = project_root / "site" / ".env.example"
    env_txt = _read_text_safe(env_path)
    if env_txt is not None:
        for idx, line in enumerate(env_txt.splitlines(), start=1):
            if "ADMIN_USER=admin" in line:
                expected.append({
                    "file_path": "site/.env.example",
                    "category": "hardcoded_or_weak_credential",
                    "evidence_substrings": ["ADMIN_USER=admin"],
                    "expected_line": idx,
                })
            if "ADMIN_PASSWORD=admin123" in line:
                expected.append({
                    "file_path": "site/.env.example",
                    "category": "hardcoded_or_weak_credential",
                    "evidence_substrings": ["ADMIN_PASSWORD=admin123"],
                    "expected_line": idx,
                })

    # site/config.yaml
    cfg_path = project_root / "site" / "config.yaml"
    cfg_txt = _read_text_safe(cfg_path)
    if cfg_txt is not None:
        for idx, line in enumerate(cfg_txt.splitlines(), start=1):
            if "http://tracker.local/collect" in line:
                expected.append({
                    "file_path": "site/config.yaml",
                    "category": "insecure_telemetry_or_remote_endpoint",
                    "evidence_substrings": ["http://tracker.local/collect"],
                    "expected_line": idx,
                })
            if "http://fileshare.local/upload" in line:
                expected.append({
                    "file_path": "site/config.yaml",
                    "category": "insecure_telemetry_or_remote_endpoint",
                    "evidence_substrings": ["http://fileshare.local/upload"],
                    "expected_line": idx,
                })
            if re.search(r'password:\s*"?123456"?', line):
                expected.append({
                    "file_path": "site/config.yaml",
                    "category": "hardcoded_or_weak_credential",
                    "evidence_substrings": ["password: \"123456\"", "password: 123456", "password: '123456'"],
                    "expected_line": idx,
                })

    # tools/art_tool.py
    art_path = project_root / "tools" / "art_tool.py"
    art_txt = _read_text_safe(art_path)
    if art_txt is not None:
        for idx, line in enumerate(art_txt.splitlines(), start=1):
            if "shell=True" in line:
                expected.append({
                    "file_path": "tools/art_tool.py",
                    "category": "command_injection_or_shell_use",
                    "evidence_substrings": ["shell=True", "subprocess.check_output"],
                    "expected_line": idx,
                })
        for idx, line in enumerate(art_txt.splitlines(), start=1):
            if "os.system(" in line:
                expected.append({
                    "file_path": "tools/art_tool.py",
                    "category": "command_injection_or_shell_use",
                    "evidence_substrings": ["os.system(", "pattern"],
                    "expected_line": idx,
                })

    # plugins/watercolor/manifest.yaml
    plug_path = project_root / "plugins" / "watercolor" / "manifest.yaml"
    plug_txt = _read_text_safe(plug_path)
    if plug_txt is not None:
        au_line = None
        url_line = None
        for idx, line in enumerate(plug_txt.splitlines(), start=1):
            if re.search(r'\bauto_update:\s*true\b', line):
                au_line = idx
            if "http://updates.local/watercolor/latest" in line:
                url_line = idx
        if au_line is not None:
            expected.append({
                "file_path": "plugins/watercolor/manifest.yaml",
                "category": "auto_update_risk",
                "evidence_substrings": ["auto_update: true"],
                "expected_line": au_line,
            })
        if url_line is not None:
            expected.append({
                "file_path": "plugins/watercolor/manifest.yaml",
                "category": "insecure_telemetry_or_remote_endpoint",
                "evidence_substrings": ["http://updates.local/watercolor/latest"],
                "expected_line": url_line,
            })

    return expected


def _parse_summary_sections(text: str) -> Dict[str, List[str]]:
    lines = text.splitlines()
    headers = ["Overview", "Top 3 Risks", "Quick Wins", "Next Steps"]
    positions: Dict[str, int] = {}
    for i, line in enumerate(lines):
        for h in headers:
            if re.match(rf"^\s*{re.escape(h)}\s*:?\s*$", line):
                if h not in positions:
                    positions[h] = i
    sections: Dict[str, List[str]] = {}
    for idx, h in enumerate(headers):
        if h in positions:
            start = positions[h] + 1
            # find next header
            next_pos = len(lines)
            for j in range(start, len(lines)):
                for other in headers:
                    if other != h and re.match(rf"^\s*{re.escape(other)}\s*:?\s*$", lines[j]):
                        next_pos = j
                        break
                if next_pos != len(lines):
                    break
            sections[h] = lines[start:next_pos]
    return sections


def _count_sentences(text: str) -> int:
    # naive sentence count splitting by ., !, ?
    parts = re.split(r"[\.!\?]+", text)
    count = 0
    for p in parts:
        if p.strip():
            # at least one alphanumeric
            if re.search(r"[A-Za-z0-9]", p):
                count += 1
    return count


def _validate_findings_schema(findings: Any) -> Tuple[float, float, float]:
    """
    Returns (schema_score, line_field_score, rec_action_score)
    schema_score: fraction of items that have all required fields and allowed values
    line_field_score: fraction of items with a valid line field format
    rec_action_score: fraction of items with non-empty recommended_action
    """
    if not isinstance(findings, list) or len(findings) == 0:
        return 0.0, 0.0, 0.0
    total = len(findings)
    schema_ok = 0
    line_ok = 0
    rec_ok = 0
    for item in findings:
        if isinstance(item, dict):
            id_ok = isinstance(item.get("id"), str) and item.get("id") != ""
            fp_ok = isinstance(item.get("file_path"), str) and item.get("file_path") != ""
            cat = item.get("category")
            cat_ok = isinstance(cat, str) and cat in ALLOWED_CATEGORIES
            sev = item.get("severity")
            sev_ok = isinstance(sev, str) and sev in ALLOWED_SEVERITY
            desc_ok = isinstance(item.get("description"), str) and item.get("description").strip() != ""
            evid_ok = isinstance(item.get("evidence"), str) and item.get("evidence").strip() != ""
            ra = item.get("recommended_action")
            rec_ok += 1 if (isinstance(ra, str) and ra.strip() != "") else 0
            line_val = item.get("line")
            line_valid = _is_valid_line_field(line_val)
            line_ok += 1 if line_valid else 0
            if id_ok and fp_ok and cat_ok and sev_ok and desc_ok and evid_ok and line_valid:
                schema_ok += 1
    return schema_ok / total, line_ok / total, rec_ok / total


def _find_match_for_expected(expected_item: Dict[str, Any], findings: List[Dict[str, Any]]) -> Tuple[bool, Optional[Dict[str, Any]]]:
    tgt_path = expected_item["file_path"]
    tgt_cat = expected_item["category"]
    substrings = [s.lower() for s in expected_item.get("evidence_substrings", []) if isinstance(s, str)]
    for item in findings:
        if not isinstance(item, dict):
            continue
        fp = item.get("file_path")
        cat = item.get("category")
        if not isinstance(fp, str) or not isinstance(cat, str):
            continue
        norm_fp = _normalize_rel_path(fp)
        if norm_fp != tgt_path:
            continue
        if cat != tgt_cat:
            continue
        ev = item.get("evidence", "")
        desc = item.get("description", "")
        evl = ev.lower() if isinstance(ev, str) else ""
        descl = desc.lower() if isinstance(desc, str) else ""
        if substrings:
            matched_sub = any((s in evl) or (s in descl) for s in substrings)
        else:
            matched_sub = True
        if matched_sub:
            return True, item
    return False, None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    project_root = workspace / "project"
    output_root = workspace / "output"

    scores: Dict[str, float] = {
        "tree_txt_complete": 0.0,
        "findings_json_parse_and_schema": 0.0,
        "findings_line_field_quality": 0.0,
        "findings_recommended_action_presence": 0.0,
        "findings_expected_coverage": 0.0,
        "findings_line_accuracy_for_covered": 0.0,
        "summary_has_required_sections": 0.0,
        "summary_overview_sentence_count_3_to_5": 0.0,
        "summary_top3_risks_three_bullets": 0.0,
        "summary_quick_wins_bulleted": 0.0,
        "summary_next_steps_bulleted": 0.0,
        "summary_project_specificity": 0.0,
    }

    # tree.txt completeness
    expected_paths = _list_project_paths(project_root)
    produced_tree = output_root / "tree.txt"
    if expected_paths:
        if produced_tree.exists():
            text = _read_text_safe(produced_tree) or ""
            lines = [ln.strip() for ln in text.splitlines()]
            # normalize lines: remove leading './', convert slashes, strip trailing '/'
            norm_lines = set()
            for ln in lines:
                s = _normalize_rel_path(ln)
                s = s.rstrip("/")
                if s and s != ".":
                    norm_lines.add(s)
            # Also strip trailing "/" from expected for comparison
            expected_set = set([p.rstrip("/") for p in expected_paths])
            # Coverage ratio: fraction of expected present
            if len(expected_set) > 0:
                covered = sum(1 for p in expected_set if p in norm_lines)
                scores["tree_txt_complete"] = covered / len(expected_set)
            else:
                scores["tree_txt_complete"] = 0.0
        else:
            scores["tree_txt_complete"] = 0.0
    else:
        # If project is missing (unexpected), set to 0.0
        scores["tree_txt_complete"] = 0.0

    # security_findings.json schema and coverage
    findings_path = output_root / "security_findings.json"
    findings_data = _load_json_safe(findings_path)
    parsed_findings: List[Dict[str, Any]] = []
    if isinstance(findings_data, list):
        parsed_findings = [f for f in findings_data if isinstance(f, dict)]
        schema_score, line_score, rec_score = _validate_findings_schema(parsed_findings)
        scores["findings_json_parse_and_schema"] = schema_score
        scores["findings_line_field_quality"] = line_score
        scores["findings_recommended_action_presence"] = rec_score
    else:
        scores["findings_json_parse_and_schema"] = 0.0
        scores["findings_line_field_quality"] = 0.0
        scores["findings_recommended_action_presence"] = 0.0

    expected_findings = _expected_findings_from_project(project_root)
    if expected_findings and parsed_findings:
        matched = 0
        matched_with_line = 0
        for exp in expected_findings:
            ok, item = _find_match_for_expected(exp, parsed_findings)
            if ok:
                matched += 1
                if item is not None and _line_field_covers(item.get("line"), exp.get("expected_line", -1)):
                    matched_with_line += 1
        total = len(expected_findings)
        scores["findings_expected_coverage"] = matched / total if total else 0.0
        if matched > 0:
            scores["findings_line_accuracy_for_covered"] = matched_with_line / matched
        else:
            scores["findings_line_accuracy_for_covered"] = 0.0
    else:
        scores["findings_expected_coverage"] = 0.0
        scores["findings_line_accuracy_for_covered"] = 0.0

    # summary.md checks
    summary_path = output_root / "summary.md"
    summary_txt = _read_text_safe(summary_path)
    if isinstance(summary_txt, str):
        sections = _parse_summary_sections(summary_txt)
        required_sections = ["Overview", "Top 3 Risks", "Quick Wins", "Next Steps"]
        have_count = sum(1 for s in required_sections if s in sections)
        scores["summary_has_required_sections"] = have_count / len(required_sections)

        # Overview sentences 3-5
        if "Overview" in sections:
            overview_text = "\n".join(sections["Overview"]).strip()
            scount = _count_sentences(overview_text)
            scores["summary_overview_sentence_count_3_to_5"] = 1.0 if 3 <= scount <= 5 else 0.0
        else:
            scores["summary_overview_sentence_count_3_to_5"] = 0.0

        # Bulleted checks
        def bullet_count(lines: List[str]) -> int:
            return sum(1 for ln in lines if re.match(r"^\s*[-\*\+]\s+", ln))

        if "Top 3 Risks" in sections:
            scores["summary_top3_risks_three_bullets"] = 1.0 if bullet_count(sections["Top 3 Risks"]) >= 3 else 0.0
        else:
            scores["summary_top3_risks_three_bullets"] = 0.0

        if "Quick Wins" in sections:
            scores["summary_quick_wins_bulleted"] = 1.0 if bullet_count(sections["Quick Wins"]) >= 1 else 0.0
        else:
            scores["summary_quick_wins_bulleted"] = 0.0

        if "Next Steps" in sections:
            scores["summary_next_steps_bulleted"] = 1.0 if bullet_count(sections["Next Steps"]) >= 1 else 0.0
        else:
            scores["summary_next_steps_bulleted"] = 0.0

        # Specificity: mention at least two project-specific keywords
        keywords = [
            "curl", "helper-tool", "shell=true", "os.system", "admin123", "admin user", "tracker.local",
            "fileshare.local", "http://example.com/install.sh", "http://files.local/helper.sh",
            "auto_update", "watercolor", "123456", "postinstall", "package.json", "build.sh", "analytics",
        ]
        lower_summary = summary_txt.lower()
        hits = sum(1 for k in keywords if k in lower_summary)
        scores["summary_project_specificity"] = 1.0 if hits >= 2 else 0.0
    else:
        # All summary-related scores remain 0.0
        pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()