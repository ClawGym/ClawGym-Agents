import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _read_text(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def _strip_comments(line: str) -> str:
    out = []
    in_quotes = False
    i = 0
    while i < len(line):
        c = line[i]
        if c == '"':
            in_quotes = not in_quotes
            out.append(c)
            i += 1
            continue
        if c == "#" and not in_quotes:
            break
        out.append(c)
        i += 1
    return "".join(out).rstrip("\n")


def _parse_glossary_yaml(text: str) -> Optional[Dict]:
    if text is None:
        return None
    lines = [_strip_comments(l.rstrip()) for l in text.splitlines()]
    banner = None
    expand_first = None
    acronyms: Dict[str, Dict[str, str]] = {}
    in_acronyms = False
    current_acr = None
    current_en = None
    current_fr = None

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            continue
        m_banner = re.match(r'^\s*classification_banner:\s*(?:"([^"]*)"|(.*))\s*$', line)
        if m_banner and not in_acronyms:
            banner = (m_banner.group(1) or m_banner.group(2) or "").strip()
            banner = banner.strip('" ').strip()
            continue
        m_expand = re.match(r'^\s*expand_first_occurrence:\s*(true|false)\s*$', line, flags=re.I)
        if m_expand and not in_acronyms:
            expand_first = m_expand.group(1).lower() == "true"
            continue
        if re.match(r'^\s*acronyms:\s*$', line):
            in_acronyms = True
            current_acr = None
            current_en = None
            current_fr = None
            continue

        if in_acronyms:
            m_acr = re.match(r'^\s{2}([A-Za-z0-9_-]+):\s*$', line)
            if m_acr:
                if current_acr is not None and current_en is not None and current_fr is not None:
                    acronyms[current_acr] = {"en": current_en, "fr": current_fr}
                current_acr = m_acr.group(1)
                current_en = None
                current_fr = None
                continue
            m_lang = re.match(r'^\s{4}(en|fr):\s*(?:"([^"]*)"|(.*))\s*$', line)
            if m_lang and current_acr:
                lang = m_lang.group(1)
                val = (m_lang.group(2) or m_lang.group(3) or "").strip()
                val = val.strip('" ').strip()
                if lang == "en":
                    current_en = val
                elif lang == "fr":
                    current_fr = val
                if current_en is not None and current_fr is not None:
                    acronyms[current_acr] = {"en": current_en, "fr": current_fr}
                continue
            if re.match(r'^\S', line):
                in_acronyms = False

    if in_acronyms and (current_acr is not None) and (current_en is not None) and (current_fr is not None):
        acronyms[current_acr] = {"en": current_en, "fr": current_fr}

    return {"classification_banner": banner, "expand_first_occurrence": expand_first, "acronyms": acronyms}


def _first_line(s: str) -> str:
    return s.splitlines()[0] if s else ""


def _find_section_lines(text: str, section_label: str) -> List[str]:
    if text is None:
        return []
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() == f"{section_label}:":
            start = i + 1
            break
    if start is None:
        return []
    collected: List[str] = []
    for j in range(start, len(lines)):
        l = lines[j]
        if l.strip().endswith(":") and l.strip().isalpha():
            break
        collected.append(l)
    return collected


def _extract_summary(text: str) -> str:
    lines = _find_section_lines(text, "Summary")
    summary_lines = []
    for l in lines:
        if not l.strip():
            break
        if l.strip().endswith(":") and l.strip().isalpha():
            break
        summary_lines.append(l)
    summary_lines = [ln.strip() for ln in summary_lines if ln is not None]
    return " ".join([ln for ln in summary_lines if ln])


def _extract_decisions_bullets(text: str) -> List[str]:
    lines = _find_section_lines(text, "Decisions")
    bullets = []
    for l in lines:
        ls = l.strip()
        if ls.startswith("- ") or ls.startswith("* "):
            bullets.append(ls[2:].strip())
    return bullets


def _extract_action_items(text: str) -> List[Dict[str, str]]:
    lines = _find_section_lines(text, "Action Items")
    items: List[Dict[str, str]] = []
    for l in lines:
        if " | " in l:
            parts = [p.strip() for p in l.split("|")]
            if len(parts) == 3:
                owner, task, due = parts
                items.append({"owner": owner, "task": task, "due": due})
    return items


def _parse_transcript_expectations(text: str) -> Tuple[List[str], List[Dict[str, str]]]:
    decisions: List[str] = []
    actions: List[Dict[str, str]] = []
    if text is None:
        return decisions, actions
    for raw in text.splitlines():
        line = raw.strip()
        m_dec = re.search(r'\bDECISION:\s*(.+)$', line)
        if m_dec:
            decisions.append(m_dec.group(1).strip())
        m_act = re.search(r'\bACTION:\s*([A-Za-z][A-Za-z.\- ]*)\s+to\s+(.+?)\s+(before|by)\s+(\d{4}-\d{2}-\d{2})\.?$', line)
        if m_act:
            owner = m_act.group(1).strip()
            task = m_act.group(2).strip()
            due = m_act.group(4).strip()
            actions.append({"owner": owner, "task": task, "due": due})
    return decisions, actions


def _normalize_text(s: str) -> str:
    return re.sub(r'\s+', ' ', s.lower()).strip()


def _count_words(s: str) -> int:
    tokens = re.findall(r'\b\w+\b', s)
    return len(tokens)


def _check_first_occurrence_expansions(content: str, acronyms_map: Dict[str, Dict[str, str]], acronyms: List[str], lang: str, require_presence: bool) -> Tuple[int, int]:
    ok = 0
    total = 0
    for acr in acronyms:
        if acr not in acronyms_map:
            continue
        expansion = acronyms_map[acr].get(lang, "")
        if not expansion:
            continue
        expected = f"{acr} ({expansion})"
        acr_present = acr in content
        if require_presence and not acr_present:
            total += 1
            continue
        if not require_presence and not acr_present:
            continue
        total += 1
        count_expanded = content.count(expected)
        if count_expanded == 1:
            ok += 1
    return ok, total


def _extract_digit_sequences(s: str) -> List[str]:
    if not s:
        return []
    return re.findall(r'\b\d{1,4}(?:-\d{1,4})*\b', s)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "config_banner_unchanged": 0.0,
        "config_expand_first_true": 0.0,
        "config_existing_acronyms_intact": 0.0,
        "config_vlf_mapping_added": 0.0,
        "notes_banner_first_line": 0.0,
        "notes_summary_length_and_one_paragraph": 0.0,
        "notes_decisions_capture": 0.0,
        "notes_action_items_lines": 0.0,
        "notes_acronym_first_occurrence_expansions": 0.0,
        "co_banner_first_line": 0.0,
        "co_word_count_limit": 0.0,
        "co_acronym_first_occurrence_expansions": 0.0,
        "co_preserve_numbers_and_terms": 0.0,
        "allied_en_banner_first_line": 0.0,
        "allied_en_word_count_limit": 0.0,
        "allied_en_acronym_first_occurrence_expansions": 0.0,
        "allied_fr_banner_first_line": 0.0,
        "allied_fr_acronym_first_occurrence_expansions": 0.0,
        "allied_fr_numbers_dates_preserved": 0.0,
        "allied_fr_sentence_alignment": 0.0,
    }

    # Load config
    config_path = workspace / "config" / "glossary.yaml"
    config_text = _read_text(config_path)
    config = None
    if config_text is not None:
        config = _parse_glossary_yaml(config_text)

    expected_banner = "UNCLASSIFIED // TRAINING USE ONLY"
    expected_expand_first = True
    expected_existing = {
        "ASW": {"en": "anti-submarine warfare", "fr": "lutte anti-sous-marine"},
        "TMA": {"en": "target motion analysis", "fr": "analyse du mouvement de cible"},
        "MAD": {"en": "magnetic anomaly detector", "fr": "détecteur d'anomalie magnétique"},
        "FFT": {"en": "fast Fourier transform", "fr": "transformée de Fourier rapide"},
    }
    expected_vlf = {"en": "very low frequency", "fr": "très basse fréquence"}

    vlf_ok = False
    if config and isinstance(config, dict):
        acrs = config.get("acronyms") or {}
        if "VLF" in acrs:
            vlf_ok = acrs["VLF"].get("en") == expected_vlf["en"] and acrs["VLF"].get("fr") == expected_vlf["fr"]
        # Only award points for ancillary config checks if VLF mapping has been added correctly
        scores["config_vlf_mapping_added"] = 1.0 if vlf_ok else 0.0
        if vlf_ok:
            banner = config.get("classification_banner")
            if banner == expected_banner:
                scores["config_banner_unchanged"] = 1.0
            expand_first = config.get("expand_first_occurrence")
            if expand_first is True and expected_expand_first:
                scores["config_expand_first_true"] = 1.0
            intact = True
            for k, v in expected_existing.items():
                if k not in acrs or acrs[k].get("en") != v["en"] or acrs[k].get("fr") != v["fr"]:
                    intact = False
                    break
            scores["config_existing_acronyms_intact"] = 1.0 if intact else 0.0

    # Prepare expectations from transcript
    transcript_path = workspace / "input" / "debrief_transcript.md"
    transcript_text = _read_text(transcript_path)
    exp_decisions, exp_actions = _parse_transcript_expectations(transcript_text if transcript_text else "")

    # Notes checks
    notes_path = workspace / "out" / "debrief_notes.md"
    notes_text = _read_text(notes_path)
    acronyms_map = config["acronyms"] if (config and "acronyms" in config) else {}

    if notes_text:
        if config and config.get("classification_banner") and _first_line(notes_text) == config["classification_banner"]:
            scores["notes_banner_first_line"] = 1.0

        summary = _extract_summary(notes_text)
        if summary:
            wc = _count_words(summary)
            if 80 <= wc <= 120:
                scores["notes_summary_length_and_one_paragraph"] = 1.0

        notes_bullets = _extract_decisions_bullets(notes_text)
        if exp_decisions:
            dec_ok = True
            norm_bullets = [_normalize_text(b) for b in notes_bullets]
            for exp in exp_decisions:
                exp_norm = _normalize_text(exp)
                found = False
                for b in norm_bullets:
                    keys = []
                    if "switch" in exp_norm:
                        keys.append("switch")
                    if "tma" in exp_norm:
                        keys.append("tma")
                    if "imm" in exp_norm:
                        keys.append("imm")
                    if "model" in exp_norm:
                        keys.append("model")
                    if all(k in b for k in keys):
                        found = True
                        break
                if not found:
                    dec_ok = False
                    break
            scores["notes_decisions_capture"] = 1.0 if dec_ok else 0.0
        else:
            scores["notes_decisions_capture"] = 1.0 if not notes_bullets else 0.0

        notes_actions = _extract_action_items(notes_text)
        if exp_actions:
            matched = 0
            for exp in exp_actions:
                owner = exp["owner"]
                due = exp["due"]
                task = exp["task"].lower()
                found = False
                for item in notes_actions:
                    if item["owner"] == owner and item["due"] == due and task in item["task"].lower():
                        found = True
                        break
                if found:
                    matched += 1
            scores["notes_action_items_lines"] = matched / len(exp_actions) if exp_actions else 0.0
        else:
            scores["notes_action_items_lines"] = 0.0

        required_acrs = ["ASW", "TMA", "FFT", "VLF"]
        if acronyms_map:
            ok_count, total = _check_first_occurrence_expansions(notes_text, acronyms_map, required_acrs, "en", require_presence=True)
            scores["notes_acronym_first_occurrence_expansions"] = (ok_count / total) if total > 0 else 0.0
        else:
            scores["notes_acronym_first_occurrence_expansions"] = 0.0

    # CO message checks
    co_path = workspace / "out" / "CO_message.txt"
    co_text = _read_text(co_path)
    if co_text:
        if config and config.get("classification_banner") and _first_line(co_text) == config["classification_banner"]:
            scores["co_banner_first_line"] = 1.0
        body_lines = co_text.splitlines()[1:] if len(co_text.splitlines()) > 1 else []
        body = "\n".join(body_lines)
        wc = _count_words(body)
        if wc <= 120 and wc > 0:
            scores["co_word_count_limit"] = 1.0
        if acronyms_map:
            present_acrs = [a for a in acronyms_map.keys() if a in co_text]
            ok_count, total = _check_first_occurrence_expansions(co_text, acronyms_map, present_acrs, "en", require_presence=False)
            scores["co_acronym_first_occurrence_expansions"] = (ok_count / total) if total > 0 else 0.0
        preserve_tokens = ["075", "25", "IMM", "legacy"]
        preserved = sum(1 for t in preserve_tokens if t in co_text)
        scores["co_preserve_numbers_and_terms"] = preserved / len(preserve_tokens) if preserve_tokens else 0.0

    # Allied messages checks
    allied_en_path = workspace / "out" / "Allied_message_en.txt"
    allied_fr_path = workspace / "out" / "Allied_message_fr.txt"
    allied_en_text = _read_text(allied_en_path)
    allied_fr_text = _read_text(allied_fr_path)

    if allied_en_text:
        if config and config.get("classification_banner") and _first_line(allied_en_text) == config["classification_banner"]:
            scores["allied_en_banner_first_line"] = 1.0
        en_body = "\n".join(allied_en_text.splitlines()[1:]) if len(allied_en_text.splitlines()) > 1 else ""
        if _count_words(en_body) <= 90 and _count_words(en_body) > 0:
            scores["allied_en_word_count_limit"] = 1.0
        if acronyms_map:
            present_acrs_en = [a for a in acronyms_map.keys() if a in allied_en_text]
            ok_count, total = _check_first_occurrence_expansions(allied_en_text, acronyms_map, present_acrs_en, "en", require_presence=False)
            scores["allied_en_acronym_first_occurrence_expansions"] = (ok_count / total) if total > 0 else 0.0

    if allied_fr_text:
        if config and config.get("classification_banner") and _first_line(allied_fr_text) == config["classification_banner"]:
            scores["allied_fr_banner_first_line"] = 1.0
        if acronyms_map:
            present_acrs_fr = [a for a in acronyms_map.keys() if a in allied_fr_text]
            ok_count, total = _check_first_occurrence_expansions(allied_fr_text, acronyms_map, present_acrs_fr, "fr", require_presence=False)
            scores["allied_fr_acronym_first_occurrence_expansions"] = (ok_count / total) if total > 0 else 0.0

        if allied_en_text:
            en_body = "\n".join(allied_en_text.splitlines()[1:]) if len(allied_en_text.splitlines()) > 1 else ""
            fr_body = "\n".join(allied_fr_text.splitlines()[1:]) if len(allied_fr_text.splitlines()) > 1 else ""
            en_nums = _extract_digit_sequences(en_body)
            fr_nums = _extract_digit_sequences(fr_body)
            scores["allied_fr_numbers_dates_preserved"] = 1.0 if en_nums == fr_nums else 0.0

            def _split_sentences(s: str) -> List[str]:
                parts = re.split(r'[.!?]+', s)
                return [p.strip() for p in parts if p.strip()]

            en_sents = _split_sentences(en_body)
            fr_sents = _split_sentences(fr_body)
            if len(en_sents) > 0 and len(en_sents) == len(fr_sents):
                scores["allied_fr_sentence_alignment"] = 1.0
            else:
                scores["allied_fr_sentence_alignment"] = 0.0
        else:
            scores["allied_fr_numbers_dates_preserved"] = 0.0
            scores["allied_fr_sentence_alignment"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()