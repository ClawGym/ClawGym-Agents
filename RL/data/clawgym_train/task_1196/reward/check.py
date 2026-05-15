import json
import re
import sys
from pathlib import Path
from typing import Optional, Tuple, Dict, List, Any


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith("'") and s.endswith("'")) or (s.startswith('"') and s.endswith('"')):
        return s[1:-1]
    return s


def _leading_spaces_count(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _parse_settings_yaml(text: str) -> Optional[Dict[str, Any]]:
    # Minimal parser for the specific known structure of settings.yaml
    if text is None:
        return None
    lines = text.splitlines()
    settings: Dict[str, Any] = {}
    target: Dict[str, Any] = {}
    report: Dict[str, Any] = {}
    sections: List[str] = []

    in_target = False
    target_indent = None

    in_report = False
    report_indent = None

    in_sections = False
    sections_indent = None

    for i, raw in enumerate(lines):
        line = raw.rstrip("\n")
        # Skip comments and empty lines
        if not line.strip() or line.strip().startswith("#"):
            continue

        indent = _leading_spaces_count(line)
        stripped = line.strip()

        # Exit nested blocks on dedent
        if in_sections and indent <= (sections_indent if sections_indent is not None else 0):
            in_sections = False
            sections_indent = None
        if in_report and indent <= (report_indent if report_indent is not None else 0) and not stripped.startswith("sections:"):
            # exiting report block
            in_report = False
            report_indent = None
        if in_target and indent <= (target_indent if target_indent is not None else 0):
            in_target = False
            target_indent = None

        # Detect entering blocks
        if not in_target and not in_report and stripped.startswith("target:"):
            in_target = True
            target_indent = indent
            continue
        if not in_report and stripped.startswith("report:"):
            in_report = True
            report_indent = indent
            continue

        # Within sections list
        if in_sections:
            # list item expected: "- item"
            m_item = re.match(r"^\s*-\s+(.*)$", line)
            if m_item:
                val = _strip_quotes(m_item.group(1).strip())
                if val:
                    sections.append(val)
                continue
            else:
                # End of sections list if we encounter non-list at same/higher indent
                in_sections = False
                sections_indent = None

        # Within target block
        if in_target and indent > (target_indent if target_indent is not None else 0):
            # key: value
            m = re.match(r"^\s*([A-Za-z0-9_]+)\s*:\s*(.*)$", line)
            if m:
                key = m.group(1).strip()
                val = _strip_quotes(m.group(2).strip())
                if key == "id":
                    try:
                        target[key] = int(val) if val != "" else None
                    except Exception:
                        target[key] = None
                else:
                    target[key] = val
            continue

        # Within report block
        if in_report and indent > (report_indent if report_indent is not None else 0):
            # detect sections:
            if stripped.startswith("sections:"):
                in_sections = True
                sections_indent = indent
                continue
            m = re.match(r"^\s*([A-Za-z0-9_]+)\s*:\s*(.*)$", line)
            if m:
                key = m.group(1).strip()
                val = _strip_quotes(m.group(2).strip())
                report[key] = val
            continue

        # Top-level scalars
        mtop = re.match(r"^\s*([A-Za-z0-9_]+)\s*:\s*(.*)$", line)
        if mtop:
            key = mtop.group(1).strip()
            val = _strip_quotes(mtop.group(2).strip())
            settings[key] = val

    if target:
        settings["target"] = target
    if report or sections:
        if sections:
            report["sections"] = sections
        settings["report"] = report
    return settings


def _parse_requirements_names(text: Optional[str]) -> set:
    names = set()
    if not text:
        return names
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Split off comments at end
        if " #" in line:
            line = line.split(" #", 1)[0].strip()
        # Extract package name before version spec and extras
        # Split on version separators
        for sep in ["==", ">=", "<=", "~=", "!=", ">", "<", "==="]:
            if sep in line:
                line = line.split(sep, 1)[0].strip()
                break
        # Remove extras in brackets: package[extra]
        base = line.split("[", 1)[0].strip()
        # Remove environment markers with ';'
        base = base.split(";", 1)[0].strip()
        if base:
            names.add(base.lower())
    return names


def _normalize_packages_mapping(packages_field: Any) -> Dict[str, str]:
    """
    Normalize 'packages' field into a mapping: name(lower) -> version(str).
    Accepts:
    - dict mapping names to versions
    - list of strings like "name==version" or "name version"
    - list of dicts with keys name/version
    """
    result: Dict[str, str] = {}
    if isinstance(packages_field, dict):
        for k, v in packages_field.items():
            if isinstance(k, str) and isinstance(v, (str, int, float)):
                result[k.lower()] = str(v)
    elif isinstance(packages_field, list):
        for item in packages_field:
            if isinstance(item, str):
                # Try to split by '==', or space
                if "==" in item:
                    name, ver = item.split("==", 1)
                    result[name.strip().lower()] = ver.strip()
                else:
                    parts = item.strip().split()
                    if len(parts) >= 2:
                        result[parts[0].strip().lower()] = parts[1].strip()
            elif isinstance(item, dict):
                name = None
                ver = None
                # possible keys: name, version
                for k, v in item.items():
                    kl = str(k).lower()
                    if kl == "name":
                        name = str(v)
                    elif kl in ("version", "ver"):
                        ver = str(v)
                if name and ver:
                    result[name.strip().lower()] = ver.strip()
    return result


def _get_python_version(snapshot: Dict[str, Any]) -> Optional[str]:
    if not isinstance(snapshot, dict):
        return None
    # direct key "python.version"
    if "python.version" in snapshot and isinstance(snapshot["python.version"], str):
        return snapshot["python.version"]
    # nested mapping
    py = snapshot.get("python")
    if isinstance(py, dict) and isinstance(py.get("version"), str):
        return py.get("version")
    return None


def _parse_markdown_sections(md_text: Optional[str]) -> Tuple[List[str], Dict[str, str]]:
    """
    Returns (ordered_section_titles, section_bodies_map)
    Section titles are extracted from markdown heading lines (# ...).
    Bodies are the text between this heading and the next heading (or end of doc).
    """
    if md_text is None:
        return [], {}
    lines = md_text.splitlines()
    headings: List[Tuple[str, int]] = []
    for idx, raw in enumerate(lines):
        m = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", raw)
        if m:
            title = m.group(1).strip()
            headings.append((title, idx))
    ordered = [t for t, _ in headings]
    bodies: Dict[str, str] = {}
    for i, (title, start_idx) in enumerate(headings):
        end_idx = len(lines)
        if i + 1 < len(headings):
            end_idx = headings[i + 1][1]
        # Body is lines between start_idx+1 and end_idx
        body = "\n".join(lines[start_idx + 1 : end_idx]).strip()
        bodies[title] = body
    return ordered, bodies


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "settings_project_and_identity": 0.0,
        "settings_target_fields": 0.0,
        "settings_report_fields_and_sections": 0.0,
        "requirements_contains_dependencies": 0.0,
        "fetch_script_no_notimplemented": 0.0,
        "env_snapshot_basic_structure": 0.0,
        "env_snapshot_contains_required_packages": 0.0,
        "rfc_headings_json_valid_structure": 0.0,
        "rfc_headings_json_source_values": 0.0,
        "report_sections_exact": 0.0,
        "report_context_contains_required_phrases": 0.0,
        "report_environment_reports_version_and_packages": 0.0,
        "report_web_extraction_reports_title_and_count": 0.0,
        "report_verification_marks_checks_correctly": 0.0,
    }

    # Paths
    settings_path = workspace / "config" / "settings.yaml"
    requirements_path = workspace / "requirements.txt"
    fetch_script_path = workspace / "scripts" / "fetch_and_extract.py"
    env_snapshot_path = workspace / "output" / "env_snapshot.json"
    report_md_path = workspace / "output" / "deployment_report.md"
    rfc_json_path = workspace / "output" / "rfc2324_headings.json"

    # Load settings
    settings_text = _read_text_safe(settings_path)
    settings = _parse_settings_yaml(settings_text) if settings_text is not None else None

    # 1) Configuration updates checks
    if settings:
        proj_ok = settings.get("project_name") == "atlani-notebook"
        dancer_ok = settings.get("dancer_name") == "Claire Durand"
        insp_ok = settings.get("inspiration") == "Catherine May Atlani"
        out_ok = settings.get("output_dir") == "output"
        if proj_ok and dancer_ok and insp_ok and out_ok:
            scores["settings_project_and_identity"] = 1.0

        t = settings.get("target") if isinstance(settings.get("target"), dict) else {}
        t_domain_ok = t.get("domain") == "rfc-editor.org"
        t_type_ok = t.get("type") == "rfc"
        try:
            t_id_val = t.get("id")
            t_id_ok = int(t_id_val) == 2324
        except Exception:
            t_id_ok = False
        if t_domain_ok and t_type_ok and t_id_ok:
            scores["settings_target_fields"] = 1.0

        r = settings.get("report") if isinstance(settings.get("report"), dict) else {}
        r_file_ok = r.get("filename") == "deployment_report.md"
        sections = r.get("sections") if isinstance(r.get("sections"), list) else None
        expected_sections = ["Context", "Environment", "Web Extraction", "Verification"]
        sections_ok = sections == expected_sections
        if r_file_ok and sections_ok:
            scores["settings_report_fields_and_sections"] = 1.0
    else:
        # settings missing or unparseable: keep 0.0
        pass

    # 2) requirements.txt
    req_text = _read_text_safe(requirements_path)
    req_names = _parse_requirements_names(req_text)
    if {"pyyaml", "requests", "beautifulsoup4"}.issubset(req_names):
        scores["requirements_contains_dependencies"] = 1.0

    # 3) fetch script implemented minimally (no NotImplementedError)
    script_text = _read_text_safe(fetch_script_path)
    if script_text is not None:
        has_notimpl = "NotImplementedError" in script_text
        # Also ensure the stub functions exist by name
        required_funcs = ["def load_settings", "def fetch_html", "def extract_headings", "def write_json", "def run"]
        funcs_present = all(fn in script_text for fn in required_funcs)
        if (not has_notimpl) and funcs_present:
            scores["fetch_script_no_notimplemented"] = 1.0

    # 4) env_snapshot.json existence and structure
    env_snapshot = _load_json_safe(env_snapshot_path)
    env_struct_ok = False
    env_packages_ok = False
    python_version = None
    packages_map: Dict[str, str] = {}
    if isinstance(env_snapshot, dict):
        python_version = _get_python_version(env_snapshot)
        packages_field = env_snapshot.get("packages")
        packages_map = _normalize_packages_mapping(packages_field)
        if isinstance(python_version, str) and python_version.strip() and isinstance(packages_field, (dict, list)):
            env_struct_ok = True
        # Must include at least PyYAML, requests, beautifulsoup4
        required_pkgs = {"pyyaml", "requests", "beautifulsoup4"}
        if required_pkgs.issubset(set(packages_map.keys())):
            env_packages_ok = True
    if env_struct_ok:
        scores["env_snapshot_basic_structure"] = 1.0
    if env_packages_ok:
        scores["env_snapshot_contains_required_packages"] = 1.0

    # 5) rfc2324_headings.json structure and source fields
    rfc_json = _load_json_safe(rfc_json_path)
    rfc_struct_ok = False
    rfc_source_ok = False
    title_value = None
    headings_list: List[str] = []
    if isinstance(rfc_json, dict):
        title_value = rfc_json.get("title")
        headings_val = rfc_json.get("headings")
        source_val = rfc_json.get("source")
        if isinstance(title_value, str) and isinstance(headings_val, list) and all(isinstance(h, str) for h in headings_val):
            rfc_struct_ok = True
            headings_list = headings_val
        if isinstance(source_val, dict):
            domain_ok = source_val.get("domain") == "rfc-editor.org"
            try:
                id_ok = int(source_val.get("id")) == 2324
            except Exception:
                id_ok = False
            if domain_ok and id_ok:
                rfc_source_ok = True
    if rfc_struct_ok:
        scores["rfc_headings_json_valid_structure"] = 1.0
    if rfc_source_ok:
        scores["rfc_headings_json_source_values"] = 1.0

    # 6) deployment_report.md checks
    report_text = _read_text_safe(report_md_path)
    ordered_sections, bodies = _parse_markdown_sections(report_text)

    expected_order = ["Context", "Environment", "Web Extraction", "Verification"]
    if ordered_sections == expected_order and len(ordered_sections) == 4:
        scores["report_sections_exact"] = 1.0

    # Context content
    context_ok = False
    context_body = bodies.get("Context", "") if bodies else ""
    if context_body:
        lower = context_body.lower()
        if ("french contemporary dancer" in lower and
                "catherine may atlani" in lower and
                "reproducible" in lower and
                "rehearsal notebook" in lower):
            context_ok = True
    if context_ok:
        scores["report_context_contains_required_phrases"] = 1.0

    # Environment section content
    env_section_ok = False
    env_body = bodies.get("Environment", "") if bodies else ""
    if env_body and python_version and packages_map:
        # must include python version and reference to env snapshot path and at least 3 packages with versions from snapshot
        has_version = python_version in env_body
        has_snapshot_path = "output/env_snapshot.json" in env_body
        # Count packages with version mentioned
        pkg_mentions = 0
        # iterate through packages_map items, but prefer to match a variety, not only required three
        for name, ver in packages_map.items():
            if not name or not ver:
                continue
            # search for "name ... ver" on same line/body
            pattern = re.compile(rf"\b{re.escape(name)}\b[^\n]*{re.escape(ver)}", flags=re.IGNORECASE)
            if pattern.search(env_body):
                pkg_mentions += 1
            if pkg_mentions >= 3:
                break
        if has_version and has_snapshot_path and pkg_mentions >= 3:
            env_section_ok = True
    if env_section_ok:
        scores["report_environment_reports_version_and_packages"] = 1.0

    # Web Extraction section content
    webext_ok = False
    web_body = bodies.get("Web Extraction", "") if bodies else ""
    if web_body and isinstance(title_value, str) and isinstance(headings_list, list):
        has_path = "output/rfc2324_headings.json" in web_body
        has_title = title_value in web_body if title_value else False
        count = len(headings_list)
        # Look for the number as a standalone number in the section
        has_count = re.search(rf"\b{count}\b", web_body) is not None
        if has_path and has_title and has_count:
            webext_ok = True
    if webext_ok:
        scores["report_web_extraction_reports_title_and_count"] = 1.0

    # Verification section content
    verification_ok = False
    ver_body = bodies.get("Verification", "") if bodies else ""
    if ver_body and settings:
        # compute actual artifact statuses
        report_filename_ok = False
        r = settings.get("report") if isinstance(settings.get("report"), dict) else {}
        if r.get("filename") == "deployment_report.md":
            report_filename_ok = True
        # JSON filename matches pattern rfc{target.id}_headings.json using config id
        t = settings.get("target") if isinstance(settings.get("target"), dict) else {}
        try:
            cfg_id = int(t.get("id"))
        except Exception:
            cfg_id = None
        expected_json_name = None
        json_name_ok = False
        if cfg_id is not None:
            expected_json_name = f"rfc{cfg_id}_headings.json"
            # It should exist under output
            json_path = workspace / "output" / expected_json_name
            json_name_ok = json_path.exists()
        # Now verify that the section includes two explicit checks marked OK/FAIL matching actual statuses.
        # We require lines mentioning these checks with correct markers.
        lines = ver_body.splitlines()
        check1_text_found = False
        check1_marker_ok = False
        check2_text_found = False
        check2_marker_ok = False

        for line in lines:
            ll = line.lower()
            if ("report.filename" in ll and "deployment_report.md" in ll):
                check1_text_found = True
                if report_filename_ok and ("ok" in ll):
                    check1_marker_ok = True
                if (not report_filename_ok) and ("fail" in ll):
                    check1_marker_ok = True
            if expected_json_name:
                if (expected_json_name.lower() in ll or "json filename" in ll):
                    check2_text_found = True
                    if json_name_ok and ("ok" in ll):
                        check2_marker_ok = True
                    if (not json_name_ok) and ("fail" in ll):
                        check2_marker_ok = True

        if check1_text_found and check1_marker_ok and check2_text_found and check2_marker_ok:
            verification_ok = True

    if verification_ok:
        scores["report_verification_marks_checks_correctly"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()