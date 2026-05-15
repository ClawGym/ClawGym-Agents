import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def parse_simple_yaml_glossary(yaml_text: str) -> Optional[Dict[str, str]]:
    # Simple, tolerant YAML parser for the expected glossary structure
    if yaml_text is None:
        return None
    lines = yaml_text.splitlines()
    glossary: Dict[str, str] = {}
    in_glossary = False
    for line in lines:
        line_no_comment = re.sub(r'\s*#.*$', '', line).rstrip()
        if not line_no_comment.strip():
            continue
        if not in_glossary:
            if re.match(r'^\s*glossary\s*:\s*$', line_no_comment):
                in_glossary = True
            continue
        if re.match(r'^\S', line_no_comment):
            break
        m = re.match(r'^\s+([\'"])(.*?)\1\s*:\s*([\'"])(.*?)\3\s*$', line_no_comment)
        if m:
            key = m.group(2).strip()
            val = m.group(4).strip()
            glossary[key] = val
        else:
            m2 = re.match(r'^\s+([^:]+)\s*:\s*(.+)$', line_no_comment)
            if m2:
                key = m2.group(1).strip().strip('"\'')
                val = m2.group(2).strip().strip('"\'')
                glossary[key] = val
    if not glossary:
        return None
    return glossary


def parse_bullets_from_section(text: str, section_label: str) -> List[Tuple[str, str]]:
    bullets: List[Tuple[str, str]] = []
    if text is None:
        return bullets
    lines = text.splitlines()
    in_section = False
    for line in lines:
        if re.match(rf'^\s*==\s*{re.escape(section_label)}\s*==\s*$', line):
            in_section = True
            continue
        if in_section and re.match(r'^\s*==\s*.+\s*==\s*$', line):
            break
        if in_section and re.match(r'^\s*-\s+', line):
            id_full = re.search(r'\[([EQ]\d+)\]\s*$', line)
            if id_full:
                id_val = id_full.group(1)
                text_without_id = re.sub(r'\s*\[[EQ]\d+\]\s*$', '', line).strip()
                text_without_id = re.sub(r'^\s*-\s+', '', text_without_id).strip()
                bullets.append((id_val, text_without_id))
    return bullets


def find_section_bullets_brief(text: str, section_name: str) -> List[str]:
    if text is None:
        return []
    lines = text.splitlines()
    section_indices = []
    for idx, line in enumerate(lines):
        if re.match(rf'^\s*#*\s*{re.escape(section_name)}\s*#*\s*$', line, flags=re.IGNORECASE):
            section_indices.append(idx)
    if not section_indices:
        return []
    start_idx = section_indices[0] + 1
    bullets: List[str] = []
    for i in range(start_idx, len(lines)):
        line = lines[i]
        if re.match(r'^\s*#*\s*(Findings|Recommendations)\s*#*\s*$', line, flags=re.IGNORECASE):
            break
        if line.strip().startswith("- "):
            bullets.append(line.rstrip())
    return bullets


def extract_source_from_bullet(line: str) -> Optional[Tuple[str, str]]:
    m = re.search(r'\[source:\s*([^\]\s]+)\s+([EQ]\d+)\]\s*$', line)
    if not m:
        return None
    return m.group(1), m.group(2)


def get_english_part_before_es_parenthetical(line: str) -> str:
    line_no_source = re.sub(r'\s*\[source:.*\]\s*$', '', line).rstrip()
    line_no_source = re.sub(r'^\s*-\s+', '', line_no_source)
    idx = line_no_source.find("(ES:")
    if idx != -1:
        eng = line_no_source[:idx].strip()
        return eng
    return line_no_source.strip()


def brief_title_line(text: str) -> Optional[str]:
    if text is None:
        return None
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return None


def count_words(text: str) -> int:
    if not text:
        return 0
    tokens = re.findall(r'\b\w+\b', text, flags=re.UNICODE)
    return len(tokens)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "terms_yaml_parseable": 0.0,
        "terms_yaml_drr_mapping_updated": 0.0,
        "terms_yaml_preserve_resiliencia_comunitaria": 0.0,
        "terms_yaml_has_ayuda_en_efectivo": 0.0,
        "terms_yaml_has_rendicion_de_cuentas": 0.0,
        "terms_yaml_has_mecanismos_de_quejas": 0.0,
        "terms_yaml_has_transferencias_condicionadas": 0.0,
        "terms_yaml_has_medios_de_vida": 0.0,
        "terms_yaml_has_alojamiento_temporal": 0.0,
        "brief_file_exists": 0.0,
        "brief_title_appropriate": 0.0,
        "brief_sections_present": 0.0,
        "brief_findings_include_interview_ids": 0.0,
        "brief_findings_include_policy_ids": 0.0,
        "brief_recommendations_include_interview_ids": 0.0,
        "brief_recommendations_include_policy_ids": 0.0,
        "brief_all_bullets_have_source_tags": 0.0,
        "brief_spanish_originals_included_findings": 0.0,
        "brief_spanish_originals_included_recommendations": 0.0,
        "brief_spanish_english_uses_glossary_findings": 0.0,
        "brief_spanish_english_uses_glossary_recommendations": 0.0,
        "brief_english_terms_consistency_overall": 0.0,
        "email_file_exists": 0.0,
        "email_subject_and_greeting": 0.0,
        "email_word_count_140_180": 0.0,
        "email_two_recommendation_ids_referenced": 0.0,
        "email_two_bulleted_questions_mecanismos": 0.0,
        "email_glossary_parenthetical_compliance": 0.0,
    }

    interview_path = workspace / "input" / "interview_notes_en.txt"
    policy_path = workspace / "input" / "policy_excerpts_es.txt"
    terms_path = workspace / "config" / "terms.yaml"
    brief_path = workspace / "output" / "bilingual_brief.md"
    email_path = workspace / "output" / "email_a_socio_es.txt"

    interview_text = safe_read_text(interview_path)
    policy_text = safe_read_text(policy_path)
    terms_text = safe_read_text(terms_path)

    glossary = None
    if terms_text is not None:
        glossary = parse_simple_yaml_glossary(terms_text)

    has_drr_updated = False
    has_required_new_terms = False
    has_resilience = False
    if glossary:
        has_drr_updated = glossary.get("reducción de riesgos de desastres") == "disaster risk reduction (DRR)"
        has_resilience = glossary.get("resiliencia comunitaria") == "community resilience"
        required_new = {
            "ayuda en efectivo": "cash assistance",
            "rendición de cuentas": "accountability",
            "mecanismos de quejas": "grievance mechanisms",
            "transferencias condicionadas": "conditional cash transfers",
            "medios de vida": "livelihoods",
            "alojamiento temporal": "temporary shelter",
        }
        has_required_new_terms = all(glossary.get(k) == v for k, v in required_new.items())

        # Gate parseable credit on actually performing required updates to avoid baseline credit
        if has_drr_updated and has_required_new_terms:
            scores["terms_yaml_parseable"] = 1.0
        if has_drr_updated:
            scores["terms_yaml_drr_mapping_updated"] = 1.0
        if has_drr_updated and has_resilience:
            scores["terms_yaml_preserve_resiliencia_comunitaria"] = 1.0
        if glossary.get("ayuda en efectivo") == "cash assistance":
            scores["terms_yaml_has_ayuda_en_efectivo"] = 1.0
        if glossary.get("rendición de cuentas") == "accountability":
            scores["terms_yaml_has_rendicion_de_cuentas"] = 1.0
        if glossary.get("mecanismos de quejas") == "grievance mechanisms":
            scores["terms_yaml_has_mecanismos_de_quejas"] = 1.0
        if glossary.get("transferencias condicionadas") == "conditional cash transfers":
            scores["terms_yaml_has_transferencias_condicionadas"] = 1.0
        if glossary.get("medios de vida") == "livelihoods":
            scores["terms_yaml_has_medios_de_vida"] = 1.0
        if glossary.get("alojamiento temporal") == "temporary shelter":
            scores["terms_yaml_has_alojamiento_temporal"] = 1.0

    interview_findings = parse_bullets_from_section(interview_text or "", "Key Findings")
    interview_recommendations = parse_bullets_from_section(interview_text or "", "Recommendations")
    policy_findings = parse_bullets_from_section(policy_text or "", "Hallazgos Clave")
    policy_recommendations = parse_bullets_from_section(policy_text or "", "Recomendaciones")

    spanish_by_id: Dict[str, str] = {}
    for _id, txt in (policy_findings + policy_recommendations):
        spanish_by_id[_id] = txt

    brief_text = safe_read_text(brief_path)
    if brief_text is not None and brief_text.strip():
        scores["brief_file_exists"] = 1.0
        title = brief_title_line(brief_text)
        if title:
            title_ok = (
                re.search(r'\bBilingual\b', title, flags=re.IGNORECASE) is not None and
                re.search(r'\bExecutive Summary\b', title, flags=re.IGNORECASE) is not None and
                re.search(r'\bDRR\b', title, flags=re.IGNORECASE) is not None and
                re.search(r'\bCash\b', title, flags=re.IGNORECASE) is not None
            )
            if title_ok:
                scores["brief_title_appropriate"] = 1.0

        findings_bullets = find_section_bullets_brief(brief_text, "Findings")
        recommendations_bullets = find_section_bullets_brief(brief_text, "Recommendations")
        if findings_bullets and recommendations_bullets:
            scores["brief_sections_present"] = 1.0

        def ids_from_bullets(bullets: List[str], expected_file: str) -> List[str]:
            ids = []
            for b in bullets:
                src = extract_source_from_bullet(b)
                if src and Path(src[0]).name == expected_file:
                    ids.append(src[1])
            return ids

        findings_interview_expected = {i for i, _ in interview_findings}
        findings_policy_expected = {i for i, _ in policy_findings}
        recs_interview_expected = {i for i, _ in interview_recommendations}
        recs_policy_expected = {i for i, _ in policy_recommendations}

        findings_interview_ids_present = set(ids_from_bullets(findings_bullets, "interview_notes_en.txt"))
        findings_policy_ids_present = set(ids_from_bullets(findings_bullets, "policy_excerpts_es.txt"))
        recs_interview_ids_present = set(ids_from_bullets(recommendations_bullets, "interview_notes_en.txt"))
        recs_policy_ids_present = set(ids_from_bullets(recommendations_bullets, "policy_excerpts_es.txt"))

        if findings_interview_expected and findings_interview_expected.issubset(findings_interview_ids_present):
            scores["brief_findings_include_interview_ids"] = 1.0
        if findings_policy_expected and findings_policy_expected.issubset(findings_policy_ids_present):
            scores["brief_findings_include_policy_ids"] = 1.0
        if recs_interview_expected and recs_interview_expected.issubset(recs_interview_ids_present):
            scores["brief_recommendations_include_interview_ids"] = 1.0
        if recs_policy_expected and recs_policy_expected.issubset(recs_policy_ids_present):
            scores["brief_recommendations_include_policy_ids"] = 1.0

        all_bullets = findings_bullets + recommendations_bullets
        if all_bullets:
            all_have_source = True
            for b in all_bullets:
                if extract_source_from_bullet(b) is None:
                    all_have_source = False
                    break
            scores["brief_all_bullets_have_source_tags"] = 1.0 if all_have_source else 0.0

        def spanish_originals_included_score(bullets: List[str], expected_ids: set) -> float:
            if not expected_ids:
                return 0.0
            found = 0
            total = len(expected_ids)
            bullet_by_id = {}
            for b in bullets:
                src = extract_source_from_bullet(b)
                if src:
                    bullet_by_id[src[1]] = b
            for sid in expected_ids:
                bline = bullet_by_id.get(sid)
                sp_text = spanish_by_id.get(sid, "")
                if bline and "(ES:" in bline and sp_text:
                    m = re.search(r'\(ES:\s*(.*?)\)\s*\[source:', bline)
                    if not m:
                        m = re.search(r'\(ES:\s*(.*?)\)\s*$', bline)
                    if m:
                        inside = m.group(1).strip()
                        def norm(s: str) -> str:
                            return re.sub(r'\s+', ' ', s.strip())
                        if norm(sp_text) in norm(inside):
                            found += 1
            return found / total if total > 0 else 0.0

        scores["brief_spanish_originals_included_findings"] = spanish_originals_included_score(
            findings_bullets, findings_policy_expected
        )
        scores["brief_spanish_originals_included_recommendations"] = spanish_originals_included_score(
            recommendations_bullets, recs_policy_expected
        )

        def english_uses_glossary_score(bullets: List[str], expected_ids: set) -> float:
            if not expected_ids or not glossary:
                return 0.0
            ok = 0
            total = len(expected_ids)
            bullet_by_id = {}
            for b in bullets:
                src = extract_source_from_bullet(b)
                if src:
                    bullet_by_id[src[1]] = b
            for sid in expected_ids:
                bline = bullet_by_id.get(sid)
                sp_text = spanish_by_id.get(sid, "")
                if not bline or not sp_text:
                    continue
                eng_part = get_english_part_before_es_parenthetical(bline)
                terms_present = []
                for sp_term, en_term in glossary.items():
                    if sp_term in sp_text:
                        terms_present.append((sp_term, en_term))
                if not terms_present:
                    ok += 1
                else:
                    all_terms_ok = all(en_term in eng_part for _, en_term in terms_present)
                    if all_terms_ok:
                        ok += 1
            return ok / total if total > 0 else 0.0

        scores["brief_spanish_english_uses_glossary_findings"] = english_uses_glossary_score(
            findings_bullets, findings_policy_expected
        )
        scores["brief_spanish_english_uses_glossary_recommendations"] = english_uses_glossary_score(
            recommendations_bullets, recs_policy_expected
        )

        required_terms = [
            "disaster risk reduction (DRR)",
            "cash assistance",
            "grievance mechanisms",
            "accountability",
            "temporary shelter",
            "livelihoods",
            "conditional cash transfers",
            "community resilience",
        ]
        if brief_text:
            present = 0
            for term in required_terms:
                if term in brief_text:
                    present += 1
            scores["brief_english_terms_consistency_overall"] = present / len(required_terms) if required_terms else 1.0

    email_text = safe_read_text(email_path)
    if email_text is not None and email_text.strip():
        scores["email_file_exists"] = 1.0
        lines = [ln for ln in email_text.splitlines()]
        first_nonempty = None
        for ln in lines:
            if ln.strip():
                first_nonempty = ln.strip()
                break
        subject_ok = first_nonempty is not None and first_nonempty.startswith("Asunto:")
        greeting_ok = bool(re.search(r'\b(Estimad[oa]|Hola|Buenos días|Buenas tardes|Buen día)\b', email_text))
        if subject_ok and greeting_ok:
            scores["email_subject_and_greeting"] = 1.0

        wc = count_words(email_text)
        if 140 <= wc <= 180:
            scores["email_word_count_140_180"] = 1.0

        ids = re.findall(r'\[([EQ]\d+)\]', email_text)
        unique_ids = set(ids)
        allowed_ids = {f"Q{i}" for i in range(4, 8)} | {f"E{i}" for i in range(4, 7)}
        valid_reco_ids = {i for i in unique_ids if i in allowed_ids}
        if len(valid_reco_ids) >= 2:
            scores["email_two_recommendation_ids_referenced"] = 1.0

        bullet_lines = [ln.strip() for ln in lines if ln.strip().startswith("- ")]
        question_bullets = [b for b in bullet_lines if "?" in b and re.search(r'\bmecanismos de quejas\b', b)]
        if len(question_bullets) == 2:
            scores["email_two_bulleted_questions_mecanismos"] = 1.0

        glossary_to_check = {
            "ayuda en efectivo": glossary.get("ayuda en efectivo") if glossary else "cash assistance",
            "reducción de riesgos de desastres": glossary.get("reducción de riesgos de desastres") if glossary else "disaster risk reduction (DRR)",
            "mecanismos de quejas": glossary.get("mecanismos de quejas") if glossary else "grievance mechanisms",
        }
        total_terms_present = 0
        compliant_terms = 0
        for sp_term, en_term in glossary_to_check.items():
            if sp_term in email_text:
                total_terms_present += 1
                if f"{sp_term} ({en_term})" in email_text:
                    compliant_terms += 1
        if total_terms_present > 0:
            scores["email_glossary_parenthetical_compliance"] = compliant_terms / total_terms_present
        else:
            scores["email_glossary_parenthetical_compliance"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()