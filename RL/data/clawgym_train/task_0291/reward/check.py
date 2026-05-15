import sys
import json
import csv
import re
import hashlib
from pathlib import Path
from typing import Optional, Dict, List, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_json(path: Path) -> Optional[object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _compute_sha256(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _extract_section(md_text: str, title: str) -> Optional[str]:
    # Extract content under a markdown header named exactly `title`
    # Recognize headers starting with one or more '#' followed by space and the title.
    lines = md_text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            # Normalize header
            m = re.match(r"^\s*#+\s+(.*)\s*$", line)
            if m:
                if m.group(1).strip() == title.strip():
                    start_idx = i + 1
                    break
    if start_idx is None:
        return None
    # Collect until next header or end
    collected: List[str] = []
    for j in range(start_idx, len(lines)):
        if lines[j].lstrip().startswith("#"):
            break
        collected.append(lines[j])
    return "\n".join(collected).strip()


def _count_words(text: str) -> int:
    # Count words as sequences of letters/numbers including unicode letters
    tokens = re.findall(r"\b[\w’'-]+\b", text, flags=re.UNICODE)
    return len(tokens)


def _split_sentences(text: str) -> List[str]:
    # Simple sentence splitter on ., !, ?
    # Keep only non-empty trimmed sentences
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in parts if s.strip()]


def _has_whole_word(haystack: str, needle: str) -> bool:
    # Whole word/phrase match: ensure boundaries around first and last word characters
    # Use unicode-friendly boundary approximation: (?<!\w) and (?!\w)
    pattern = r"(?<!\w)" + re.escape(needle) + r"(?!\w)"
    return re.search(pattern, haystack, flags=re.IGNORECASE | re.UNICODE) is not None


def _parse_agenda_todos(text: str) -> List[Dict[str, str]]:
    todos: List[Dict[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("TODO"):
            continue
        m = re.match(
            r"^TODO\s*\[Owner:\s*([A-Za-z]{2,})\]\s*\[Due:\s*(\d{4}-\d{2}-\d{2})\]:\s*(.+)$",
            line,
        )
        if m:
            initials = m.group(1).strip()
            due = m.group(2).strip()
            desc = m.group(3).strip()
            todos.append({"initials": initials, "due": due, "description": desc})
    return todos


def _parse_participants_yaml(text: str) -> Dict[str, str]:
    # Minimal YAML parser for the given simple structure
    mapping: Dict[str, str] = {}
    lines = text.splitlines()
    in_participants = False
    current: Dict[str, str] = {}
    for raw in lines:
        line = raw.rstrip("\n")
        if not in_participants:
            if line.strip().startswith("participants:"):
                in_participants = True
            continue
        # process participant entries
        if line.strip().startswith("- "):
            # Commit previous
            if "initials" in current and "name" in current:
                mapping[current["initials"]] = current["name"]
            current = {}
            # May contain fields on the same line
            rest = line.strip()[2:].strip()
            if rest:
                # e.g., "- initials: AB"
                m = re.match(r"initials:\s*(.+)", rest)
                if m:
                    current["initials"] = m.group(1).strip()
        else:
            # parse indented key: value
            m = re.match(r"^\s+([A-Za-z_]+):\s*(.+)$", line)
            if m:
                key = m.group(1).strip()
                val = m.group(2).strip()
                if key in ("initials", "name"):
                    current[key] = val
    # commit last
    if "initials" in current and "name" in current:
        mapping[current["initials"]] = current["name"]
    return mapping


def _load_glossary_csv(path: Path) -> Optional[List[Tuple[str, str]]]:
    try:
        rows: List[Tuple[str, str]] = []
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if "term_en" not in reader.fieldnames or "term_fr" not in reader.fieldnames:
                return None
            for r in reader:
                term_en = (r.get("term_en") or "").strip()
                term_fr = (r.get("term_fr") or "").strip()
                if term_en and term_fr:
                    rows.append((term_en, term_fr))
        return rows
    except Exception:
        return None


def _manifest_entries(vendor: Path, manifest_data: object) -> Optional[List[Dict[str, object]]]:
    entries: List[Dict[str, object]] = []
    if isinstance(manifest_data, list):
        for e in manifest_data:
            if isinstance(e, dict):
                entries.append(e)
    elif isinstance(manifest_data, dict):
        # Could be mapping of filename -> metadata
        for k, v in manifest_data.items():
            if isinstance(v, dict):
                e = dict(v)
                # inject filename if not present
                if "filename" not in e and "original_filename" not in e and "name" not in e and "file" not in e:
                    e["filename"] = str(k)
                entries.append(e)
    else:
        return None
    return entries if entries else None


def _entry_filename(e: Dict[str, object]) -> Optional[str]:
    for key in ("filename", "original_filename", "name", "file"):
        if key in e and isinstance(e[key], str) and e[key].strip():
            return e[key].strip()
    return None


def _entry_size(e: Dict[str, object]) -> Optional[int]:
    for key in ("size", "file_size", "bytes"):
        if key in e:
            try:
                return int(e[key])  # type: ignore[arg-type]
            except Exception:
                continue
    return None


def _entry_sha256(e: Dict[str, object]) -> Optional[str]:
    for key in ("sha256", "sha256sum"):
        if key in e and isinstance(e[key], str) and e[key].strip():
            return e[key].strip().lower()
    return None


def _contains_single_sentence_analogy(text: str, lang: str = "en") -> bool:
    sentences = _split_sentences(text)
    if not sentences:
        return False
    if lang.lower().startswith("en"):
        markers = [" like ", " as ", " analogy", "metaphor"]
    else:
        markers = [" comme ", " analogie", " métaphore"]
    count = 0
    for s in sentences:
        s_norm = " " + s.lower() + " "
        if any(m in s_norm for m in markers):
            count += 1
    return count == 1


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "vendor_manifest_exists_and_valid_json": 0.0,
        "vendor_has_non_manifest_files": 0.0,
        "vendor_manifest_entries_match_files": 0.0,
        "notes_en_has_sections": 0.0,
        "notes_fr_has_sections": 0.0,
        "en_agenda_summary_bullets_and_content": 0.0,
        "fr_agenda_summary_bullets_min2": 0.0,
        "en_plain_summary_word_limit": 0.0,
        "en_plain_summary_single_sentence_analogy": 0.0,
        "fr_plain_summary_word_limit": 0.0,
        "fr_plain_summary_single_sentence_analogy": 0.0,
        "technical_abstract_en_unchanged": 0.0,
        "technical_abstract_fr_differs_from_en": 0.0,
        "technical_abstract_fr_math_symbols_preserved": 0.0,
        "technical_abstract_fr_glossary_terms_enforced": 0.0,
        "glossary_verification_section_lists_all_terms": 0.0,
        "action_items_has_two_entries_from_todos": 0.0,
        "action_items_owner_full_names_mapped": 0.0,
        "action_items_due_dates_present": 0.0,
        "action_items_contains_required_tags": 0.0,
        "logs_install_and_translate_exists_and_nonempty": 0.0,
        "logs_mentions_install_download_translate": 0.0,
        "diagnostics_exists_and_nonempty": 0.0,
        "diagnostics_handles_errors_or_none_found": 0.0,
    }

    # Paths
    vendor_dir = workspace / "vendor"
    manifest_path = vendor_dir / "manifest.json"
    notes_en_path = workspace / "meeting" / "notes_en.md"
    notes_fr_path = workspace / "meeting" / "notes_fr.md"
    action_items_path = workspace / "meeting" / "action_items.md"
    agenda_path = workspace / "input" / "agenda.md"
    abstract_en_path = workspace / "input" / "abstract_en.txt"
    glossary_path = workspace / "input" / "glossary_en_fr.csv"
    participants_path = workspace / "input" / "participants.yaml"
    log_path = workspace / "logs" / "install_and_translate.log"
    diagnostics_path = workspace / "logs" / "diagnostics.md"

    # Vendor manifest checks
    manifest_data = _read_json(manifest_path)
    if manifest_data is not None:
        scores["vendor_manifest_exists_and_valid_json"] = 1.0
        entries = _manifest_entries(vendor_dir, manifest_data)
        if entries:
            # Check there is at least one non-manifest file in vendor
            non_manifest_files = [p for p in vendor_dir.glob("**/*") if p.is_file() and p.name != "manifest.json"]
            if non_manifest_files:
                scores["vendor_has_non_manifest_files"] = 1.0
            # Validate entries: filename exists, size matches, sha256 matches
            all_ok = True
            at_least_one = False
            for e in entries:
                fname = _entry_filename(e)
                esize = _entry_size(e)
                esha = _entry_sha256(e)
                if not fname:
                    all_ok = False
                    continue
                fpath = (vendor_dir / fname).resolve()
                try:
                    # ensure fpath within vendor
                    fpath.relative_to(vendor_dir.resolve())
                except Exception:
                    all_ok = False
                    continue
                if not fpath.exists() or not fpath.is_file():
                    all_ok = False
                    continue
                at_least_one = True
                actual_size = fpath.stat().st_size
                actual_sha = _compute_sha256(fpath)
                if esize is None or esha is None:
                    all_ok = False
                    continue
                if actual_size != esize:
                    all_ok = False
                if actual_sha is None or actual_sha.lower() != esha.lower():
                    all_ok = False
            if at_least_one and all_ok:
                scores["vendor_manifest_entries_match_files"] = 1.0

    # Notes existence and sections
    notes_en_text = _read_text(notes_en_path) or ""
    notes_fr_text = _read_text(notes_fr_path) or ""

    # Required sections
    en_agenda = _extract_section(notes_en_text, "Agenda Summary") if notes_en_text else None
    en_plain = _extract_section(notes_en_text, "Plain-language summary (EN)") if notes_en_text else None
    en_tech = _extract_section(notes_en_text, "Technical abstract (EN)") if notes_en_text else None

    fr_agenda = _extract_section(notes_fr_text, "Résumé de l'ordre du jour") if notes_fr_text else None
    fr_plain = _extract_section(notes_fr_text, "Résumé vulgarisé (FR)") if notes_fr_text else None
    fr_tech = _extract_section(notes_fr_text, "Résumé technique (FR)") if notes_fr_text else None
    fr_gloss_check = _extract_section(notes_fr_text, "Vérification du glossaire") if notes_fr_text else None

    if en_agenda is not None and en_plain is not None and en_tech is not None:
        scores["notes_en_has_sections"] = 1.0
    if fr_agenda is not None and fr_plain is not None and fr_tech is not None and fr_gloss_check is not None:
        scores["notes_fr_has_sections"] = 1.0

    # Agenda Summary content and bullet checks
    agenda_src = _read_text(agenda_path) or ""
    if en_agenda is not None and agenda_src:
        # require bullet list entries
        bullets = [ln for ln in en_agenda.splitlines() if ln.strip().startswith(("-", "*"))]
        # keywords to check presence
        keywords = [
            "Spontaneous",
            "Lagrangian",
            "gauge",
            "phase space",
            "landscape",
            "vacuum",
            "colloquium",
        ]
        present = 0
        en_agenda_lower = en_agenda.lower()
        for kw in keywords:
            if kw.lower() in en_agenda_lower:
                present += 1
        if len(bullets) >= 2 and present >= 2:
            scores["en_agenda_summary_bullets_and_content"] = 1.0

    if fr_agenda is not None:
        fr_bullets = [ln for ln in fr_agenda.splitlines() if ln.strip().startswith(("-", "*"))]
        if len(fr_bullets) >= 2:
            scores["fr_agenda_summary_bullets_min2"] = 1.0

    # Plain-language summaries checks
    if en_plain is not None:
        if _count_words(en_plain) <= 120:
            scores["en_plain_summary_word_limit"] = 1.0
        if _contains_single_sentence_analogy(en_plain, lang="en"):
            scores["en_plain_summary_single_sentence_analogy"] = 1.0

    if fr_plain is not None:
        if _count_words(fr_plain) <= 120:
            scores["fr_plain_summary_word_limit"] = 1.0
        if _contains_single_sentence_analogy(fr_plain, lang="fr"):
            scores["fr_plain_summary_single_sentence_analogy"] = 1.0

    # Technical abstract EN unchanged
    abstract_en_text = _read_text(abstract_en_path) or ""
    if en_tech is not None and abstract_en_text:
        # Compare exact trimmed content
        if en_tech.strip() == abstract_en_text.strip():
            scores["technical_abstract_en_unchanged"] = 1.0

    # Technical abstract FR checks
    if fr_tech is not None and abstract_en_text:
        # Must differ from EN abstract (translated)
        if fr_tech.strip() != abstract_en_text.strip():
            scores["technical_abstract_fr_differs_from_en"] = 1.0
        # Math symbols preserved
        required_syms = ["L = T - V", "SU(2)", "ℏ"]
        if all(sym in fr_tech for sym in required_syms):
            scores["technical_abstract_fr_math_symbols_preserved"] = 1.0

    # Glossary enforcement in FR section
    glossary_rows = _load_glossary_csv(glossary_path)
    if glossary_rows is not None and fr_tech is not None:
        all_enforced = True
        for term_en, term_fr in glossary_rows:
            # term_fr must appear as whole phrase; term_en must not appear as whole phrase
            if not _has_whole_word(fr_tech, term_fr):
                all_enforced = False
                break
            if _has_whole_word(fr_tech, term_en):
                all_enforced = False
                break
        if all_enforced:
            scores["technical_abstract_fr_glossary_terms_enforced"] = 1.0

    if glossary_rows is not None and fr_gloss_check is not None:
        listed_all = True
        for term_en, term_fr in glossary_rows:
            if term_en not in fr_gloss_check or term_fr not in fr_gloss_check:
                listed_all = False
                break
        if listed_all:
            scores["glossary_verification_section_lists_all_terms"] = 1.0

    # Action items from agenda
    agenda_todos = _parse_agenda_todos(agenda_src) if agenda_src else []
    participants_text = _read_text(participants_path) or ""
    participants_map = _parse_participants_yaml(participants_text) if participants_text else {}

    action_items_text = _read_text(action_items_path) or ""

    if agenda_todos and action_items_text:
        # Check descriptions present
        found_all_desc = all(todo["description"] in action_items_text for todo in agenda_todos)
        # Check count by due dates
        found_all_due = all(todo["due"] in action_items_text for todo in agenda_todos)
        if found_all_desc and found_all_due:
            scores["action_items_has_two_entries_from_todos"] = 1.0
        if found_all_due:
            scores["action_items_due_dates_present"] = 1.0

        # Owner full names mapped
        owners_ok = True
        for todo in agenda_todos:
            init = todo["initials"]
            full = participants_map.get(init)
            if not full or full not in action_items_text:
                owners_ok = False
                break
        if owners_ok:
            scores["action_items_owner_full_names_mapped"] = 1.0

        # Tags present
        tags_ok = ("theory" in action_items_text.lower()) and ("intuition" in action_items_text.lower())
        if tags_ok:
            scores["action_items_contains_required_tags"] = 1.0

    # Logs
    log_text = _read_text(log_path) or ""
    if log_text:
        scores["logs_install_and_translate_exists_and_nonempty"] = 1.0
        # Must mention install, download, translate
        lt = log_text.lower()
        if ("install" in lt) and ("download" in lt) and ("translate" in lt or "translation" in lt):
            scores["logs_mentions_install_download_translate"] = 1.0

    diagnostics_text = _read_text(diagnostics_path) or ""
    if diagnostics_text:
        scores["diagnostics_exists_and_nonempty"] = 1.0

        # Determine if issues exist in log
        issues_lines = []
        for i, line in enumerate(log_text.splitlines(), start=1):
            low = line.lower()
            if ("error" in low) or ("warning" in low) or re.search(r"(exit code|non[- ]?zero|return code|exited with)", low):
                issues_lines.append((i, line))

        diag_low = diagnostics_text.lower()
        if issues_lines:
            # Expect mention of error/warning/exit and resolution and reference to line/snippet
            mentions_issue = any(token in diag_low for token in ["error", "warning", "exit code", "non-zero", "return code", "exited"])
            mentions_resolution = any(token in diag_low for token in ["resolve", "resolved", "résolu", "résolution"])
            mentions_reference = ("line" in diag_low) or ("ligne" in diag_low)
            if mentions_issue and mentions_resolution and mentions_reference:
                scores["diagnostics_handles_errors_or_none_found"] = 1.0
        else:
            # Expect explicit none found
            if ("none" in diag_low and "found" in diag_low) or ("aucun" in diag_low):
                scores["diagnostics_handles_errors_or_none_found"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()