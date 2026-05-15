import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set


def read_text_safe(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def parse_requirements_yaml_tools(text: str) -> Optional[Dict[str, str]]:
    # Minimal YAML parser tailored to the provided format
    # Looks for a "tools:" section and parses indented "key: "value"" lines.
    tools: Dict[str, str] = {}
    lines = text.splitlines()
    in_tools = False
    base_indent = None
    for i, raw in enumerate(lines):
        line = raw.rstrip("\n")
        # Remove full-line comments
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        if not in_tools:
            # Detect the tools section
            if re.match(r'^\s*tools\s*:\s*$', line):
                in_tools = True
                base_indent = len(line) - len(line.lstrip(" "))
            continue
        else:
            # If dedent to base or less, tools section ends
            indent = len(line) - len(line.lstrip(" "))
            if indent <= (base_indent or 0):
                break
            # Parse key: value lines
            if ":" not in line:
                # Not a key-value; ignore
                continue
            parts = line.strip().split(":", 1)
            key = parts[0].strip()
            val = parts[1].strip()
            # Remove inline comments
            if "#" in val:
                val = val.split("#", 1)[0].strip()
            # Remove surrounding quotes
            if len(val) >= 2 and ((val[0] == val[-1] == '"') or (val[0] == val[-1] == "'")):
                val = val[1:-1]
            # If value is empty (null), skip or set empty
            if key:
                tools[key] = val
    # If we never entered tools or got empty, still return dict (could be empty)
    if in_tools is False:
        # Could not find tools section
        return None
    return tools


def parse_makefile_required_tools(text: str) -> Optional[Set[str]]:
    # Parse REQUIRED_TOOLS assignment (single line expected)
    # Pattern: REQUIRED_TOOLS = convert gs exiftool cwebp
    required: Set[str] = set()
    found = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r'^REQUIRED_TOOLS\s*=\s*(.+)$', line)
        if m:
            rhs = m.group(1)
            tokens = rhs.strip().split()
            for tok in tokens:
                # skip inline comments after tokens if present (unlikely)
                if tok.startswith("#"):
                    break
                required.add(tok)
            found = True
            break
    if not found:
        return None
    return required


def load_json_safe(p: Path) -> Optional[dict]:
    try:
        return json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def normalize_source(val) -> Optional[str]:
    if isinstance(val, str):
        return val.lower()
    if isinstance(val, list) and len(val) == 1 and isinstance(val[0], str):
        return val[0].lower()
    return None


def extract_first_version_pattern(s: str) -> Optional[str]:
    # Find first occurrence of version-like pattern: digits and dots
    if not isinstance(s, str):
        return None
    m = re.search(r'\d+(?:\.\d+)*', s)
    return m.group(0) if m else None


def parse_version_tuple(s: str) -> Optional[Tuple[int, ...]]:
    if s is None:
        return None
    pat = extract_first_version_pattern(s)
    if not pat:
        return None
    try:
        parts = tuple(int(x) for x in pat.split("."))
        return parts
    except Exception:
        return None


def compare_version_tuples(a: Tuple[int, ...], b: Tuple[int, ...]) -> int:
    # Compare lexicographically, padding shorter with zeros
    la = list(a)
    lb = list(b)
    maxlen = max(len(la), len(lb))
    la += [0] * (maxlen - len(la))
    lb += [0] * (maxlen - len(lb))
    if la < lb:
        return -1
    if la > lb:
        return 1
    return 0


def compute_json_counts(data: dict) -> Dict[str, int]:
    counts = {"ok": 0, "missing": 0, "version_below_min": 0, "unknown_version": 0}
    items = data.get("checked", [])
    for it in items:
        status = it.get("status")
        if status in counts:
            counts[status] += 1
    counts["total"] = len(items)
    return counts


def find_number_for_label(text: str, label: str) -> Optional[int]:
    # Look for lines containing label with number
    # Accept patterns like "ok: 3", "ok - 3", "ok 3", "3 ok" not allowed.
    # We search for label then number after it on same line.
    for raw in text.splitlines():
        line = raw.strip()
        if re.search(r'\b' + re.escape(label) + r'\b', line, flags=re.IGNORECASE):
            m = re.search(r'\b' + re.escape(label) + r'\b[^0-9]*(\d+)', line, flags=re.IGNORECASE)
            if m:
                try:
                    return int(m.group(1))
                except Exception:
                    continue
    return None


def get_bullet_lines(text: str) -> List[str]:
    bullets = []
    for raw in text.splitlines():
        if re.match(r'^\s*[-*]\s+', raw):
            bullets.append(raw.strip())
    return bullets


def text_contains_any(text: str, words: List[str]) -> bool:
    for w in words:
        if re.search(r'\b' + re.escape(w) + r'\b', text, flags=re.IGNORECASE):
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "audit_script_present": 0.0,
        "tool_status_json_structure": 0.0,
        "json_union_coverage": 0.0,
        "json_source_and_min_versions": 0.0,
        "json_only_in_lists_correctness": 0.0,
        "json_status_semantics": 0.0,
        "report_exists": 0.0,
        "report_intro_references_engravings": 0.0,
        "report_counts_match_json": 0.0,
        "report_missing_and_below_bullets": 0.0,
        "report_only_in_bullets": 0.0,
        "email_exists": 0.0,
        "email_subject_present": 0.0,
        "email_references_blog_engravings": 0.0,
        "email_actions_aligned_with_findings": 0.0,
    }

    # Inputs
    req_yaml_path = workspace / "input" / "requirements.yaml"
    makefile_path = workspace / "input" / "Makefile"

    req_text = read_text_safe(req_yaml_path)
    mk_text = read_text_safe(makefile_path)
    req_tools: Optional[Dict[str, str]] = None
    mk_tools: Optional[Set[str]] = None

    if req_text is not None:
        req_tools = parse_requirements_yaml_tools(req_text)
    if mk_text is not None:
        mk_tools = parse_makefile_required_tools(mk_text)

    # Deliverable script presence
    py_script = workspace / "scripts" / "audit_toolchain.py"
    sh_script = workspace / "scripts" / "audit_toolchain.sh"
    if py_script.is_file() or sh_script.is_file():
        scores["audit_script_present"] = 1.0

    # JSON report
    json_path = workspace / "out" / "tool_status.json"
    data = load_json_safe(json_path)
    if isinstance(data, dict) and "checked" in data and "only_in_makefile" in data and "only_in_requirements" in data:
        # Basic structure ok
        if isinstance(data.get("checked"), list) and isinstance(data.get("only_in_makefile"), list) and isinstance(data.get("only_in_requirements"), list):
            scores["tool_status_json_structure"] = 1.0

    # If we have both inputs and JSON, proceed with deeper checks
    if req_tools is not None and mk_tools is not None and isinstance(data, dict):
        # Compute expected sets
        yaml_set = set(req_tools.keys())
        make_set = set(mk_tools)
        union_set = yaml_set | make_set
        only_in_make = sorted(list(make_set - yaml_set))
        only_in_req = sorted(list(yaml_set - make_set))

        # json_union_coverage
        try:
            checked_list = data.get("checked", [])
            cmds_in_json = [it.get("command") for it in checked_list if isinstance(it, dict)]
            if None not in cmds_in_json and len(cmds_in_json) == len(checked_list):
                if set(cmds_in_json) == union_set and len(cmds_in_json) == len(set(cmds_in_json)):
                    scores["json_union_coverage"] = 1.0
        except Exception:
            pass

        # json_source_and_min_versions
        try:
            ok_source = True
            checked_list = data.get("checked", [])
            for it in checked_list:
                if not isinstance(it, dict):
                    ok_source = False
                    break
                cmd = it.get("command")
                src = normalize_source(it.get("source"))
                req_min = it.get("required_min_version", None)
                if cmd is None or src not in {"yaml", "makefile", "both"}:
                    ok_source = False
                    break
                in_yaml = cmd in yaml_set
                in_make = cmd in make_set
                exp_src = "both" if in_yaml and in_make else ("yaml" if in_yaml else "makefile")
                if src != exp_src:
                    ok_source = False
                    break
                # required_min_version rules
                exp_min = req_tools.get(cmd) if in_yaml else None
                # JSON may use null for None; Python None is expected
                if exp_min is None:
                    if req_min is not None:
                        ok_source = False
                        break
                else:
                    if not isinstance(req_min, str):
                        ok_source = False
                        break
                    if req_min != exp_min:
                        ok_source = False
                        break
            if ok_source:
                scores["json_source_and_min_versions"] = 1.0
        except Exception:
            pass

        # json_only_in_lists_correctness
        try:
            json_only_make = data.get("only_in_makefile", [])
            json_only_req = data.get("only_in_requirements", [])
            if set(json_only_make) == set(only_in_make) and set(json_only_req) == set(only_in_req):
                scores["json_only_in_lists_correctness"] = 1.0
        except Exception:
            pass

        # json_status_semantics
        try:
            ok_semantics = True
            checked_list = data.get("checked", [])
            for it in checked_list:
                cmd = it.get("command")
                detected = it.get("detected")
                status = it.get("status")
                det_ver = it.get("detected_version", None)
                req_min = it.get("required_min_version", None)

                # Basic type checks
                if cmd is None or not isinstance(detected, bool) or not isinstance(status, str):
                    ok_semantics = False
                    break
                if det_ver is not None and not isinstance(det_ver, str):
                    ok_semantics = False
                    break
                if req_min is not None and not isinstance(req_min, str):
                    ok_semantics = False
                    break

                # Allowed statuses
                if status not in {"ok", "missing", "version_below_min", "unknown_version"}:
                    ok_semantics = False
                    break

                # Consistency checks
                if not detected:
                    # Must be missing
                    if status != "missing":
                        ok_semantics = False
                        break
                    if det_ver is not None:
                        ok_semantics = False
                        break
                    continue

                # detected == True
                # Determine min version if any
                min_tuple = parse_version_tuple(req_min) if req_min is not None else None
                det_tuple = parse_version_tuple(det_ver) if det_ver is not None else None

                if det_tuple is None:
                    # version unknown; acceptable statuses:
                    if min_tuple is None:
                        if status not in {"unknown_version", "ok"}:
                            ok_semantics = False
                            break
                    else:
                        # min exists but version cannot be determined: must be unknown_version
                        if status != "unknown_version":
                            ok_semantics = False
                            break
                else:
                    # version known
                    if min_tuple is None:
                        # No min required; OK to be 'ok'
                        if status not in {"ok", "unknown_version"}:
                            ok_semantics = False
                            break
                    else:
                        cmp = compare_version_tuples(det_tuple, min_tuple)
                        if cmp >= 0:
                            if status != "ok":
                                ok_semantics = False
                                break
                        else:
                            if status != "version_below_min":
                                ok_semantics = False
                                break
            if ok_semantics:
                scores["json_status_semantics"] = 1.0
        except Exception:
            pass

    # report.md checks
    report_path = workspace / "out" / "report.md"
    report_text = read_text_safe(report_path)
    if report_text is not None:
        scores["report_exists"] = 1.0
        # Intro referencing engraving/etching blog workflow
        if (text_contains_any(report_text, ["engraving", "engraver", "etching", "etcher"])
                and text_contains_any(report_text, ["blog", "workflow"])):
            scores["report_intro_references_engravings"] = 1.0

        # Counts match JSON
        if isinstance(data, dict):
            counts = compute_json_counts(data)
            # total, ok, missing, version_below_min, unknown_version
            total_num = find_number_for_label(report_text, "total")
            ok_num = find_number_for_label(report_text, "ok")
            missing_num = find_number_for_label(report_text, "missing")
            below_num = find_number_for_label(report_text, "version_below_min")
            unknown_num = find_number_for_label(report_text, "unknown_version")
            if (total_num == counts.get("total")
                and ok_num == counts.get("ok")
                and missing_num == counts.get("missing")
                and below_num == counts.get("version_below_min")
                and unknown_num == counts.get("unknown_version")):
                scores["report_counts_match_json"] = 1.0

            # Bullet lists for missing and below-min
            bullets = get_bullet_lines(report_text)
            bullets_text = "\n".join(bullets)
            missing_cmds = [it["command"] for it in data.get("checked", []) if it.get("status") == "missing"]
            below_cmds = [it["command"] for it in data.get("checked", []) if it.get("status") == "version_below_min"]
            have_all = True
            for cmd in missing_cmds + below_cmds:
                if not text_contains_any(bullets_text, [cmd]):
                    have_all = False
                    break
            # If there are none to list, consider it satisfied
            if have_all:
                scores["report_missing_and_below_bullets"] = 1.0

            # Bullet lists for only_in_makefile and only_in_requirements
            only_make = data.get("only_in_makefile", [])
            only_req = data.get("only_in_requirements", [])
            have_all_only = True
            for cmd in only_make + only_req:
                if not text_contains_any(bullets_text, [cmd]):
                    have_all_only = False
                    break
            if have_all_only:
                scores["report_only_in_bullets"] = 1.0

    # email_draft.txt checks
    email_path = workspace / "out" / "email_draft.txt"
    email_text = read_text_safe(email_path)
    if email_text is not None:
        scores["email_exists"] = 1.0
        # Subject line
        # Check presence of a line starting with 'Subject:'
        subj_ok = any(re.match(r'^\s*Subject\s*:', ln) for ln in email_text.splitlines())
        if subj_ok:
            scores["email_subject_present"] = 1.0
        # Reference to engraving/etching blog
        if (text_contains_any(email_text, ["engraving", "engraver", "etching", "etcher"])
                and text_contains_any(email_text, ["blog"])):
            scores["email_references_blog_engravings"] = 1.0
        # Actions aligned with findings
        action_ok = False
        if isinstance(data, dict):
            problems = [it["command"] for it in data.get("checked", []) if it.get("status") in {"missing", "version_below_min"}]
            if problems:
                # Require mention of at least one problem command and action verbs
                verbs_present = text_contains_any(email_text, ["install", "upgrade", "update"])
                cmds_present = all(text_contains_any(email_text, [cmd]) for cmd in problems)
                # Be a bit lenient: require verbs and at least one command mentioned
                if verbs_present and (cmds_present or any(text_contains_any(email_text, [cmd]) for cmd in problems)):
                    action_ok = True
            else:
                # No problems: must say the toolchain looks ready
                if text_contains_any(email_text, ["ready", "good to go", "in good shape", "looks good"]):
                    action_ok = True
        if action_ok:
            scores["email_actions_aligned_with_findings"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()