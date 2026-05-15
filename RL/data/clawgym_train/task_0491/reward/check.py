import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _read_text_safe(path: Path) -> Tuple[bool, str]:
    try:
        return True, path.read_text(encoding="utf-8")
    except Exception:
        return False, ""


def _load_json_safe(path: Path) -> Tuple[bool, Optional[dict]]:
    ok, txt = _read_text_safe(path)
    if not ok:
        return False, None
    try:
        return True, json.loads(txt)
    except Exception:
        return False, None


def _parse_simple_yaml_top_level(path: Path) -> Tuple[bool, Optional[dict]]:
    ok, txt = _read_text_safe(path)
    if not ok:
        return False, None
    data: Dict[str, object] = {}
    current_list_key: Optional[str] = None
    for raw_line in txt.splitlines():
        line = raw_line.rstrip("\n")
        if not line.strip():
            # blank line; maintain current_list_key to allow multi-line lists
            continue
        # list item
        if current_list_key is not None:
            m_item = re.match(r"^\s*-\s*(.*)$", line)
            if m_item:
                item = m_item.group(1).strip()
                if (item.startswith('"') and item.endswith('"')) or (item.startswith("'") and item.endswith("'")):
                    item = item[1:-1]
                if not isinstance(data.get(current_list_key), list):
                    data[current_list_key] = []
                assert isinstance(data[current_list_key], list)
                data[current_list_key].append(item)
                continue
            # if we reach a non-list item, reset list context and continue parsing as key
            current_list_key = None
        # key: value or key:
        m = re.match(r"^([A-Za-z0-9_]+)\s*:\s*(.*)$", line)
        if m:
            key = m.group(1).strip()
            rest = m.group(2)
            if rest == "":
                # possible start of list or nested mapping (we only handle list)
                current_list_key = key
                data[key] = []
                continue
            val = rest.strip()
            # strip quotes if present
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            data[key] = val
        # ignore anything else (comments or unsupported)
    return True, data


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def _is_single_sentence(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if not re.search(r"[.!?]\s*$", stripped):
        return False
    count = len(re.findall(r"[.!?]", stripped))
    return count == 1


def _extract_subject_and_body(email_text: str) -> Tuple[Optional[str], List[str]]:
    lines = email_text.splitlines()
    if not lines:
        return None, []
    first = lines[0].strip()
    if not re.match(r"^Subject\s*:", first, flags=re.IGNORECASE):
        return None, lines
    subj = first.split(":", 1)[1].strip()
    return subj, lines[1:]


def _find_action_items_indices(lines: List[str]) -> Tuple[int, int, int]:
    # returns (header_index, first_bullet_idx, last_bullet_idx) or (-1, -1, -1)
    header_idx = -1
    for i, ln in enumerate(lines):
        if ln.strip().lower().startswith("action items:"):
            header_idx = i
            break
    if header_idx == -1:
        return -1, -1, -1
    first_bullet = -1
    last_bullet = -1
    for j in range(header_idx + 1, len(lines)):
        s = lines[j].strip()
        if re.match(r"^[-*]\s+", s):
            if first_bullet == -1:
                first_bullet = j
            last_bullet = j
        elif s == "":
            continue
        else:
            if first_bullet != -1:
                break
            else:
                break
    if first_bullet == -1:
        return header_idx, -1, -1
    return header_idx, first_bullet, last_bullet


def _check_signature_and_disclaimer(lines: List[str], expected_signature_lines: List[str], expected_disclaimer: str) -> bool:
    indices = [i for i, ln in enumerate(lines) if ln.strip() == "Thanks,"]
    if not indices:
        return False
    start = indices[-1]
    sig_lines: List[str] = []
    i = start + 1
    while i < len(lines) and len(sig_lines) < len(expected_signature_lines):
        if lines[i].strip() != "":
            sig_lines.append(lines[i].rstrip("\n"))
        i += 1
    if sig_lines != expected_signature_lines:
        return False
    last_non_empty = ""
    for ln in lines[::-1]:
        if ln.strip() != "":
            last_non_empty = ln.strip()
            break
    if last_non_empty != expected_disclaimer:
        return False
    return True


def _check_director_buffer_request(body_text: str) -> bool:
    t = body_text.lower()
    has_date = "2026-05-04" in body_text
    has_buffer = "buffer" in t
    has_15_minute = bool(re.search(r"\b15\s*[- ]?\s*minute\b", t)) or "15-min" in t or "15min" in t
    has_closeups = bool(re.search(r"close[- ]?ups?", t))
    return has_date and has_buffer and has_15_minute and has_closeups


def _get_addendum_section(text: str) -> Optional[str]:
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        norm = re.sub(r"^#+\s*", "", ln.strip())
        if norm == "Addendum v1.1 — Skin Safety Updates":
            return "\n".join(lines[i:])
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "config_mobile_updated": 0.0,
        "config_signature_lines_exact": 0.0,
        "config_disclaimer_appended": 0.0,
        "config_tone_signoff_updated": 0.0,
        "config_core_fields_preserved": 0.0,
        "makeup_email_exists": 0.0,
        "makeup_email_subject_requirements": 0.0,
        "makeup_email_structure_and_length": 0.0,
        "makeup_email_products_exact": 0.0,
        "makeup_email_patch_test_datetime": 0.0,
        "makeup_email_signature_and_disclaimer": 0.0,
        "director_email_exists": 0.0,
        "director_email_subject_requirements": 0.0,
        "director_email_structure_and_length": 0.0,
        "director_email_buffer_request": 0.0,
        "director_email_signature_and_disclaimer": 0.0,
        "director_email_product_name_consistency": 0.0,
        "protocol_v1_1_exists": 0.0,
        "protocol_contains_original_prefix": 0.0,
        "addendum_section_present": 0.0,
        "addendum_allowed_products_listed": 0.0,
        "addendum_avoid_products_listed": 0.0,
        "addendum_removal_steps_present": 0.0,
        "addendum_patch_test_line": 0.0,
        "addendum_prepared_by_line": 0.0,
    }

    cfg_path = workspace / "config" / "email_profile.yaml"
    makeup_email_path = workspace / "output" / "emails" / "makeup_dept_email.txt"
    director_email_path = workspace / "output" / "emails" / "director_ad_email.txt"
    protocol_v1_path = workspace / "input" / "docs" / "protocol_current.md"
    protocol_v11_path = workspace / "output" / "docs" / "protocol_v1.1.md"

    expected_mobile = "+1 (747) 555-0199"
    base_disclaimer = "This message may contain confidential production information."
    appended_sentence = "Makeup and prosthetics must comply with union skin safety guidelines."
    expected_disclaimer = base_disclaimer + " " + appended_sentence
    expected_signature_lines = [
        "Kade Bannon",
        "Lead Actor | 'Iron Meridian'",
        "SAG-AFTRA Member",
        "Mobile: +1 (747) 555-0199",
    ]
    expected_tone = "professional-warm"
    expected_signoff = "Thanks"

    cfg_ok, cfg = _parse_simple_yaml_top_level(cfg_path)
    if cfg_ok and isinstance(cfg, dict):
        if cfg.get("mobile") == expected_mobile:
            scores["config_mobile_updated"] = 1.0
        sig = cfg.get("signature_lines")
        if isinstance(sig, list) and all(isinstance(x, str) for x in sig) and sig == expected_signature_lines:
            scores["config_signature_lines_exact"] = 1.0
        if isinstance(cfg.get("disclaimer"), str) and cfg.get("disclaimer") == expected_disclaimer:
            scores["config_disclaimer_appended"] = 1.0
        if cfg.get("tone") == expected_tone and cfg.get("signoff") == expected_signoff:
            scores["config_tone_signoff_updated"] = 1.0
        # Only award preserved fields if the required updates are present (to avoid baseline credit)
        if (
            scores["config_mobile_updated"] == 1.0
            and scores["config_signature_lines_exact"] == 1.0
            and scores["config_disclaimer_appended"] == 1.0
            and scores["config_tone_signoff_updated"] == 1.0
            and cfg.get("name") == "Kade Bannon"
            and cfg.get("role") == "Lead Actor"
            and cfg.get("project_title") == "Iron Meridian"
        ):
            scores["config_core_fields_preserved"] = 1.0

    # Makeup email checks
    makeup_ok, makeup_text = _read_text_safe(makeup_email_path)
    if makeup_ok:
        scores["makeup_email_exists"] = 1.0
        subj, body_lines = _extract_subject_and_body(makeup_text)
        body_text = "\n".join(body_lines)
        if subj is not None:
            if ("2026-05-03" in subj) and (re.search(r"\bpatch test\b", subj, flags=re.IGNORECASE) is not None):
                scores["makeup_email_subject_requirements"] = 1.0
        structure_ok = False
        length_ok = False
        context_idx = -1
        for i, ln in enumerate(body_lines):
            if ln.strip() != "":
                context_idx = i
                break
        if context_idx != -1 and _is_single_sentence(body_lines[context_idx]):
            header_idx, first_bullet, last_bullet = _find_action_items_indices(body_lines[context_idx + 1 :])
            if header_idx != -1 and first_bullet != -1 and last_bullet != -1:
                header_abs = context_idx + 1 + header_idx
                first_abs = context_idx + 1 + first_bullet
                last_abs = context_idx + 1 + last_bullet
                bullets_count = sum(
                    1 for j in range(first_abs, last_abs + 1) if re.match(r"^\s*[-*]\s+", body_lines[j].strip())
                )
                closing_line = ""
                for j in range(last_abs + 1, len(body_lines)):
                    s = body_lines[j].strip()
                    if s == "":
                        continue
                    if s == "Thanks,":
                        break
                    if s in expected_signature_lines or s == expected_disclaimer:
                        break
                    closing_line = s
                    break
                if bullets_count >= 2 and closing_line and _is_single_sentence(closing_line):
                    structure_ok = True
        words = _word_count(body_text)
        if words <= 180:
            length_ok = True
        if structure_ok and length_ok:
            scores["makeup_email_structure_and_length"] = 1.0
        if all(p in makeup_text for p in ["ProSkin Bond", "AquaFix Foam", "CitrusFX Remover"]):
            scores["makeup_email_products_exact"] = 1.0
        if "2026-05-03 07:00" in makeup_text:
            scores["makeup_email_patch_test_datetime"] = 1.0
        if _check_signature_and_disclaimer(body_lines, expected_signature_lines, expected_disclaimer):
            scores["makeup_email_signature_and_disclaimer"] = 1.0

    # Director/AD email checks
    director_ok, director_text = _read_text_safe(director_email_path)
    if director_ok:
        scores["director_email_exists"] = 1.0
        subj, body_lines = _extract_subject_and_body(director_text)
        body_text = "\n".join(body_lines)
        if subj is not None:
            if ("2026-05-04" in subj) and (re.search(r"\bbuffer\b", subj, flags=re.IGNORECASE) is not None):
                scores["director_email_subject_requirements"] = 1.0
        structure_ok = False
        length_ok = False
        context_idx = -1
        for i, ln in enumerate(body_lines):
            if ln.strip() != "":
                context_idx = i
                break
        if context_idx != -1 and _is_single_sentence(body_lines[context_idx]):
            header_idx, first_bullet, last_bullet = _find_action_items_indices(body_lines[context_idx + 1 :])
            if header_idx != -1 and first_bullet != -1 and last_bullet != -1:
                header_abs = context_idx + 1 + header_idx
                first_abs = context_idx + 1 + first_bullet
                last_abs = context_idx + 1 + last_bullet
                bullets_count = sum(
                    1 for j in range(first_abs, last_abs + 1) if re.match(r"^\s*[-*]\s+", body_lines[j].strip())
                )
                closing_line = ""
                for j in range(last_abs + 1, len(body_lines)):
                    s = body_lines[j].strip()
                    if s == "":
                        continue
                    if s == "Thanks,":
                        break
                    if s in expected_signature_lines or s == expected_disclaimer:
                        break
                    closing_line = s
                    break
                if bullets_count >= 2 and closing_line and _is_single_sentence(closing_line):
                    structure_ok = True
        words = _word_count(body_text)
        if words <= 180:
            length_ok = True
        if structure_ok and length_ok:
            scores["director_email_structure_and_length"] = 1.0
        if _check_director_buffer_request(body_text):
            scores["director_email_buffer_request"] = 1.0
        if _check_signature_and_disclaimer(body_lines, expected_signature_lines, expected_disclaimer):
            scores["director_email_signature_and_disclaimer"] = 1.0
        t_low = director_text.lower()
        consistency_ok = True
        roots_to_full = {
            "proskin": "ProSkin Bond",
            "aquafix": "AquaFix Foam",
            "citrusfx": "CitrusFX Remover",
            "ultrahold": "UltraHold Black",
        }
        for root, full in roots_to_full.items():
            if root in t_low and full not in director_text:
                consistency_ok = False
                break
        if consistency_ok:
            scores["director_email_product_name_consistency"] = 1.0

    # Protocol addendum checks
    v11_ok, v11_text = _read_text_safe(protocol_v11_path)
    if v11_ok:
        scores["protocol_v1_1_exists"] = 1.0
        v1_ok, v1_text = _read_text_safe(protocol_v1_path)
        if v1_ok and v11_text.startswith(v1_text):
            scores["protocol_contains_original_prefix"] = 1.0
        addendum_text = _get_addendum_section(v11_text)
        if addendum_text is not None:
            scores["addendum_section_present"] = 1.0
            if all(p in addendum_text for p in ["ProSkin Bond", "AquaFix Foam", "CitrusFX Remover"]):
                scores["addendum_allowed_products_listed"] = 1.0
            if "UltraHold Black" in addendum_text:
                scores["addendum_avoid_products_listed"] = 1.0
            step_lines = [ln for ln in addendum_text.splitlines() if re.match(r"^\s*\d+\.\s+", ln)]
            steps_present = (
                any(ln.strip().startswith("1.") for ln in step_lines)
                and any(ln.strip().startswith("2.") for ln in step_lines)
                and any(ln.strip().startswith("3.") for ln in step_lines)
                and any(ln.strip().startswith("4.") for ln in step_lines)
            )
            details_ok = all(k in addendum_text for k in ["CitrusFX Remover", "60", "roll", "clean"])
            if steps_present and details_ok:
                scores["addendum_removal_steps_present"] = 1.0
            if "2026-05-03 07:00" in addendum_text:
                scores["addendum_patch_test_line"] = 1.0
            prepared_by_expected = "Prepared by Kade Bannon (Lead Actor) | Mobile: +1 (747) 555-0199"
            if prepared_by_expected in addendum_text:
                scores["addendum_prepared_by_line"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()