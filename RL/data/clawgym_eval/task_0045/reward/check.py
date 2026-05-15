import json
import re
import sys
import ast
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List, Set


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _snake_to_title(s: str) -> str:
    parts = [p for p in s.replace("-", "_").split("_") if p]
    return " ".join([p.capitalize() for p in parts])


def _parse_simple_yaml_game(path: Path) -> Optional[Dict[str, Any]]:
    """
    Very small YAML parser for the expected config/game.yaml structure:
    - top-level keys: game_name (string), features (mapping), experimental (mapping)
    - booleans true/false
    - simple quoted strings for game_name
    """
    text = _read_text_safe(path)
    if text is None:
        return None

    data: Dict[str, Any] = {}
    current_section: Optional[str] = None

    def parse_value(val: str) -> Any:
        v = val.strip()
        if v == "":
            return None
        if v.lower() == "true":
            return True
        if v.lower() == "false":
            return False
        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            return v[1:-1]
        return v

    lines = text.splitlines()
    for raw_line in lines:
        line = raw_line.split("#", 1)[0].rstrip("\n")
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        # section header like: features:
        if indent == 0 and stripped.endswith(":"):
            key = stripped[:-1].strip()
            current_section = key
            if key not in data:
                data[key] = {}
            continue
        # top-level key with value: game_name: "Grim Quest"
        if indent == 0 and ":" in stripped:
            key, val = stripped.split(":", 1)
            data[key.strip()] = parse_value(val)
            current_section = None
            continue
        # nested key under a section
        if indent > 0 and current_section is not None and ":" in stripped:
            key, val = stripped.split(":", 1)
            key = key.strip()
            value = parse_value(val)
            if isinstance(data.get(current_section), dict):
                data[current_section][key] = value
            else:
                data[current_section] = {key: value}
            continue
        # Otherwise ignore
    return data


def _parse_constants_py(path: Path) -> Optional[Dict[str, Any]]:
    text = _read_text_safe(path)
    if text is None:
        return None
    try:
        tree = ast.parse(text, filename=str(path))
    except Exception:
        return None
    result: Dict[str, Any] = {}
    try:
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in ("VERSION", "FEATURE_FLAGS"):
                        try:
                            value = ast.literal_eval(node.value)
                            result[target.id] = value
                        except Exception:
                            return None
    except Exception:
        return None
    return result


def _extract_release_title_and_version(notes_text: str) -> Tuple[Optional[str], Optional[str]]:
    title_line = None
    version = None
    for line in notes_text.splitlines():
        if re.match(r"^\s*#\s*Release v\d+\.\d+\.\d+\b", line):
            title_line = line.rstrip("\n")
            m = re.search(r"Release v(\d+\.\d+\.\d+)\b", line)
            if m:
                version = m.group(1)
            break
    return title_line, version


def _parse_markdown_sections(notes_text: str) -> Dict[str, List[str]]:
    """
    Parse simple sections with headings like:
    Highlights
    - bullet
    ...
    Experimental
    - bullet
    ...
    Fixes
    text line(s)
    """
    lines = notes_text.splitlines()
    sections: Dict[str, List[str]] = {"highlights": [], "experimental": [], "fixes": []}
    current: Optional[str] = None
    section_names = {"highlights", "experimental", "fixes"}
    for raw in lines:
        line = raw.strip()
        lower = line.lower()
        if lower in section_names:
            current = lower
            continue
        # stop on new top-level markdown header
        if line.startswith("#"):
            current = None
            continue
        if current is None:
            continue
        if current in ("highlights", "experimental"):
            if line.startswith("- "):
                sections[current].append(line[2:].strip())
            # ignore non-bullet in these sections
        elif current == "fixes":
            # collect non-empty lines (could be bullet or sentence)
            if line != "":
                sections[current].append(line)
    return sections


def _compute_claims_from_highlights(highlight_bullets: List[str],
                                    features: Dict[str, bool],
                                    experimental: Dict[str, bool]) -> Tuple[Set[str], Set[str]]:
    """
    Returns: (claimed_stable_titles, claimed_experimental_titles)
    Titles are Title Case versions of the snake_case config keys that matched.
    """
    claimed_stable: Set[str] = set()
    claimed_experimental: Set[str] = set()
    feature_title_map = {k: _snake_to_title(k) for k in (features or {}).keys()}
    experimental_title_map = {k: _snake_to_title(k) for k in (experimental or {}).keys()}
    for bullet in highlight_bullets:
        b_low = bullet.lower()
        is_experimental_claim = "experimental" in b_low
        # Check matches for stable features
        for k, title in feature_title_map.items():
            if title.lower() in b_low:
                if not is_experimental_claim:
                    claimed_stable.add(title)
        # Check matches for experimental items
        if is_experimental_claim:
            for k, title in experimental_title_map.items():
                if title.lower() in b_low:
                    claimed_experimental.add(title)
    return claimed_stable, claimed_experimental


def _compare_title_sets(expected: Set[str], actual_list: List[str]) -> bool:
    exp_norm = {e.lower() for e in expected}
    act_norm = {a.strip().lower() for a in actual_list}
    return exp_norm == act_norm


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "version_synced": 0.0,
        "feature_flags_synced": 0.0,
        "report_json_present_and_valid": 0.0,
        "report_release_version_correct": 0.0,
        "report_feature_flags_after_correct": 0.0,
        "report_claimed_stable_correct": 0.0,
        "report_claimed_experimental_correct": 0.0,
        "report_claimed_but_disabled_correct": 0.0,
        "report_enabled_but_unclaimed_correct": 0.0,
        "report_files_updated_includes_constants": 0.0,
        "report_files_updated_includes_clean_notes": 0.0,
        "clean_notes_title_preserved": 0.0,
        "clean_notes_highlights_enabled_only": 0.0,
        "clean_notes_experimental_items_match": 0.0,
        "clean_notes_fixes_single_sentence": 0.0,
    }

    # Load config
    cfg_path = workspace / "config" / "game.yaml"
    cfg = _parse_simple_yaml_game(cfg_path)
    features: Dict[str, bool] = {}
    experimental: Dict[str, bool] = {}
    if cfg and isinstance(cfg, dict):
        features = cfg.get("features") or {}
        experimental = cfg.get("experimental") or {}
        if not isinstance(features, dict):
            features = {}
        if not isinstance(experimental, dict):
            experimental = {}

    # Load notes
    notes_path = workspace / "notes" / "RELEASE_NOTES.md"
    notes_text = _read_text_safe(notes_path) or ""
    title_line, release_version = _extract_release_title_and_version(notes_text)
    sections = _parse_markdown_sections(notes_text)
    highlights_bullets = sections.get("highlights", [])

    # Compute claims from raw notes
    claimed_stable_exp, claimed_experimental_exp = _compute_claims_from_highlights(highlights_bullets, features, experimental)
    disabled_stable_titles = {_snake_to_title(k) for k, v in features.items() if v is False}
    enabled_stable_titles = {_snake_to_title(k) for k, v in features.items() if v is True}
    claimed_but_disabled_exp = {t for t in claimed_stable_exp if t in disabled_stable_titles}
    enabled_but_unclaimed_exp = {t for t in enabled_stable_titles if t not in claimed_stable_exp}

    # Check src/constants.py sync
    consts_path = workspace / "src" / "constants.py"
    consts = _parse_constants_py(consts_path)
    if consts and isinstance(consts.get("VERSION"), str) and release_version:
        if consts["VERSION"] == release_version:
            scores["version_synced"] = 1.0
    # feature flags synced
    expected_flags = {k: bool(v) for k, v in features.items()}
    if consts and isinstance(consts.get("FEATURE_FLAGS"), dict):
        actual_flags = consts["FEATURE_FLAGS"]
        # Ensure all values are booleans
        if isinstance(actual_flags, dict) and all(isinstance(k, str) for k in actual_flags.keys()) and all(isinstance(v, bool) for v in actual_flags.values()):
            if actual_flags == expected_flags:
                scores["feature_flags_synced"] = 1.0

    # Validate report JSON
    report_path = workspace / "output" / "check_report.json"
    report = None
    report_text = _read_text_safe(report_path)
    if report_text is not None:
        try:
            report = json.loads(report_text)
        except Exception:
            report = None
    if isinstance(report, dict):
        # Basic schema checks
        required_fields = [
            "release_version",
            "feature_flags_before",
            "feature_flags_after",
            "claimed_stable",
            "claimed_experimental",
            "claimed_but_disabled",
            "enabled_but_unclaimed",
            "files_updated",
        ]
        types_ok = True
        for f in required_fields:
            if f not in report:
                types_ok = False
                break
        if types_ok:
            if not isinstance(report.get("release_version"), str):
                types_ok = False
            if not isinstance(report.get("feature_flags_before"), dict):
                types_ok = False
            if not isinstance(report.get("feature_flags_after"), dict):
                types_ok = False
            if not isinstance(report.get("claimed_stable"), list):
                types_ok = False
            if not isinstance(report.get("claimed_experimental"), list):
                types_ok = False
            if not isinstance(report.get("claimed_but_disabled"), list):
                types_ok = False
            if not isinstance(report.get("enabled_but_unclaimed"), list):
                types_ok = False
            if not isinstance(report.get("files_updated"), list):
                types_ok = False
        if types_ok:
            scores["report_json_present_and_valid"] = 1.0

        # release_version check
        if isinstance(report.get("release_version"), str) and release_version:
            if report["release_version"] == release_version:
                scores["report_release_version_correct"] = 1.0

        # feature_flags_after check
        rffa = report.get("feature_flags_after")
        if isinstance(rffa, dict):
            # Ensure all values booleans
            if all(isinstance(k, str) for k in rffa.keys()) and all(isinstance(v, bool) for v in rffa.values()):
                if rffa == expected_flags:
                    scores["report_feature_flags_after_correct"] = 1.0

        # claimed stable and experimental checks
        r_cs = report.get("claimed_stable")
        if isinstance(r_cs, list):
            if _compare_title_sets(claimed_stable_exp, r_cs):
                scores["report_claimed_stable_correct"] = 1.0

        r_ce = report.get("claimed_experimental")
        if isinstance(r_ce, list):
            if _compare_title_sets(claimed_experimental_exp, r_ce):
                scores["report_claimed_experimental_correct"] = 1.0

        # claimed_but_disabled and enabled_but_unclaimed
        r_cbd = report.get("claimed_but_disabled")
        if isinstance(r_cbd, list):
            if _compare_title_sets(claimed_but_disabled_exp, r_cbd):
                scores["report_claimed_but_disabled_correct"] = 1.0
        r_ebu = report.get("enabled_but_unclaimed")
        if isinstance(r_ebu, list):
            if _compare_title_sets(enabled_but_unclaimed_exp, r_ebu):
                scores["report_enabled_but_unclaimed_correct"] = 1.0

        # files_updated inclusion checks
        files_updated = report.get("files_updated")
        if isinstance(files_updated, list):
            fu_set = {str(x) for x in files_updated if isinstance(x, str)}
            if "src/constants.py" in fu_set or str(consts_path) in fu_set:
                scores["report_files_updated_includes_constants"] = 1.0
            clean_notes_rel = "output/RELEASE_NOTES_CLEAN.md"
            clean_notes_abs = str(workspace / clean_notes_rel)
            if clean_notes_rel in fu_set or clean_notes_abs in fu_set:
                scores["report_files_updated_includes_clean_notes"] = 1.0

    # Validate cleaned notes
    clean_notes_path = workspace / "output" / "RELEASE_NOTES_CLEAN.md"
    clean_text = _read_text_safe(clean_notes_path) or ""
    if clean_text:
        clean_sections = _parse_markdown_sections(clean_text)
        clean_lines = clean_text.splitlines()
        # title preserved
        if title_line is not None and len(clean_lines) > 0:
            if clean_lines[0].rstrip("\n") == title_line:
                scores["clean_notes_title_preserved"] = 1.0

        # Highlights enabled only
        clean_highlights = clean_sections.get("highlights", [])
        # Build expected set from enabled features
        expected_enabled_titles = {_snake_to_title(k) for k, v in features.items() if v is True}
        # Build set detected in cleaned highlights: features whose title appears in bullet
        detected_clean_highlights: Set[str] = set()
        for b in clean_highlights:
            b_low = b.lower()
            for t in expected_enabled_titles:
                if t.lower() in b_low:
                    detected_clean_highlights.add(t)
        # Ensure disabled titles are not present
        disabled_titles = {_snake_to_title(k) for k, v in features.items() if v is False}
        disabled_mentioned = False
        for b in clean_highlights:
            b_low = b.lower()
            for t in disabled_titles:
                if t.lower() in b_low:
                    disabled_mentioned = True
                    break
            if disabled_mentioned:
                break
        if detected_clean_highlights == expected_enabled_titles and not disabled_mentioned:
            scores["clean_notes_highlights_enabled_only"] = 1.0

        # Experimental section match
        clean_experimental = clean_sections.get("experimental", [])
        expected_experimental_titles = {_snake_to_title(k) for k, v in experimental.items() if v is True}
        detected_clean_experimental: Set[str] = set()
        for b in clean_experimental:
            b_low = b.lower()
            for t in expected_experimental_titles:
                if t.lower() in b_low:
                    detected_clean_experimental.add(t)
        # Ensure false experimental not mentioned
        false_experimental_titles = {_snake_to_title(k) for k, v in experimental.items() if v is False}
        exp_disabled_mentioned = False
        for b in clean_experimental:
            b_low = b.lower()
            for t in false_experimental_titles:
                if t.lower() in b_low:
                    exp_disabled_mentioned = True
                    break
            if exp_disabled_mentioned:
                break
        if detected_clean_experimental == expected_experimental_titles and not exp_disabled_mentioned:
            scores["clean_notes_experimental_items_match"] = 1.0

        # Fixes single sentence
        clean_fixes = clean_sections.get("fixes", [])
        nonempty_fixes = [l for l in clean_fixes if l.strip() != ""]
        if len(nonempty_fixes) == 1:
            only_line = nonempty_fixes[0]
            # Must not be a bullet
            if not only_line.strip().startswith("- "):
                scores["clean_notes_fixes_single_sentence"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()