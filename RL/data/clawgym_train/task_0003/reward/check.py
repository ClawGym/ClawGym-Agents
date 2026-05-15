import json
import csv
import sys
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_file(path: Path) -> Optional[Any]:
    try:
        text = read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def parse_scalar(val: str) -> Any:
    v = val.strip()
    if len(v) >= 2 and ((v[0] == '"' and v[-1] == '"') or (v[0] == "'" and v[-1] == "'")):
        return v[1:-1]
    low = v.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if re.fullmatch(r"-?\d+", v):
        try:
            return int(v)
        except Exception:
            pass
    if re.fullmatch(r"-?\d+\.\d+", v):
        try:
            return float(v)
        except Exception:
            pass
    return v


def simple_yaml_load(text: str) -> Optional[Dict[str, Any]]:
    try:
        raw_lines = text.splitlines()
        processed: List[Tuple[int, str]] = []
        for line in raw_lines:
            stripped = line.rstrip("\n")
            if "#" in stripped:
                # Simple remove comments: everything after # is comment if not within a quote (heuristic)
                m = re.match(r'^(.*?)(?<!")#.*$', stripped)
                if m:
                    stripped = m.group(1)
            if stripped.strip() == "":
                continue
            indent = len(re.match(r"^ *", stripped).group(0))
            content = stripped.strip()
            processed.append((indent, content))

        root: Dict[str, Any] = {}
        stack: List[Tuple[int, Any]] = [(-1, root)]
        i = 0
        n = len(processed)
        while i < n:
            indent, content = processed[i]
            while len(stack) > 0 and indent <= stack[-1][0]:
                stack.pop()
            if not stack:
                return None
            parent = stack[-1][1]

            if content.startswith("- "):
                if not isinstance(parent, list):
                    return None
                item_str = content[2:].strip()
                if item_str == "":
                    return None
                parent.append(parse_scalar(item_str))
            else:
                if ":" not in content:
                    return None
                key, rest = content.split(":", 1)
                key = key.strip()
                rest = rest.strip()
                if rest == "":
                    # Determine container type by peeking next line
                    j = i + 1
                    next_container: Any = {}
                    if j < n:
                        next_indent, next_content = processed[j]
                        if next_indent > indent and next_content.startswith("- "):
                            next_container = []
                        else:
                            next_container = {}
                    if isinstance(parent, dict):
                        parent[key] = next_container
                    else:
                        return None
                    stack.append((indent, next_container))
                else:
                    val = parse_scalar(rest)
                    if isinstance(parent, dict):
                        parent[key] = val
                    else:
                        return None
            i += 1
        return root
    except Exception:
        return None


def load_yaml_file(path: Path) -> Optional[Dict[str, Any]]:
    text = read_text(path)
    if text is None:
        return None
    return simple_yaml_load(text)


def load_glossary_csv(path: Path) -> Optional[Dict[str, str]]:
    try:
        text = read_text(path)
        if text is None:
            return None
        lines = text.splitlines()
        reader = csv.DictReader(lines)
        headers = [h.lower().strip() for h in (reader.fieldnames or [])]
        if "english" not in headers or "spanish" not in headers:
            return None
        eng_field = reader.fieldnames[headers.index("english")]
        spa_field = reader.fieldnames[headers.index("spanish")]
        mapping: Dict[str, str] = {}
        for row in reader:
            if row is None:
                return None
            eng = (row.get(eng_field) or "").strip()
            spa = (row.get(spa_field) or "").strip()
            if eng == "":
                return None
            mapping[eng] = spa
        return mapping
    except Exception:
        return None


def compute_expected_es_values(
    site_cfg: Dict[str, Any],
    en_json: Dict[str, Any],
    glossary: Dict[str, str],
) -> Tuple[List[str], Dict[str, str], Dict[str, str]]:
    required_keys: List[str] = []
    expected_values: Dict[str, str] = {}
    review_reasons: Dict[str, str] = {}

    i18n = site_cfg.get("i18n", {}) if isinstance(site_cfg, dict) else {}
    req = i18n.get("signage_keys_required", []) if isinstance(i18n, dict) else []
    if isinstance(req, list):
        required_keys = req[:]
    else:
        required_keys = []

    for key in required_keys:
        if key not in en_json or not isinstance(en_json.get(key), str):
            expected_values[key] = "REVIEW: MISSING_ENGLISH_TEXT"
            review_reasons[key] = "Missing English source string"
        else:
            en_text = en_json[key]
            if en_text in glossary and glossary[en_text] != "":
                expected_values[key] = glossary[en_text]
            else:
                expected_values[key] = f"REVIEW: {en_text}"
                review_reasons[key] = "Missing glossary mapping"
    return required_keys, expected_values, review_reasons


def classify_translations(expected_values: Dict[str, str]) -> Tuple[List[str], List[str]]:
    translated: List[str] = []
    review: List[str] = []
    for k, v in expected_values.items():
        if isinstance(v, str) and v.startswith("REVIEW:"):
            review.append(k)
        else:
            translated.append(k)
    return translated, review


def extract_bullets_after_heading(text: str, keyword: str) -> List[str]:
    lines = text.splitlines()
    bullets: List[str] = []
    found = False
    for idx, line in enumerate(lines):
        if not found and keyword.lower() in line.lower():
            found = True
            j = idx + 1
            while j < len(lines):
                l = lines[j]
                if l.strip().startswith(("-", "*")):
                    bullets.append(l.strip())
                    j += 1
                    continue
                if l.strip() == "":
                    break
                # Stop on potential new section
                if not l.startswith(" ") and (l.strip().endswith(":") or ":" in l or l.strip().istitle()):
                    break
                if bullets:
                    bullets[-1] += " " + l.strip()
                j += 1
            break
    return bullets


def line_contains_all(line: str, terms: List[str]) -> bool:
    low = line.lower()
    return all(t.lower() in low for t in terms)


def find_counts_line_number(text: str, keywords: List[str]) -> Optional[int]:
    for line in text.splitlines():
        if line_contains_all(line, keywords):
            nums = re.findall(r"\d+", line)
            if nums:
                try:
                    return int(nums[0])
                except Exception:
                    return None
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "es_json_exists": 0.0,
        "es_json_parseable": 0.0,
        "es_json_keys_match_required": 0.0,
        "es_json_values_correct": 0.0,
        "meeting_notes_exists": 0.0,
        "meeting_notes_context_includes_festival_and_bilingual": 0.0,
        "meeting_notes_languages_enabled_and_spanish_status": 0.0,
        "meeting_notes_status_counts_correct": 0.0,
        "meeting_notes_lists_translated_and_review_keys_present": 0.0,
        "meeting_notes_review_reasons_present": 0.0,
        "meeting_notes_action_items_content_ops": 0.0,
        "meeting_notes_action_items_signage_ops": 0.0,
    }

    # Paths
    site_yaml_path = workspace / "input" / "site_config.yaml"
    en_json_path = workspace / "input" / "i18n" / "en.json"
    glossary_csv_path = workspace / "input" / "glossary.csv"
    es_json_path = workspace / "output" / "i18n" / "es.json"
    notes_md_path = workspace / "output" / "meeting_notes.md"

    # Load inputs
    site_cfg = load_yaml_file(site_yaml_path) or {}
    en_json = load_json_file(en_json_path) or {}
    glossary_map = load_glossary_csv(glossary_csv_path) or {}

    # Prepare expected values if inputs loaded (only if all are meaningful)
    required_keys: List[str] = []
    expected_values: Dict[str, str] = {}
    review_reasons: Dict[str, str] = {}
    translated_keys_expected: List[str] = []
    review_keys_expected: List[str] = []

    if site_cfg and en_json and glossary_map is not None:
        required_keys, expected_values, review_reasons = compute_expected_es_values(site_cfg, en_json, glossary_map)
        translated_keys_expected, review_keys_expected = classify_translations(expected_values)

    # Derived config values for meeting notes
    i18n_cfg = site_cfg.get("i18n", {}) if isinstance(site_cfg, dict) else {}
    languages_enabled: List[str] = i18n_cfg.get("languages_enabled", []) if isinstance(i18n_cfg, dict) else []
    spanish_enabled = "es" in languages_enabled
    fest = site_cfg.get("festival", {}) if isinstance(site_cfg, dict) else {}
    festival_name = fest.get("name")
    participant_estimate = fest.get("participant_count_estimate")
    owners = site_cfg.get("owners", {}) if isinstance(site_cfg, dict) else {}
    content_owner = owners.get("content_ops")
    signage_owner = owners.get("signage_ops")
    constraints = site_cfg.get("constraints", {}) if isinstance(site_cfg, dict) else {}
    translation_deadline_days = constraints.get("translation_deadline_days")

    # Check es.json
    if es_json_path.exists():
        scores["es_json_exists"] = 1.0
        es_data = load_json_file(es_json_path)
        if isinstance(es_data, dict):
            scores["es_json_parseable"] = 1.0
            if required_keys:
                if set(es_data.keys()) == set(required_keys):
                    scores["es_json_keys_match_required"] = 1.0
                values_ok = True
                for k in required_keys:
                    if k not in es_data:
                        values_ok = False
                        break
                    if expected_values.get(k) != es_data.get(k):
                        values_ok = False
                        break
                if values_ok and required_keys:
                    scores["es_json_values_correct"] = 1.0

    # meeting_notes checks
    if notes_md_path.exists():
        scores["meeting_notes_exists"] = 1.0
        notes_text = read_text(notes_md_path) or ""
        notes_low = notes_text.lower()

        # Context
        ctx_ok = True
        if not (festival_name and str(festival_name) in notes_text):
            ctx_ok = False
        if not (participant_estimate is not None and str(participant_estimate) in notes_text):
            ctx_ok = False
        if not ("bilingual" in notes_low and "signage" in notes_low):
            ctx_ok = False
        if ctx_ok:
            scores["meeting_notes_context_includes_festival_and_bilingual"] = 1.0

        # Languages enabled and Spanish enabled
        lang_ok = True
        # Require listing enabled languages from config
        if isinstance(languages_enabled, list) and languages_enabled:
            for lang in languages_enabled:
                if str(lang) not in notes_text:
                    lang_ok = False
        else:
            lang_ok = False
        # Require explicit note about Spanish enabled or not
        if spanish_enabled:
            if not (("spanish" in notes_low or "es" in notes_low) and "enable" in notes_low):
                lang_ok = False
        else:
            # If Spanish not enabled, should indicate it's not enabled
            if not (("spanish" in notes_low or "es" in notes_low) and ("not enable" in notes_low or "disable" in notes_low)):
                lang_ok = False
        if lang_ok:
            scores["meeting_notes_languages_enabled_and_spanish_status"] = 1.0

        # Status counts
        counts_ok = True
        total_expected = len(required_keys)
        translated_expected = len(translated_keys_expected)
        review_expected = len(review_keys_expected)
        total_found = find_counts_line_number(notes_text, ["total", "required"])
        translated_found = find_counts_line_number(notes_text, ["translat"])
        review_found = find_counts_line_number(notes_text, ["review"])
        if total_found != total_expected or translated_found != translated_expected or review_found != review_expected:
            counts_ok = False
        if counts_ok and total_expected + translated_expected + review_expected >= 0:
            scores["meeting_notes_status_counts_correct"] = 1.0

        # Bullet lists for translated and review keys
        lists_ok = True
        translated_bullets = extract_bullets_after_heading(notes_text, "translated")
        review_bullets = extract_bullets_after_heading(notes_text, "review")
        translated_present: set = set()
        review_present: set = set()
        for line in translated_bullets:
            for k in required_keys:
                if k in line:
                    translated_present.add(k)
        for line in review_bullets:
            for k in required_keys:
                if k in line:
                    review_present.add(k)
        if set(translated_keys_expected) != translated_present or set(review_keys_expected) != review_present:
            lists_ok = False
        if lists_ok and (translated_keys_expected or review_keys_expected):
            scores["meeting_notes_lists_translated_and_review_keys_present"] = 1.0

        # Review reasons present
        reasons_ok = True
        if review_keys_expected:
            if not review_bullets:
                reasons_ok = False
            else:
                for k in review_keys_expected:
                    found_reason = False
                    for line in review_bullets:
                        if k in line and (("Missing English source string" in line) or ("Missing glossary mapping" in line)):
                            found_reason = True
                            break
                    if not found_reason:
                        reasons_ok = False
                        break
        else:
            # No review items expected; reasons section not required; keep false to avoid accidental reward
            reasons_ok = False
        if reasons_ok:
            scores["meeting_notes_review_reasons_present"] = 1.0

        # Action items: Content Ops
        action_bullets = extract_bullets_after_heading(notes_text, "action")
        content_ok = False
        if action_bullets and content_owner:
            for line in action_bullets:
                if content_owner in line:
                    has_translation_ref = ("translat" in line.lower()) or ("review" in line.lower())
                    deadline_ok = False
                    if translation_deadline_days is not None:
                        if str(translation_deadline_days) in line and ("day" in line.lower() or "deadline" in line.lower()):
                            deadline_ok = True
                    has_output_ref = "output/i18n/es.json" in line
                    if has_translation_ref and deadline_ok and has_output_ref:
                        content_ok = True
                        break
        if content_ok:
            scores["meeting_notes_action_items_content_ops"] = 1.0

        # Action items: Signage Ops
        signage_ok = False
        if action_bullets and signage_owner:
            for line in action_bullets:
                if signage_owner in line:
                    has_print_ref = "print" in line.lower()
                    has_output_ref = "output/i18n/es.json" in line
                    if has_print_ref and has_output_ref:
                        signage_ok = True
                        break
        if signage_ok:
            scores["meeting_notes_action_items_signage_ops"] = 1.0

    return scores


def main() -> None:
    args = sys.argv[1:]
    workspace = args[0] if args else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()