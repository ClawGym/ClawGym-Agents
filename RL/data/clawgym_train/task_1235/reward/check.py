import json
import csv
import sys
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _normalize_newlines(s: str) -> str:
    return s.replace("\r\n", "\n").replace("\r", "\n")


def _parse_simple_yaml_mapping(text: str) -> Optional[Dict[str, Any]]:
    # Minimal indentation-based YAML mapping parser for the provided structure.
    lines = text.splitlines()
    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Dict[str, Any]]] = [(-1, root)]
    for raw in lines:
        if not raw.strip():
            continue
        if raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        if ":" not in line:
            return None
        key, rest = line.split(":", 1)
        key = key.strip()
        value = rest.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            return None
        current = stack[-1][1]
        if value == "":
            new_map: Dict[str, Any] = {}
            current[key] = new_map
            stack.append((indent, new_map))
        else:
            current[key] = value
    return root


def _glossary_struct_ok(gloss: Dict[str, Any]) -> bool:
    try:
        if "languages" not in gloss or "signature" not in gloss:
            return False
        langs = gloss["languages"]
        if not isinstance(langs, dict):
            return False
        for code in ("es", "fr"):
            if code not in langs:
                return False
            lc = langs[code]
            if not isinstance(lc, dict):
                return False
            for req in ("terms", "subject_template", "salutation", "signoff"):
                if req not in lc:
                    return False
            if not isinstance(lc["terms"], dict):
                return False
            if not isinstance(lc["subject_template"], str):
                return False
            if not isinstance(lc["salutation"], str):
                return False
            if not isinstance(lc["signoff"], str):
                return False
        if not isinstance(gloss["signature"], str):
            return False
        return True
    except Exception:
        return False


def _apply_terms(text: str, terms: Dict[str, str]) -> str:
    # Replace longer keys first to avoid partial overlaps, case-sensitive.
    result = text
    for key in sorted(terms.keys(), key=lambda k: len(k), reverse=True):
        result = result.replace(key, terms[key])
    return result


def _load_contacts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            # Validate header contains expected columns
            expected_cols = {"contact_id", "name", "email", "county", "language_preference", "availability_date", "urgency_score", "voters_impacted"}
            if reader.fieldnames is None or not expected_cols.issubset(set(reader.fieldnames)):
                return None
            rows = []
            for r in reader:
                rows.append({k: v for k, v in r.items()})
            return rows
    except Exception:
        return None


def _select_and_rank_contacts(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    selected = [r for r in rows if r.get("language_preference") in ("Spanish", "French")]
    def _to_int(v: str) -> int:
        try:
            return int(v)
        except Exception:
            return -10**9
    selected.sort(key=lambda r: (_to_int(r.get("urgency_score", "")), _to_int(r.get("voters_impacted", ""))), reverse=True)
    ranked = []
    for idx, r in enumerate(selected, start=1):
        ranked.append({
            "rank": str(idx),
            "contact_id": r.get("contact_id", ""),
            "name": r.get("name", ""),
            "email": r.get("email", ""),
            "county": r.get("county", ""),
            "language_preference": r.get("language_preference", ""),
            "availability_date": r.get("availability_date", ""),
            "urgency_score": r.get("urgency_score", ""),
            "voters_impacted": r.get("voters_impacted", ""),
        })
    return ranked


def _read_ranked_contacts_output(path: Path) -> Optional[Tuple[List[str], List[List[str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
            if not rows:
                return None
            header = rows[0]
            data = rows[1:]
            return header, data
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "translation_es_exact_match": 0.0,
        "translation_fr_exact_match": 0.0,
        "contacts_ranked_exact_match": 0.0,
        "emails_files_count_and_names": 0.0,
        "emails_subjects_correct": 0.0,
        "emails_salutations_correct": 0.0,
        "emails_body_contains_translated_flyer_filled": 0.0,
        "emails_signoff_and_signature_in_order": 0.0,
        "emails_no_placeholders_remaining": 0.0,
    }

    # Load glossary
    glossary_path = workspace / "config" / "glossary.yaml"
    glossary_text = _read_text(glossary_path)
    glossary = None
    glossary_ok = False
    if glossary_text is not None:
        glossary = _parse_simple_yaml_mapping(glossary_text)
        if glossary is not None and _glossary_struct_ok(glossary):
            glossary_ok = True

    # Prepare expected translations
    flyer_path = workspace / "input" / "messages" / "flyer.txt"
    flyer_text = _read_text(flyer_path)
    expected_translations: Dict[str, str] = {}
    if glossary_ok and flyer_text is not None:
        langs = glossary["languages"]
        for code in ("es", "fr"):
            terms = langs[code]["terms"]
            expected_translations[code] = _apply_terms(_normalize_newlines(flyer_text), terms)

    # Check translation files
    out_es_path = workspace / "out" / "translations" / "flyer_es.txt"
    out_fr_path = workspace / "out" / "translations" / "flyer_fr.txt"

    if "es" in expected_translations:
        es_out_text = _read_text(out_es_path)
        if es_out_text is not None:
            if _normalize_newlines(es_out_text) == expected_translations["es"]:
                scores["translation_es_exact_match"] = 1.0

    if "fr" in expected_translations:
        fr_out_text = _read_text(out_fr_path)
        if fr_out_text is not None:
            if _normalize_newlines(fr_out_text) == expected_translations["fr"]:
                scores["translation_fr_exact_match"] = 1.0

    # Contacts ranking
    contacts_path = workspace / "data" / "contacts.csv"
    contacts_rows = _load_contacts(contacts_path)
    expected_ranked: List[Dict[str, str]] = []
    expected_contact_ids: List[str] = []
    if contacts_rows is not None:
        expected_ranked = _select_and_rank_contacts(contacts_rows)
        expected_contact_ids = [r["contact_id"] for r in expected_ranked]

        out_ranked_path = workspace / "out" / "priority" / "contacts_ranked.csv"
        parsed = _read_ranked_contacts_output(out_ranked_path)
        if parsed is not None:
            header, data_rows = parsed
            expected_header = ["rank", "contact_id", "name", "email", "county", "language_preference", "availability_date", "urgency_score", "voters_impacted"]
            if header == expected_header and len(data_rows) == len(expected_ranked):
                match = True
                for i, row in enumerate(data_rows):
                    exp = expected_ranked[i]
                    if row != [exp[h] for h in expected_header]:
                        match = False
                        break
                if match:
                    scores["contacts_ranked_exact_match"] = 1.0

    # Emails checks
    emails_dir = workspace / "out" / "emails"
    emails_files_ok = 0.0
    subjects_ok = 0.0
    salutations_ok = 0.0
    body_ok = 0.0
    signoff_sig_ok = 0.0
    no_placeholders_ok = 0.0

    if glossary_ok and contacts_rows is not None and expected_contact_ids:
        langs = glossary["languages"]
        signature = glossary["signature"]
        existing_email_files = []
        if emails_dir.exists() and emails_dir.is_dir():
            for p in emails_dir.iterdir():
                if p.is_file() and p.suffix == ".txt":
                    existing_email_files.append(p.name)
        expected_file_names = [f"{cid}.txt" for cid in expected_contact_ids]
        if set(existing_email_files) == set(expected_file_names) and len(existing_email_files) == len(expected_file_names):
            emails_files_ok = 1.0

        contacts_by_id = {r["contact_id"]: r for r in contacts_rows}
        all_subjects_ok = True
        all_salutations_ok = True
        all_body_ok = True
        all_signoff_sig_ok = True
        all_no_placeholders_ok = True

        translated_flyers = expected_translations

        for cid in expected_contact_ids:
            c = contacts_by_id.get(cid)
            if not c:
                all_subjects_ok = False
                all_salutations_ok = False
                all_body_ok = False
                all_signoff_sig_ok = False
                all_no_placeholders_ok = False
                continue
            lang_pref = c.get("language_preference")
            lang_code = "es" if lang_pref == "Spanish" else ("fr" if lang_pref == "French" else None)
            if lang_code is None:
                all_subjects_ok = False
                all_salutations_ok = False
                all_body_ok = False
                all_signoff_sig_ok = False
                all_no_placeholders_ok = False
                continue
            lang_cfg = langs[lang_code]
            expected_subject = lang_cfg["subject_template"].replace("{county}", c.get("county", ""))
            expected_salutation = lang_cfg["salutation"].replace("{name}", c.get("name", ""))
            base_translated = translated_flyers.get(lang_code, "")
            expected_body = base_translated.replace("{county}", c.get("county", "")).replace("{date}", c.get("availability_date", ""))
            expected_signoff = lang_cfg["signoff"]
            expected_signature = signature

            email_path = emails_dir / f"{cid}.txt"
            email_text_raw = _read_text(email_path)
            if email_text_raw is None:
                all_subjects_ok = False
                all_salutations_ok = False
                all_body_ok = False
                all_signoff_sig_ok = False
                all_no_placeholders_ok = False
                continue
            email_text = _normalize_newlines(email_text_raw)

            if expected_subject not in email_text:
                all_subjects_ok = False
            if expected_salutation not in email_text:
                all_salutations_ok = False
            if expected_body not in email_text:
                all_body_ok = False
            idx_signoff = email_text.find(expected_signoff)
            idx_signature = email_text.find(expected_signature)
            if idx_signoff == -1 or idx_signature == -1 or not (idx_signoff < idx_signature):
                all_signoff_sig_ok = False
            if ("{county}" in email_text) or ("{date}" in email_text):
                all_no_placeholders_ok = False

        subjects_ok = 1.0 if all_subjects_ok else 0.0
        salutations_ok = 1.0 if all_salutations_ok else 0.0
        body_ok = 1.0 if all_body_ok else 0.0
        signoff_sig_ok = 1.0 if all_signoff_sig_ok else 0.0
        no_placeholders_ok = 1.0 if all_no_placeholders_ok else 0.0

    scores["emails_files_count_and_names"] = emails_files_ok
    scores["emails_subjects_correct"] = subjects_ok
    scores["emails_salutations_correct"] = salutations_ok
    scores["emails_body_contains_translated_flyer_filled"] = body_ok
    scores["emails_signoff_and_signature_in_order"] = signoff_sig_ok
    scores["emails_no_placeholders_remaining"] = no_placeholders_ok

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()