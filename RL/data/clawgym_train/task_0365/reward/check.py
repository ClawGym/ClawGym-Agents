import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="utf-8-sig")
        except Exception:
            return None


def _read_lines(path: Path) -> Optional[List[str]]:
    txt = _read_text(path)
    if txt is None:
        return None
    return txt.splitlines()


def _load_json(path: Path) -> Optional[Any]:
    txt = _read_text(path)
    if txt is None:
        return None
    try:
        return json.loads(txt)
    except Exception:
        return None


def _simple_yaml_load_map(path: Path) -> Optional[Dict[str, str]]:
    """
    Very simple YAML parser for top-level mapping of key: "value" pairs.
    Does not support nesting. Intended for the provided tibetan_phrases.yaml.
    """
    lines = _read_lines(path)
    if lines is None:
        return None
    result: Dict[str, str] = {}
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if ":" not in s:
            continue
        key, val = s.split(":", 1)
        key = key.strip()
        val = val.strip()
        # remove possible quotes
        if val.startswith('"') and val.endswith('"'):
            val = val[1:-1]
        elif val.startswith("'") and val.endswith("'"):
            val = val[1:-1]
        result[key] = val
    return result


def _run_scanner_and_capture(workspace: Path) -> Tuple[Optional[Dict[str, Any]], Optional[List[str]]]:
    """
    Run the scanner as specified: python3 input/pii_scan.py input/transcripts
    Capture stdout JSON and WARNING lines from stderr.
    Returns (json_obj, warning_lines) or (None, None) if failure.
    """
    script_path = workspace / "input" / "pii_scan.py"
    transcripts_path = workspace / "input" / "transcripts"
    if not script_path.exists():
        return None, None
    try:
        proc = subprocess.run(
            [sys.executable, str(script_path), str(transcripts_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        return None, None
    try:
        out_json = json.loads(proc.stdout)
    except Exception:
        return None, None
    stderr_lines = proc.stderr.splitlines()
    warn_lines = [ln.strip() for ln in stderr_lines if ln.strip().startswith("WARNING:")]
    return out_json, warn_lines


def _extract_domain(url: str) -> str:
    try:
        p = urlparse(url if re.match(r"^[a-z]+://", url) else "http://" + url)
        return p.netloc.lower()
    except Exception:
        return ""


def _classify_source(publisher: str, url: str) -> Optional[str]:
    pub = (publisher or "").lower()
    domain = _extract_domain(url)
    # University or national research council heuristics
    uni_kw = [
        "university",
        "college",
        "institute",
        "polytechnic",
        "universidad",
        "université",
        "universität",
        "università",
        "universidade",
        "research council",
        "ukri",
        "esrc",
        "ahrc",
        "sshrc",
        "nserc",
        "nsf",
        "nih",
        "arc",
        "cnrs",
        "dfg",
    ]
    uni_dom_patterns = [".edu", ".ac.", ".edu.", ".ac.uk"]
    if any(k in pub for k in uni_kw) or any(p in domain for p in uni_dom_patterns):
        return "university_or_council"

    # Data protection authority/commissioner heuristics
    dpa_kw = [
        "commissioner",
        "data protection",
        "information commissioner",
        "privacy commissioner",
        "supervisory authority",
        "authority",
        "commission",
        "protección de datos",
        "protection des données",
    ]
    gov_dom_patterns = [
        ".gov",
        ".gouv",
        "gov.uk",
        "canada.ca",
        ".gc.ca",
        "govt.nz",
        "gov.au",
        "gov.in",
        "go.jp",
        "go.kr",
        "go.id",
        "go.th",
        "gob.",
        "ico.org.uk",
        "cnil.fr",
        "oaic.gov.au",
        "dataprotection.ie",
        "edpb.europa.eu",
        "edps.europa.eu",
        "oipc",
    ]
    if any(k in pub for k in dpa_kw) or any(p in domain for p in gov_dom_patterns):
        return "data_protection_authority"

    return None


def _find_section_block(lines: List[str], start_tokens: List[str], end_tokens: List[str]) -> List[str]:
    """
    Find lines between a start heading (line containing any of start_tokens)
    and the next heading line containing any end_tokens. Returns block lines (excluding start line).
    """
    start_idx = None
    for i, ln in enumerate(lines):
        low = ln.lower()
        if any(tok.lower() in low for tok in start_tokens):
            start_idx = i
            break
    if start_idx is None:
        return []
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        low = lines[j].lower()
        if any(tok.lower() in low for tok in end_tokens):
            end_idx = j
            break
    return lines[start_idx + 1 : end_idx]


def _contains_number_with_keyword(block_lines: List[str], number: int, keywords: List[str]) -> bool:
    num_str = str(number)
    for ln in block_lines:
        low = ln.lower()
        if num_str in ln and any(kw in low for kw in keywords):
            return True
    return False


def _count_action_items_with_date_and_owner(block_lines: List[str]) -> int:
    count = 0
    date_re = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
    owner_tokens = [
        "pi",
        "ra",
        "it",
        "owner",
        "data steward",
        "coordinator",
        "manager",
        "lead",
        "analyst",
        "engineer",
    ]
    for ln in block_lines:
        s = ln.strip()
        # Consider bullet or numbered lines as action items
        if re.match(r"^[-*\u2022]\s+", s) or re.match(r"^\d+[\.\)]\s+", s):
            if date_re.search(s):
                low = s.lower()
                if any(re.search(r"\b" + re.escape(tok) + r"\b", low) for tok in owner_tokens):
                    count += 1
    return count


def _has_consent_no_action(block_lines: List[str]) -> bool:
    for ln in block_lines:
        s = ln.strip().lower()
        if ("consent" in s) and ("no" in s):
            # Ensure it's an action item line
            if re.match(r"^[-*\u2022]\s+", ln.strip()) or re.match(r"^\d+[\.\)]\s+", ln.strip()):
                return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "scan_results_json_matches": 0.0,
        "scan_warnings_log_matches": 0.0,
        "sources_json_structure": 0.0,
        "sources_categories_covered": 0.0,
        "meeting_notes_bilingual_title": 0.0,
        "meeting_notes_headings_present": 0.0,
        "meeting_notes_risks_counts": 0.0,
        "meeting_notes_warning_interpretation": 0.0,
        "meeting_notes_guidance_integration": 0.0,
        "meeting_notes_action_items_count": 0.0,
        "meeting_notes_consent_no_action_item": 0.0,
    }

    # 1) Scanner outputs: compute expected by running scanner via subprocess
    expected_json, expected_warn_lines = _run_scanner_and_capture(workspace)

    # Compare scan_results.json
    out_scan_path = workspace / "output" / "scan_results.json"
    saved_scan_json = _load_json(out_scan_path)
    if expected_json is not None and isinstance(saved_scan_json, dict):
        # Deep comparison ignoring insignificant formatting
        if saved_scan_json == expected_json:
            scores["scan_results_json_matches"] = 1.0

    # Compare scan_warnings.log: extract WARNING lines
    out_warn_path = workspace / "output" / "scan_warnings.log"
    saved_warn_lines_raw = _read_lines(out_warn_path)
    if expected_warn_lines is not None and saved_warn_lines_raw is not None:
        saved_warning_only = [ln.strip() for ln in saved_warn_lines_raw if ln.strip().startswith("WARNING:")]
        if saved_warning_only == expected_warn_lines:
            scores["scan_warnings_log_matches"] = 1.0

    # 2) sources.json checks
    sources_path = workspace / "output" / "sources.json"
    sources = _load_json(sources_path)
    valid_structure = False
    categories_ok = False
    if isinstance(sources, list) and len(sources) == 2:
        structure_ok = True
        categories: List[Optional[str]] = []
        for obj in sources:
            if not isinstance(obj, dict):
                structure_ok = False
                break
            # required fields
            if not all(k in obj for k in ["title", "publisher", "url"]):
                structure_ok = False
                break
            if "date" not in obj:
                structure_ok = False
                break
            # recommendations
            recs = obj.get("recommendations")
            if not isinstance(recs, list) or len(recs) != 3 or not all(isinstance(r, str) and r.strip() for r in recs):
                structure_ok = False
                break
            # url basic check
            url = obj.get("url", "")
            if not isinstance(url, str) or not url.strip() or not (url.startswith("http://") or url.startswith("https://")):
                structure_ok = False
                break
            # classify
            cat = _classify_source(str(obj.get("publisher", "")), str(obj.get("url", "")))
            categories.append(cat)
        if structure_ok:
            valid_structure = True
            scores["sources_json_structure"] = 1.0
        # Check categories coverage: one university/council and one data protection authority
        if len(categories) == 2 and set(categories) == {"university_or_council", "data_protection_authority"}:
            categories_ok = True
            scores["sources_categories_covered"] = 1.0

    # 3) meeting_notes.md checks
    notes_path = workspace / "output" / "meeting_notes.md"
    notes_lines = _read_lines(notes_path)
    tibetan_map = _simple_yaml_load_map(workspace / "input" / "tibetan_phrases.yaml") or {}

    # Bilingual title line
    if notes_lines:
        # first non-empty line
        first_line = ""
        for ln in notes_lines:
            if ln.strip():
                first_line = ln.strip()
                break
        tib_title = tibetan_map.get("title", "")
        if tib_title and tib_title in first_line:
            # Check English presence: at least 5 ASCII letters
            ascii_letters = re.findall(r"[A-Za-z]", first_line)
            if len(ascii_letters) >= 5:
                scores["meeting_notes_bilingual_title"] = 1.0

        # Headings presence
        risks_tib = tibetan_map.get("risks_section", "")
        guidance_tib = tibetan_map.get("guidance_section", "")
        action_tib = tibetan_map.get("action_items", "")
        # English headings as specified
        risks_eng = "Risks found in local transcripts"
        guidance_eng = "External guidance summary"
        action_eng = "Action Items"

        has_risks_tib = any(risks_tib and (risks_tib in ln) for ln in notes_lines)
        has_guid_tib = any(guidance_tib and (guidance_tib in ln) for ln in notes_lines)
        has_action_tib = any(action_tib and (action_tib in ln) for ln in notes_lines)
        has_risks_eng = any(risks_eng.lower() in ln.lower() for ln in notes_lines)
        has_guid_eng = any(guidance_eng.lower() in ln.lower() for ln in notes_lines)
        has_action_eng = any(action_eng.lower() in ln.lower() for ln in notes_lines)

        if has_risks_tib and has_guid_tib and has_action_tib and has_risks_eng and has_guid_eng and has_action_eng:
            scores["meeting_notes_headings_present"] = 1.0

        # Section blocks
        end_tokens = []
        # build a set of possible end tokens for block detection
        for t in [guidance_tib, action_tib, guidance_eng, action_eng]:
            if t:
                end_tokens.append(t)
        # Risks block between risks heading and next section
        risks_block = _find_section_block(
            notes_lines,
            start_tokens=[tok for tok in [risks_tib, risks_eng] if tok],
            end_tokens=end_tokens,
        )

        # Validate risk counts summary
        if isinstance(saved_scan_json, dict):
            summary = saved_scan_json.get("summary", {})
            files_scanned = summary.get("files_scanned")
            email_count = summary.get("email_count")
            phone_count = summary.get("phone_count")
            dob_count = summary.get("dob_like_count")
            if all(isinstance(x, int) for x in [files_scanned, email_count, phone_count, dob_count]):
                has_files_count = _contains_number_with_keyword(risks_block, files_scanned, ["file", "scan"])
                has_email_count = _contains_number_with_keyword(risks_block, email_count, ["email"])
                has_phone_count = _contains_number_with_keyword(risks_block, phone_count, ["phone"])
                has_dob_count = _contains_number_with_keyword(risks_block, dob_count, ["dob"])
                if has_files_count and has_email_count and has_phone_count and has_dob_count:
                    scores["meeting_notes_risks_counts"] = 1.0

        # Interpret warnings
        interpreted_all = False
        if expected_warn_lines is not None:
            if not expected_warn_lines:
                # No warnings to interpret; consider satisfied if risks section exists
                interpreted_all = True
            else:
                interpreted = True
                for w in expected_warn_lines:
                    # w format: "WARNING: filename: message"
                    # Check presence of filename and key terms in risks block
                    m = re.match(r"WARNING:\s*([^:]+):\s*(.*)$", w)
                    if not m:
                        interpreted = False
                        break
                    fname = m.group(1).strip()
                    msg = m.group(2).strip().lower()
                    # Build key terms
                    terms = []
                    if "consent" in msg:
                        terms.append("consent")
                    if "unknown" in msg:
                        terms.append("unknown")
                    if "no" in msg:
                        terms.append("no")
                    if "read" in msg or "could not read" in msg:
                        terms.append("read")
                    # Check block contains filename and at least one term
                    block_text = "\n".join(risks_block).lower()
                    if (fname.lower() not in block_text) or (not any(t in block_text for t in terms if t)):
                        interpreted = False
                        break
                interpreted_all = interpreted
        if interpreted_all:
            scores["meeting_notes_warning_interpretation"] = 1.0

        # Guidance integration block
        guidance_block = _find_section_block(
            notes_lines,
            start_tokens=[tok for tok in [guidance_tib, guidance_eng] if tok],
            end_tokens=[tok for tok in [action_tib, action_eng] if tok],
        )
        guidance_text = "\n".join(guidance_block) if guidance_block else ""
        if isinstance(sources, list) and len(sources) == 2 and guidance_text:
            names_ok = True
            recs_ok = True
            for obj in sources:
                pub = str(obj.get("publisher", ""))
                title = str(obj.get("title", ""))
                if (pub and pub not in guidance_text) or (title and title not in guidance_text):
                    names_ok = False
                recs = obj.get("recommendations", [])
                if not isinstance(recs, list) or len(recs) != 3:
                    recs_ok = False
                else:
                    for r in recs:
                        if not isinstance(r, str) or r.strip() == "":
                            recs_ok = False
                            break
                        if r not in guidance_text:
                            recs_ok = False
                            break
            if names_ok and recs_ok:
                scores["meeting_notes_guidance_integration"] = 1.0

        # Action items block
        action_block = _find_section_block(
            notes_lines,
            start_tokens=[tok for tok in [action_tib, action_eng] if tok],
            end_tokens=[],
        )
        if action_block:
            count_items = _count_action_items_with_date_and_owner(action_block)
            if count_items >= 5:
                scores["meeting_notes_action_items_count"] = 1.0

            # Consent: no action item requirement
            has_no_consent_warning = False
            if expected_warn_lines:
                for w in expected_warn_lines:
                    if "consent" in w.lower() and "no" in w.lower():
                        has_no_consent_warning = True
                        break
            if not has_no_consent_warning:
                # Not applicable, consider satisfied
                scores["meeting_notes_consent_no_action_item"] = 1.0
            else:
                if _has_consent_no_action(action_block):
                    scores["meeting_notes_consent_no_action_item"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()