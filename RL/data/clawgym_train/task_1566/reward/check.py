import json
import csv
import hashlib
import sys
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def read_text_safe(path: Path) -> Optional[str]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def load_json_safe(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_yaml_safe(path: Path) -> Optional[dict]:
    try:
        import yaml  # stdlib not, but provided in task context; handle failure gracefully
    except Exception:
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception:
        return None


def load_csv_safe(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader]
            # Validate required headers
            if not reader.fieldnames:
                return None
            required = {"term", "es-ES", "fr-FR"}
            if not required.issubset(set(reader.fieldnames)):
                return None
            return rows
    except Exception:
        return None


def md5_of_text(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def count_unified_diff_changes(diff_text: str) -> int:
    if not diff_text:
        return 0
    changes = 0
    for line in diff_text.splitlines():
        if line.startswith('@@'):
            continue
        if line.startswith('+++') or line.startswith('---'):
            continue
        if line.startswith('+') or line.startswith('-'):
            changes += 1
    return changes


def build_placeholder_regex(patterns: List[str]) -> Optional[re.Pattern]:
    try:
        if not patterns:
            return None
        # Combine multiple patterns into one OR regex
        combined = "(" + ")|(".join(patterns) + ")"
        return re.compile(combined)
    except Exception:
        return None


def extract_placeholders(text: str, placeholder_re: re.Pattern) -> List[str]:
    if not text:
        return []
    return [m.group(0) for m in placeholder_re.finditer(text)]


def structure_sequence(text: str) -> List[str]:
    seq = []
    if not text:
        return seq
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#####"):
            seq.append("H5")
        elif stripped.startswith("####"):
            seq.append("H4")
        elif stripped.startswith("###"):
            seq.append("H3")
        elif stripped.startswith("##"):
            seq.append("H2")
        elif stripped.startswith("#"):
            seq.append("H1")
        elif re.match(r'^\s*-\s+', line):
            seq.append("UL")
        # We ignore other lines for structure purposes
    return seq


def extract_numbers_and_emails(text: str) -> List[str]:
    if not text:
        return []
    tokens = set()
    # Currency amounts like $250,000
    for m in re.finditer(r'\$[0-9][0-9,]*', text):
        tokens.add(m.group(0))
    # Percentages like 6.9%
    for m in re.finditer(r'\d+(?:\.\d+)?%', text):
        tokens.add(m.group(0))
    # Plain integers
    for m in re.finditer(r'\b\d+\b', text):
        tokens.add(m.group(0))
    # Emails (allow placeholders in local part)
    for m in re.finditer(r'[A-Za-z0-9._{}+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}', text):
        tokens.add(m.group(0))
    return sorted(tokens)


def count_case_insensitive(haystack: str, needle: str) -> int:
    if not haystack or not needle:
        return 0
    return haystack.lower().count(needle.lower())


def compute_glossary_occurrences(out_text: str, glossary_rows: List[Dict[str, str]], locale: str) -> int:
    if not out_text or not glossary_rows:
        return 0
    total = 0
    for row in glossary_rows:
        trans = row.get(locale, "") or ""
        trans = trans.strip()
        if not trans:
            continue
        total += count_case_insensitive(out_text, trans)
    return total


def endswith_path(p: str, suffix: str) -> bool:
    try:
        return Path(p).as_posix().endswith(Path(suffix).as_posix())
    except Exception:
        # Fallback simple
        return str(p).replace("\\", "/").endswith(str(suffix).replace("\\", "/"))


def grade(transcript: list, workspace_path: str) -> dict:
    ws = Path(workspace_path)
    scores: Dict[str, float] = {
        "config_has_preserve_terms": 0.0,
        "config_has_placeholder_patterns": 0.0,
        "localized_files_exist": 0.0,
        "structure_preserved_es": 0.0,
        "structure_preserved_fr": 0.0,
        "placeholders_preserved_es": 0.0,
        "placeholders_preserved_fr": 0.0,
        "preserve_terms_preserved_es": 0.0,
        "preserve_terms_preserved_fr": 0.0,
        "glossary_applied_es": 0.0,
        "glossary_applied_fr": 0.0,
        "numbers_and_email_preserved_es": 0.0,
        "numbers_and_email_preserved_fr": 0.0,
        "qa_report_exists": 0.0,
        "qa_md5_matches_es": 0.0,
        "qa_md5_matches_fr": 0.0,
        "qa_lines_total_consistent_es": 0.0,
        "qa_lines_total_consistent_fr": 0.0,
        "qa_lines_changed_consistent_es": 0.0,
        "qa_lines_changed_consistent_fr": 0.0,
        "qa_glossary_matches_reported_es": 0.0,
        "qa_glossary_matches_reported_fr": 0.0,
        "qa_preserved_placeholders_reported_es": 0.0,
        "qa_preserved_placeholders_reported_fr": 0.0,
        "qa_preserved_terms_reported_es": 0.0,
        "qa_preserved_terms_reported_fr": 0.0,
        "diff_files_exist_nonempty_es": 0.0,
        "diff_files_exist_nonempty_fr": 0.0,
    }

    # Paths
    cfg_path = ws / "config" / "localization.yml"
    src_path = ws / "input" / "products.md"
    glossary_path = ws / "input" / "glossary.csv"
    out_es = ws / "output" / "es-ES" / "products.md"
    out_fr = ws / "output" / "fr-FR" / "products.md"
    qa_report_path = ws / "output" / "qa" / "report.json"
    diff_es_path = ws / "output" / "qa" / "diff-es-ES.txt"
    diff_fr_path = ws / "output" / "qa" / "diff-fr-FR.txt"

    # Load config
    cfg = load_yaml_safe(cfg_path) or {}

    # Check preserve_terms
    preserve_terms = cfg.get("preserve_terms", None)
    if isinstance(preserve_terms, list) and preserve_terms == ["Northstar Capital", "Northstar Flex"]:
        scores["config_has_preserve_terms"] = 1.0

    # Check placeholder_patterns
    placeholder_patterns = cfg.get("placeholder_patterns", None)
    # When YAML loads "\\{[^}]+\\}" it becomes "\{[^}]+\}"
    expected_pattern = r"\{[^}]+\}"
    if isinstance(placeholder_patterns, list) and len(placeholder_patterns) == 1:
        pat = placeholder_patterns[0]
        if isinstance(pat, str) and pat == expected_pattern:
            scores["config_has_placeholder_patterns"] = 1.0

    # Load files
    src_text = read_text_safe(src_path) or ""
    out_es_text = read_text_safe(out_es) or ""
    out_fr_text = read_text_safe(out_fr) or ""
    glossary_rows = load_csv_safe(glossary_path) or []
    # Placeholder regex
    placeholder_re = None
    if isinstance(placeholder_patterns, list) and placeholder_patterns:
        placeholder_re = build_placeholder_regex(placeholder_patterns)

    # Check localized files exist and non-empty
    if out_es.exists() and out_fr.exists() and out_es_text.strip() != "" and out_fr_text.strip() != "":
        scores["localized_files_exist"] = 1.0

    # Structure preservation checks
    src_seq = structure_sequence(src_text)
    es_seq = structure_sequence(out_es_text)
    fr_seq = structure_sequence(out_fr_text)
    if src_seq and src_seq == es_seq:
        scores["structure_preserved_es"] = 1.0
    if src_seq and src_seq == fr_seq:
        scores["structure_preserved_fr"] = 1.0

    # Placeholder preservation
    if placeholder_re:
        src_placeholders = extract_placeholders(src_text, placeholder_re)
        if src_placeholders:
            es_preserved = sum(1 for ph in src_placeholders if ph in out_es_text)
            fr_preserved = sum(1 for ph in src_placeholders if ph in out_fr_text)
            if es_preserved == len(src_placeholders):
                scores["placeholders_preserved_es"] = 1.0
            if fr_preserved == len(src_placeholders):
                scores["placeholders_preserved_fr"] = 1.0

    # Preserve terms checks
    terms = ["Northstar Capital", "Northstar Flex"]
    if out_es_text and all(t in out_es_text for t in terms):
        scores["preserve_terms_preserved_es"] = 1.0
    if out_fr_text and all(t in out_fr_text for t in terms):
        scores["preserve_terms_preserved_fr"] = 1.0

    # Glossary applied checks: count translated terms presence in outputs
    if glossary_rows:
        es_glossary_count = compute_glossary_occurrences(out_es_text, glossary_rows, "es-ES")
        fr_glossary_count = compute_glossary_occurrences(out_fr_text, glossary_rows, "fr-FR")
        # Expect at least one glossary match per locale for success
        if es_glossary_count > 0:
            scores["glossary_applied_es"] = 1.0
        if fr_glossary_count > 0:
            scores["glossary_applied_fr"] = 1.0

    # Numbers and emails preserved
    tokens = extract_numbers_and_emails(src_text)
    if tokens:
        if all(tok in out_es_text for tok in tokens):
            scores["numbers_and_email_preserved_es"] = 1.0
        if all(tok in out_fr_text for tok in tokens):
            scores["numbers_and_email_preserved_fr"] = 1.0

    # QA report checks
    report = load_json_safe(qa_report_path)
    if isinstance(report, dict) and "locales" in report and isinstance(report["locales"], dict):
        locales = report["locales"]
        if "es-ES" in locales and "fr-FR" in locales:
            scores["qa_report_exists"] = 1.0

        for loc, out_text, diff_path in [
            ("es-ES", out_es_text, diff_es_path),
            ("fr-FR", out_fr_text, diff_fr_path),
        ]:
            entry = locales.get(loc, {})
            # md5 check
            out_file_path_str = entry.get("output")
            md5_reported = entry.get("md5")
            # Resolve expected out path
            expected_out = ws / "output" / loc / "products.md"
            if isinstance(md5_reported, str) and out_text:
                md5_actual = md5_of_text(out_text)
                if md5_actual == md5_reported:
                    if loc == "es-ES":
                        scores["qa_md5_matches_es"] = 1.0
                    else:
                        scores["qa_md5_matches_fr"] = 1.0

            # lines_total consistency: accept either source lines or output lines
            lt = entry.get("lines_total")
            if isinstance(lt, int):
                src_lines = len(src_text.splitlines()) if src_text else 0
                out_lines = len(out_text.splitlines()) if out_text else 0
                if lt in (src_lines, out_lines):
                    if loc == "es-ES":
                        scores["qa_lines_total_consistent_es"] = 1.0
                    else:
                        scores["qa_lines_total_consistent_fr"] = 1.0

            # diff existence and non-empty
            diff_text = read_text_safe(diff_path) or ""
            if diff_text.strip():
                if loc == "es-ES":
                    scores["diff_files_exist_nonempty_es"] = 1.0
                else:
                    scores["diff_files_exist_nonempty_fr"] = 1.0

            # lines_changed consistency
            lc = entry.get("lines_changed")
            if isinstance(lc, int):
                # Prefer reading provided diff; fallback to recomputing count if empty
                diff_changes = count_unified_diff_changes(diff_text)
                if diff_changes == 0 and out_text and src_text:
                    # recompute unified diff ourselves
                    import difflib
                    src_lines = src_text.splitlines(keepends=True)
                    out_lines_k = out_text.splitlines(keepends=True)
                    ud = ''.join(difflib.unified_diff(src_lines, out_lines_k))
                    diff_changes = count_unified_diff_changes(ud)
                if lc == diff_changes:
                    if loc == "es-ES":
                        scores["qa_lines_changed_consistent_es"] = 1.0
                    else:
                        scores["qa_lines_changed_consistent_fr"] = 1.0

            # glossary_matches consistency
            gm = entry.get("glossary_matches")
            if isinstance(gm, int):
                if glossary_rows:
                    expected_gm = compute_glossary_occurrences(out_text, glossary_rows, loc)
                else:
                    expected_gm = 0
                if gm == expected_gm:
                    if loc == "es-ES":
                        scores["qa_glossary_matches_reported_es"] = 1.0
                    else:
                        scores["qa_glossary_matches_reported_fr"] = 1.0

            # preserved_placeholders consistency
            pp = entry.get("preserved_placeholders")
            if isinstance(pp, int) and placeholder_re:
                src_placeholders = extract_placeholders(src_text, placeholder_re)
                expected_pp = sum(1 for ph in src_placeholders if ph in out_text)
                if pp == expected_pp:
                    if loc == "es-ES":
                        scores["qa_preserved_placeholders_reported_es"] = 1.0
                    else:
                        scores["qa_preserved_placeholders_reported_fr"] = 1.0

            # preserved_terms consistency
            pt = entry.get("preserved_terms")
            if isinstance(pt, int):
                expected_pt = 0
                # Count occurrences of each term in output that should remain unchanged
                for t in ["Northstar Capital", "Northstar Flex"]:
                    expected_pt += out_text.count(t)
                if pt == expected_pt:
                    if loc == "es-ES":
                        scores["qa_preserved_terms_reported_es"] = 1.0
                    else:
                        scores["qa_preserved_terms_reported_fr"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()