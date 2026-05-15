import json
import sys
import re
import csv
import subprocess
from pathlib import Path
from typing import Optional, Tuple, Dict, List


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _normalize_newlines(s: str) -> str:
    return s.replace("\r\n", "\n").replace("\r", "\n")


def _safe_run_quote_extractor(workspace: Path) -> Optional[str]:
    script = workspace / "input" / "quote_extractor.py"
    md = workspace / "input" / "newsletter_draft.md"
    if not script.exists() or not md.exists():
        return None
    try:
        proc = subprocess.run(
            [sys.executable, str(script), str(md)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
        combined = proc.stdout + proc.stderr
        return _normalize_newlines(combined)
    except Exception:
        return None


def _count_lines(path: Path, treat_csv_data_rows: bool = False) -> Optional[int]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    if not treat_csv_data_rows:
        return len(text.splitlines())
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return 0
        return max(0, len(rows) - 1)
    except Exception:
        return None


def _parse_report_sections(report_text: str) -> Dict[str, Tuple[int, int]]:
    lower = report_text.lower()
    names = ["input inventory", "quote verification", "command analysis"]
    positions = {}
    for name in names:
        idx = lower.find(name)
        if idx != -1:
            positions[name] = idx
    sections = {}
    sorted_items = sorted(positions.items(), key=lambda x: x[1])
    for i, (name, start) in enumerate(sorted_items):
        end = len(report_text)
        if i + 1 < len(sorted_items):
            end = sorted_items[i + 1][1]
        sections[name] = (start, end)
    return sections


def _extract_quotes_with_citations(newsletter_text: str) -> List[Dict]:
    quotes = []
    lines = newsletter_text.splitlines()
    for i, line in enumerate(lines, start=1):
        for m in re.finditer(r'"([^"]+)"', line):
            quote_text = m.group(1).strip()
            tail = line[m.end():]
            cm = re.search(r'\(([^)]+)\)', tail)
            citation_text = cm.group(1).strip() if cm else ""
            quotes.append({"line": i, "quote": quote_text, "citation": citation_text})
    return quotes


def _load_city_codes(workspace: Path) -> Optional[Dict[str, Dict[str, str]]]:
    csv_path = workspace / "input" / "ordinance_sections.csv"
    if not csv_path.exists():
        return None
    try:
        mapping = {}
        with csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                code = (row.get("code") or "").strip()
                title = (row.get("title") or "").strip()
                text = (row.get("text") or "").strip()
                if code:
                    mapping[code] = {"title": title, "text": text}
        return mapping
    except Exception:
        return None


def _load_hoa_rules(workspace: Path) -> Optional[Dict[str, str]]:
    txt_path = workspace / "input" / "hoa_rules.txt"
    if not txt_path.exists():
        return None
    try:
        rules = {}
        lines = txt_path.read_text(encoding="utf-8").splitlines()
        for ln in lines:
            m = re.match(r'\s*([0-9]+(?:\.[0-9]+)?)\s+(.*)', ln)
            if m:
                rule_num = m.group(1).strip()
                rest = m.group(2).strip()
                rules[rule_num] = rest
        return rules
    except Exception:
        return None


def _determine_source_and_official(citation: str, city_codes: Optional[Dict[str, Dict[str, str]]], hoa_rules: Optional[Dict[str, str]]) -> Tuple[str, Optional[str], Optional[str]]:
    c = citation.strip()
    hoa_match = re.search(r'HOA\s*Rule\s*([0-9]+(?:\.[0-9]+)?)', c, flags=re.I)
    if hoa_match:
        rule = hoa_match.group(1)
        official_text = None
        if hoa_rules and rule in hoa_rules:
            official_text = hoa_rules[rule]
        return "hoa", rule, official_text
    sec_match = re.search(r'§\s*([0-9A-Za-z\-\(\)]+)', c)
    code = None
    if sec_match:
        code = sec_match.group(1)
    else:
        mc_match = re.search(r'Municipal\s+Code\s*([0-9A-Za-z\-\(\)]+)', c, flags=re.I)
        if mc_match:
            code = mc_match.group(1)
    official_text = None
    if city_codes and code and code in city_codes:
        official_text = city_codes[code]["text"]
    return "city", code, official_text


def _is_accurate(quote: str, official_text: Optional[str]) -> bool:
    if not official_text:
        return False
    q = quote.casefold()
    t = official_text.casefold()
    return q in t


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "verification_report_exists": 0.0,
        "report_has_required_sections": 0.0,
        "input_inventory_lists_all_files": 0.0,
        "input_inventory_counts_correct": 0.0,
        "command_log_captured_correctly": 0.0,
        "command_analysis_summarizes_output": 0.0,
        "quote_verification_includes_all_quotes": 0.0,
        "quote_verification_uses_correct_sources": 0.0,
        "quote_verification_verdicts_correct": 0.0,
        "email_exists": 0.0,
        "email_addresses_editor": 0.0,
        "email_includes_corrections_with_citations": 0.0,
        "email_tone_and_closing": 0.0,
    }

    input_dir = workspace / "input"
    output_dir = workspace / "output"
    report_path = output_dir / "verification_report.md"
    cmd_log_path = output_dir / "command_log.txt"
    email_path = output_dir / "email_to_editor.txt"

    newsletter_path = input_dir / "newsletter_draft.md"
    csv_path = input_dir / "ordinance_sections.csv"
    hoa_path = input_dir / "hoa_rules.txt"
    extractor_path = input_dir / "quote_extractor.py"

    expected_log = _safe_run_quote_extractor(workspace)

    city_codes = _load_city_codes(workspace)
    hoa_rules = _load_hoa_rules(workspace)

    newsletter_text = _read_text(newsletter_path) or ""
    quotes = _extract_quotes_with_citations(newsletter_text)

    expected_items = []
    for item in quotes:
        citation = item["citation"]
        source_type, code_or_rule, official_text = _determine_source_and_official(citation, city_codes, hoa_rules)
        accurate = _is_accurate(item["quote"], official_text)
        expected_items.append({
            "line": item["line"],
            "quote": item["quote"],
            "citation": citation,
            "source_type": source_type,
            "code_or_rule": code_or_rule,
            "official_text": official_text,
            "accurate": accurate
        })

    report_text = _read_text(report_path)
    cmd_log_text = _read_text(cmd_log_path)
    email_text = _read_text(email_path)

    if report_text is not None:
        scores["verification_report_exists"] = 1.0

    if report_text is not None:
        sections = _parse_report_sections(report_text)
        has_input = "input inventory" in sections
        has_quote = "quote verification" in sections
        has_command = "command analysis" in sections
        if has_input:
            input_start = sections["input inventory"][0]
            leading = report_text[:input_start]
            leading_clean = leading.strip()
            input_first = (len(leading_clean) == 0)
        else:
            input_first = False
        if has_input and has_quote and has_command and input_first:
            scores["report_has_required_sections"] = 1.0

    if report_text is not None:
        sections = _parse_report_sections(report_text)
        inv_ok = 0
        inv_total = 0
        cnt_ok = 0
        cnt_total = 0
        if "input inventory" in sections:
            start, end = sections["input inventory"]
            inv_text = report_text[start:end]
            present_files = []
            if input_dir.exists():
                for p in sorted(input_dir.iterdir()):
                    if p.is_file():
                        present_files.append(p)
            for p in present_files:
                inv_total += 1
                fname = f"input/{p.name}"
                lines = inv_text.splitlines()
                matched_line = None
                for ln in lines:
                    if p.name in ln or fname in ln:
                        matched_line = ln
                        break
                if matched_line is not None:
                    inv_ok += 1
                    cnt_total += 1
                    is_csv = p.suffix.lower() == ".csv"
                    expected_count = _count_lines(p, treat_csv_data_rows=is_csv)
                    if expected_count is not None:
                        nums = re.findall(r'\d+', matched_line)
                        ext = p.suffix.lower().lstrip(".")
                        has_format = (ext in matched_line.lower())
                        if str(expected_count) in nums and has_format:
                            cnt_ok += 1
        if inv_total > 0:
            scores["input_inventory_lists_all_files"] = inv_ok / inv_total
        if cnt_total > 0:
            scores["input_inventory_counts_correct"] = cnt_ok / cnt_total

    if expected_log is not None and cmd_log_text is not None:
        if _normalize_newlines(expected_log).strip() == _normalize_newlines(cmd_log_text).strip():
            scores["command_log_captured_correctly"] = 1.0

    if report_text is not None and expected_log is not None:
        sections = _parse_report_sections(report_text)
        if "command analysis" in sections:
            start, end = sections["command analysis"]
            ca_text = report_text[start:end]
            expected_lines = [itm["line"] for itm in expected_items]
            expected_count = len(expected_items)
            count_ok = False
            m = re.search(r'(\d+)\s+quote', ca_text, flags=re.I)
            if m and int(m.group(1)) == expected_count:
                count_ok = True
            nums = set(int(x) for x in re.findall(r'\b(\d{1,3})\b', ca_text))
            lines_ok = all(ln in nums for ln in expected_lines)
            if count_ok and lines_ok:
                scores["command_analysis_summarizes_output"] = 1.0

    if report_text is not None:
        sections = _parse_report_sections(report_text)
        if "quote verification" in sections:
            start, end = sections["quote verification"]
            qv_text = report_text[start:end]
            include_hits = 0
            include_total = 0
            sources_hits = 0
            sources_total = 0
            verdict_hits = 0
            verdict_total = 0
            for itm in expected_items:
                include_total += 1
                citation = itm["citation"]
                idx = qv_text.find(citation) if citation else -1
                window = ""
                if idx != -1:
                    left = max(0, idx - 400)
                    right = min(len(qv_text), idx + 400)
                    window = qv_text[left:right]
                else:
                    key = itm["code_or_rule"] or ""
                    if key:
                        idx2 = qv_text.find(key)
                        if idx2 != -1:
                            left = max(0, idx2 - 400)
                            right = min(len(qv_text), idx2 + 400)
                            window = qv_text[left:right]
                has_quote = itm["quote"] in window if window else False
                has_citation = citation in window if window else False
                if has_quote and has_citation:
                    include_hits += 1

                sources_total += 1
                official_text = itm["official_text"] or ""
                has_official = official_text and (official_text in window)
                has_no_match_notation = ("no match found" in window.lower())
                if (has_official) or (not official_text and has_no_match_notation):
                    sources_hits += 1

                verdict_total += 1
                expected_verdict = "Accurate" if itm["accurate"] else "Mismatch"
                has_verdict = expected_verdict.lower() in window.lower()
                if has_verdict:
                    verdict_hits += 1

            if include_total > 0:
                scores["quote_verification_includes_all_quotes"] = include_hits / include_total
            if sources_total > 0:
                scores["quote_verification_uses_correct_sources"] = sources_hits / sources_total
            if verdict_total > 0:
                scores["quote_verification_verdicts_correct"] = verdict_hits / verdict_total

    if email_text is not None:
        scores["email_exists"] = 1.0

    if email_text is not None:
        if re.search(r'\bLydia\b', email_text):
            scores["email_addresses_editor"] = 1.0

    if email_text is not None:
        mismatch_items = [itm for itm in expected_items if not itm["accurate"]]
        if mismatch_items:
            hits = 0
            for itm in mismatch_items:
                citation = itm["citation"]
                official_text = itm["official_text"] or ""
                found = False
                idx = email_text.find(citation) if citation else -1
                window = ""
                if idx != -1:
                    left = max(0, idx - 400)
                    right = min(len(email_text), idx + 400)
                    window = email_text[left:right]
                if citation and citation in email_text:
                    if (official_text and (official_text in (window or email_text))) or re.search(r'correct|correction|corrected', window or email_text, flags=re.I):
                        found = True
                if found:
                    hits += 1
            if len(mismatch_items) > 0:
                scores["email_includes_corrections_with_citations"] = hits / len(mismatch_items)
        else:
            scores["email_includes_corrections_with_citations"] = 0.0

    if email_text is not None:
        closing_ok = bool(re.search(r'best regards|sincerely|thank you|thanks|regards|best,', email_text, flags=re.I))
        polite_tone = bool(re.search(r'please|thank', email_text, flags=re.I))
        if closing_ok and polite_tone:
            scores["email_tone_and_closing"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()