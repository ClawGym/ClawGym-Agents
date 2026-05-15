import json
import re
import sys
import csv
from pathlib import Path
import ast
from typing import List, Dict, Any, Optional, Tuple


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_read_lines(path: Path) -> List[str]:
    txt = read_text(path)
    if txt is None:
        return []
    return txt.splitlines()


def parse_python(text: str) -> Optional[ast.AST]:
    try:
        return ast.parse(text)
    except Exception:
        return None


def get_function_node(tree: ast.AST, name: str) -> Optional[ast.FunctionDef]:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def get_function_source(text: str, func: ast.FunctionDef) -> str:
    lines = text.splitlines()
    start = getattr(func, "lineno", 1) - 1
    end = getattr(func, "end_lineno", func.lineno)
    end = max(end, start + 1)
    return "\n".join(lines[start:end])


def has_docstring(func: ast.FunctionDef) -> bool:
    try:
        doc = ast.get_docstring(func)
        return bool(doc and doc.strip())
    except Exception:
        return False


def has_type_hints(func: ast.FunctionDef) -> bool:
    ret_annotated = func.returns is not None
    params = [a for a in func.args.args]
    params_annotated = all(a.annotation is not None for a in params)
    return ret_annotated and params_annotated


def uses_utils_load_songs(text: str) -> bool:
    if re.search(r"\bfrom\s+utils\s+import\s+load_songs\b", text):
        return True
    if re.search(r"\bimport\s+utils\b", text) and re.search(r"\butils\.load_songs\s*\(", text):
        return True
    return False


def has_duplicate_loader_in_setlist(text: str) -> bool:
    return bool(re.search(r"\bdef\s+load_songs\s*\(", text))


def utils_loader_exposes_bpm_and_accepts_tempo(text: str) -> bool:
    tree = parse_python(text)
    if tree is None:
        return False
    func = get_function_node(tree, "load_songs")
    if func is None:
        return False
    src = get_function_source(text, func)
    assigns_bpm = bool(re.search(r"row\s*\[\s*['\"]bpm['\"]\s*\]\s*=", src))
    references_tempo = "tempo" in src
    references_bpm = "bpm" in src
    has_int_cast = "int(" in src or "int (" in src
    return assigns_bpm and references_tempo and references_bpm and has_int_cast


def calculate_set_duration_uses_duration_min(text: str) -> bool:
    tree = parse_python(text)
    if tree is None:
        return False
    func = get_function_node(tree, "calculate_set_duration")
    if func is None:
        return False
    src = get_function_source(text, func)
    no_seconds = "duration_sec" not in src
    no_div60 = not re.search(r"/\s*60", src) and not re.search(r"//\s*60", src)
    uses_duration_min = "duration_min" in src
    return no_seconds and no_div60 and uses_duration_min


def config_tempo_unit_is_bpm(path: Path) -> bool:
    lines = safe_read_lines(path)
    for line in lines:
        m = re.match(r"^\s*tempo_unit\s*:\s*(\S+)\s*$", line)
        if m:
            return m.group(1).strip().lower() == "bpm"
    return False


def compute_top3_and_missing(csv_path: Path) -> Tuple[List[Tuple[str, int]], List[Tuple[str, str]]]:
    top_candidates: List[Tuple[str, int]] = []
    missing: List[Tuple[str, str]] = []
    try:
        with csv_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            for row in rows:
                title = (row.get("title") or "").strip()
                tempo_val = row.get("bpm") if "bpm" in row and (row.get("bpm") or "").strip() != "" else row.get("tempo", "")
                bpm_num: Optional[int] = None
                if tempo_val is not None and str(tempo_val).strip() != "":
                    try:
                        bpm_num = int(float(tempo_val))
                    except Exception:
                        bpm_num = None
                if bpm_num is not None:
                    top_candidates.append((title, bpm_num))
                key_val = row.get("key", "")
                if not key_val or str(key_val).strip() == "":
                    missing.append((title, "key"))
                if bpm_num is None:
                    missing.append((title, "tempo"))
    except Exception:
        return [], []
    top_sorted = sorted(top_candidates, key=lambda x: x[1], reverse=True)
    return top_sorted[:3], missing


def normalize_heading(line: str) -> str:
    s = line.strip()
    s = re.sub(r"^#+\s*", "", s)
    s = s.strip().rstrip(":").strip()
    return s.lower()


def find_section_ranges(lines: List[str], required_sections: List[str]) -> Dict[str, Tuple[int, int]]:
    indices: Dict[str, int] = {}
    for i, ln in enumerate(lines):
        nh = normalize_heading(ln)
        for name in required_sections:
            if nh == name.lower():
                if name.lower() not in indices:
                    indices[name.lower()] = i
    ranges: Dict[str, Tuple[int, int]] = {}
    heading_positions = sorted(indices.items(), key=lambda kv: kv[1])
    for idx, (name, start) in enumerate(heading_positions):
        if idx + 1 < len(heading_positions):
            end = heading_positions[idx + 1][1]
        else:
            end = len(lines)
        ranges[name] = (start, end)
    return ranges


def is_bullet_line(s: str) -> bool:
    stripped = s.strip()
    if not stripped:
        return False
    if stripped.startswith(("-", "*", "•", "–")):
        return True
    if re.match(r"^\s*\d+[\.\)]\s+", s):
        return True
    return False


def extract_bullets(lines: List[str]) -> List[str]:
    return [ln.strip() for ln in lines if is_bullet_line(ln)]


def section_lines(lines: List[str], section_ranges: Dict[str, Tuple[int, int]], name: str) -> List[str]:
    rng = section_ranges.get(name.lower())
    if not rng:
        return []
    start, end = rng
    return lines[start + 1 : end]


def findings_cover_requirements(bullets: List[str]) -> bool:
    joined_lower = "\n".join(bullets).lower()
    has_duplicate_loader = ("duplicate" in joined_lower and ("loader" in joined_lower or "load_songs" in joined_lower)) or ("removed" in joined_lower and "load_songs" in joined_lower)
    has_bpm_standardization = ("bpm" in joined_lower and ("unit" in joined_lower or "standard" in joined_lower or "standardize" in joined_lower or "normalize" in joined_lower or "tempo" in joined_lower))
    has_duration_fix = ("duration" in joined_lower and ("fix" in joined_lower or "minutes" in joined_lower or "duration_min" in joined_lower))
    return has_duplicate_loader and has_bpm_standardization and has_duration_fix


def practice_focus_top3_correct(lines: List[str], expected_top3: List[Tuple[str, int]]) -> bool:
    line_indices: List[int] = []
    for title, bpm in expected_top3:
        idx = -1
        for i, ln in enumerate(lines):
            if (title.lower() in ln.lower()) and (str(bpm) in ln):
                idx = i
                break
        if idx == -1:
            return False
        line_indices.append(idx)
    return line_indices == sorted(line_indices)


def contains_missing_entry(lines: List[str], title: str, field: str) -> bool:
    for ln in lines:
        lnl = ln.lower()
        if title.lower() in lnl:
            if field == "key":
                if ("missing" in lnl and "key" in lnl) or "no key" in lnl:
                    return True
            if field in ("tempo", "bpm"):
                if ("missing" in lnl and ("tempo" in lnl or "bpm" in lnl)) or "no tempo" in lnl or "no bpm" in lnl:
                    return True
    return False


def action_items_owner_and_counts(bullets: List[str]) -> Tuple[bool, int]:
    count = len(bullets)
    all_have_owner = True
    for b in bullets:
        b_stripped = b.rstrip()
        m = re.search(r"\(([^()]*)\)\s*$", b_stripped)
        if not m:
            all_have_owner = False
            break
        owner = m.group(1).strip().lower()
        if owner not in ("dad", "son"):
            all_have_owner = False
            break
    return all_have_owner, count


def count_code_followup_bullets(bullets: List[str]) -> int:
    keywords = [
        "code", "refactor", "utils", "setlist", "config", "test", "type hint",
        "docstring", "loader", "bpm", "duration", "function", "yaml", "lint", "ci", "module", "script", "src/"
    ]
    cnt = 0
    for b in bullets:
        bl = b.lower()
        if any(kw in bl for kw in keywords):
            cnt += 1
    return cnt


def count_rehearsal_bullets_referencing_songs(bullets: List[str], songs: List[str]) -> int:
    cnt = 0
    for b in bullets:
        bl = b.lower()
        if any(title.lower() in bl for title in songs):
            cnt += 1
    return cnt


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "setlist_no_duplicate_loader": 0.0,
        "setlist_imports_utils_loader": 0.0,
        "utils_loader_bpm_normalization": 0.0,
        "utils_loader_type_hints_and_docstring": 0.0,
        "calculate_set_duration_uses_duration_min": 0.0,
        "calculate_set_duration_type_hints_and_docstring": 0.0,
        "config_tempo_unit_bpm": 0.0,
        "notes_sections_present": 0.0,
        "findings_cover_key_points": 0.0,
        "practice_focus_top3_correct": 0.0,
        "practice_focus_missing_list_correct": 0.0,
        "action_items_min4_with_owners": 0.0,
        "action_items_code_followups_min2": 0.0,
        "action_items_rehearsal_refs_min2": 0.0,
    }

    setlist_path = workspace / "src" / "setlist.py"
    utils_path = workspace / "src" / "utils.py"
    config_path = workspace / "config" / "settings.yaml"
    notes_path = workspace / "docs" / "meeting_notes_father_son.md"
    data_csv_path = workspace / "data" / "songs.csv"

    setlist_text = read_text(setlist_path)
    if setlist_text:
        scores["setlist_no_duplicate_loader"] = 1.0 if not has_duplicate_loader_in_setlist(setlist_text) else 0.0
        scores["setlist_imports_utils_loader"] = 1.0 if uses_utils_load_songs(setlist_text) else 0.0
        scores["calculate_set_duration_uses_duration_min"] = 1.0 if calculate_set_duration_uses_duration_min(setlist_text) else 0.0
        tree = parse_python(setlist_text)
        if tree is not None:
            func = get_function_node(tree, "calculate_set_duration")
            if func is not None and has_docstring(func) and has_type_hints(func):
                scores["calculate_set_duration_type_hints_and_docstring"] = 1.0

    utils_text = read_text(utils_path)
    normalization_ok = False
    if utils_text:
        if utils_loader_exposes_bpm_and_accepts_tempo(utils_text):
            scores["utils_loader_bpm_normalization"] = 1.0
            normalization_ok = True
        tree_u = parse_python(utils_text)
        if tree_u is not None:
            func_u = get_function_node(tree_u, "load_songs")
            if normalization_ok and func_u is not None and has_docstring(func_u) and has_type_hints(func_u):
                scores["utils_loader_type_hints_and_docstring"] = 1.0

    if config_path.exists():
        scores["config_tempo_unit_bpm"] = 1.0 if config_tempo_unit_is_bpm(config_path) else 0.0

    notes_lines = safe_read_lines(notes_path)
    required_sections = ["Agenda", "Codebase Findings", "Practice Focus", "Action Items"]
    section_ranges = find_section_ranges(notes_lines, required_sections)
    if all(s.lower() in section_ranges for s in [sec for sec in required_sections]):
        scores["notes_sections_present"] = 1.0

    expected_top3: List[Tuple[str, int]] = []
    expected_missing: List[Tuple[str, str]] = []
    if data_csv_path.exists():
        expected_top3, expected_missing = compute_top3_and_missing(data_csv_path)

    findings_lines = section_lines(notes_lines, section_ranges, "Codebase Findings")
    findings_bullets = extract_bullets(findings_lines)
    if findings_bullets and findings_cover_requirements(findings_bullets):
        scores["findings_cover_key_points"] = 1.0

    practice_lines = section_lines(notes_lines, section_ranges, "Practice Focus")
    if expected_top3 and practice_focus_top3_correct(practice_lines, expected_top3):
        scores["practice_focus_top3_correct"] = 1.0

    missing_ok = True
    if expected_missing:
        for title, field in expected_missing:
            if field == "tempo":
                ok = contains_missing_entry(practice_lines, title, "tempo") or contains_missing_entry(practice_lines, title, "bpm")
            else:
                ok = contains_missing_entry(practice_lines, title, field)
            if not ok:
                missing_ok = False
                break
    else:
        missing_ok = False
    scores["practice_focus_missing_list_correct"] = 1.0 if missing_ok else 0.0

    action_lines = section_lines(notes_lines, section_ranges, "Action Items")
    action_bullets = extract_bullets(action_lines)
    owners_ok, count_bullets = action_items_owner_and_counts(action_bullets)
    if owners_ok and count_bullets >= 4:
        scores["action_items_min4_with_owners"] = 1.0

    if count_code_followup_bullets(action_bullets) >= 2:
        scores["action_items_code_followups_min2"] = 1.0

    top_titles = [t for (t, _b) in expected_top3]
    if top_titles and count_rehearsal_bullets_referencing_songs(action_bullets, top_titles) >= 2:
        scores["action_items_rehearsal_refs_min2"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()