import json
import re
import sys
import csv
from pathlib import Path
from typing import List, Tuple, Dict, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _csv_read_rows(path: Path) -> Tuple[Optional[List[str]], Optional[List[List[str]]]]:
    if not path.exists():
        return None, None
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return [], []
        header = rows[0]
        data = rows[1:]
        return header, data
    except Exception:
        return None, None


def _count_lines(path: Path) -> Optional[int]:
    text = _safe_read_text(path)
    if text is None:
        return None
    return len(text.splitlines())


def _parse_disclaimers(path: Path) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
    text = _safe_read_text(path)
    if text is None:
        return None, "missing or unreadable disclaimers.txt"
    lines = text.splitlines()
    disclaimers: Dict[str, str] = {}
    current_id: Optional[str] = None
    current_block: List[str] = []
    try:
        for line in lines:
            if line.startswith("ID: "):
                if current_id is not None:
                    disclaimers[current_id] = "\n".join(current_block).strip()
                current_id = line[len("ID: "):].strip()
                current_block = [line]
            else:
                current_block.append(line)
        if current_id is not None:
            disclaimers[current_id] = "\n".join(current_block).strip()
        if not disclaimers:
            return disclaimers, "no ID blocks found in disclaimers.txt"
        return disclaimers, None
    except Exception as e:
        return None, f"error parsing disclaimers.txt: {e}"


def _extract_ein(text: str) -> Optional[str]:
    if not text:
        return None
    m = re.search(r"\b(\d{2}-\d{7}|\d{9})\b", text)
    if not m:
        return None
    digits = re.sub(r"\D", "", m.group(1))
    if len(digits) == 9:
        return digits
    return None


def _has_required_phrase(text: str) -> Optional[str]:
    if not text:
        return None
    phrases = [
        "tax-deductible",
        "IRS",
        "No goods or services were provided",
    ]
    for ph in phrases:
        if re.search(re.escape(ph), text, flags=re.IGNORECASE):
            return ph
    return None


def _normalize_ein(ein: str) -> Optional[str]:
    if ein is None:
        return None
    digits = re.sub(r"\D", "", ein)
    return digits if len(digits) == 9 else None


def _bool_from_str(s: str) -> Optional[bool]:
    if s is None:
        return None
    sl = s.strip().lower()
    if sl in ("true", "t", "yes"):
        return True
    if sl in ("false", "f", "no"):
        return False
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "output_verified_csv_exists_and_header": 0.0,
        "output_verified_csv_row_count": 0.0,
        "output_verified_csv_ein_and_source_correct": 0.0,
        "output_verified_csv_verified_flags_correct": 0.0,
        "output_verified_csv_reasons_quality": 0.0,
        "status_summary_exists": 0.0,
        "status_summary_totals_correct": 0.0,
        "status_summary_skipped_lines_reported": 0.0,
        "status_summary_field_count_output_present": 0.0,
        "status_summary_line_counts_present": 0.0,
        "status_summary_disclaimers_errors_note": 0.0,
        "status_summary_ein_source_summary": 0.0,
    }

    input_csv_path = workspace / "input" / "charity_list.csv"
    disclaimers_path = workspace / "input" / "disclaimers.txt"
    out_csv_path = workspace / "output" / "verified_charities.csv"
    out_md_path = workspace / "output" / "status_summary.md"

    in_header, in_rows = _csv_read_rows(input_csv_path)
    disclaimers_map, disclaimers_parse_error = _parse_disclaimers(disclaimers_path)
    csv_total_lines = _count_lines(input_csv_path)
    disclaimers_total_lines = _count_lines(disclaimers_path)

    expected_processed: List[Dict[str, Optional[str]]] = []
    malformed_lines: List[Tuple[int, str]] = []

    if in_header is not None and in_rows is not None:
        for idx, row in enumerate(in_rows, start=2):
            if len(row) != 6:
                malformed_lines.append((idx, f"expected 6 fields, got {len(row)}"))
                continue
            name, claimed_status, ein_csv, website, notes, disclaimer_id = row
            record = {
                "name": name.strip(),
                "claimed_status": claimed_status.strip(),
                "ein_csv": ein_csv.strip(),
                "disclaimer_id": disclaimer_id.strip(),
            }
            expected_processed.append(record)

    expected_name_to_output: Dict[str, Dict[str, Optional[str]]] = {}
    expected_verified_flags: Dict[str, bool] = {}
    ein_source_counts = {"csv": 0, "disclaimer": 0}

    if expected_processed and disclaimers_map is not None:
        for rec in expected_processed:
            name = rec["name"]
            claimed_status = rec["claimed_status"]
            ein_csv = rec["ein_csv"]
            disclaimer_id = rec["disclaimer_id"]

            disclaimer_text = disclaimers_map.get(disclaimer_id, "")
            normalized_csv_ein = _normalize_ein(ein_csv) if ein_csv else None
            source_ein = None
            final_ein = None
            if normalized_csv_ein:
                final_ein = normalized_csv_ein
                source_ein = "csv"
                ein_source_counts["csv"] += 1
            else:
                extracted = _extract_ein(disclaimer_text)
                if extracted:
                    final_ein = extracted
                    source_ein = "disclaimer"
                    ein_source_counts["disclaimer"] += 1

            phrase = _has_required_phrase(disclaimer_text)
            status_ok = bool(re.search(r"501\s*\(c\)\s*3", claimed_status, flags=re.IGNORECASE))
            verified = bool(status_ok and final_ein is not None and phrase is not None)
            expected_verified_flags[name] = verified
            expected_name_to_output[name] = {
                "name": name,
                "ein": final_ein if final_ein is not None else "",
                "verified": "true" if verified else "false",
                "source_ein": source_ein if source_ein is not None else "",
                "phrase": phrase if phrase is not None else "",
                "status_ok": status_ok,
                "disclaimer_id": disclaimer_id,
            }

    expected_processed_count = len(expected_processed)
    expected_malformed_line_numbers = [ln for (ln, _reason) in malformed_lines]

    out_header, out_rows = _csv_read_rows(out_csv_path)
    expected_out_header = ["name", "ein", "verified", "reasons", "source_ein"]
    if out_header is not None:
        if out_header == expected_out_header:
            scores["output_verified_csv_exists_and_header"] = 1.0

    if out_rows is not None:
        if len(out_rows) == expected_processed_count:
            scores["output_verified_csv_row_count"] = 1.0

    out_map: Dict[str, Dict[str, str]] = {}
    if out_rows is not None and out_header == expected_out_header:
        for row in out_rows:
            if len(row) != len(expected_out_header):
                continue
            rec = dict(zip(out_header, row))
            out_map[rec["name"]] = rec

    ein_checks_total = 0
    ein_checks_ok = 0
    if expected_name_to_output and out_map:
        for name, exp in expected_name_to_output.items():
            exp_ein = exp["ein"]
            exp_source = exp["source_ein"]
            if exp_ein:
                ein_checks_total += 1
                got = out_map.get(name)
                if got:
                    got_ein = (got.get("ein") or "").strip()
                    got_src = (got.get("source_ein") or "").strip().lower()
                    if got_ein == exp_ein and got_src == exp_source:
                        ein_checks_ok += 1
    if ein_checks_total > 0:
        scores["output_verified_csv_ein_and_source_correct"] = ein_checks_ok / ein_checks_total

    verified_total = 0
    verified_ok = 0
    if expected_verified_flags and out_map:
        for name, exp_verified in expected_verified_flags.items():
            got = out_map.get(name)
            if got:
                v = _bool_from_str(got.get("verified", ""))
                if v is not None:
                    verified_total += 1
                    if v == exp_verified:
                        verified_ok += 1
    if verified_total > 0:
        scores["output_verified_csv_verified_flags_correct"] = verified_ok / verified_total

    reasons_total = 0
    reasons_ok = 0
    if out_map and expected_name_to_output:
        for name, exp in expected_name_to_output.items():
            got = out_map.get(name)
            if not got:
                continue
            reasons_total += 1
            reasons = (got.get("reasons") or "").strip()
            reasons_low = reasons.lower()
            exp_verified = (exp["verified"] == "true")
            phrase = exp["phrase"]
            src = exp["source_ein"]
            status_ok = exp["status_ok"]
            pass_flag = False
            if exp_verified:
                has_status = ("501" in reasons) or ("status" in reasons_low)
                has_ein_src = False
                if src == "csv":
                    has_ein_src = ("csv" in reasons_low) or ("from csv" in reasons_low) or ("ein from csv" in reasons_low)
                elif src == "disclaimer":
                    has_ein_src = ("disclaimer" in reasons_low) or ("from disclaimer" in reasons_low) or ("ein from disclaimer" in reasons_low)
                has_phrase = False
                if phrase:
                    if re.search(r"\birs\b", reasons, flags=re.IGNORECASE) or \
                       re.search(r"tax-?deductible", reasons, flags=re.IGNORECASE) or \
                       re.search(r"no goods or services were provided", reasons, flags=re.IGNORECASE):
                        has_phrase = True
                pass_flag = bool(has_status and has_ein_src and has_phrase)
            else:
                indicates_missing = ("missing" in reasons_low) or ("no required phrase" in reasons_low) or ("no ein" in reasons_low)
                if not status_ok and ("status" in reasons_low or "501" in reasons):
                    indicates_missing = True
                pass_flag = bool(indicates_missing)
            if pass_flag:
                reasons_ok += 1
    if reasons_total > 0:
        scores["output_verified_csv_reasons_quality"] = reasons_ok / reasons_total

    md_text = _safe_read_text(out_md_path)
    if md_text is not None:
        scores["status_summary_exists"] = 1.0

        totals_ok = False
        if csv_total_lines is not None:
            found_csv_count_ok = False
            for line in md_text.splitlines():
                if re.search(r"input/charity_list\.csv", line, flags=re.IGNORECASE):
                    nums = re.findall(r"\d+", line)
                    for num in nums:
                        if int(num) == csv_total_lines:
                            found_csv_count_ok = True
                            break
                if found_csv_count_ok:
                    break
            found_processed_ok = False
            m_processed = re.search(r"processed[^0-9]*(\d+)|(\d+)[^0-9]*processed", md_text, flags=re.IGNORECASE | re.DOTALL)
            if m_processed:
                num = next((g for g in m_processed.groups() if g), None)
                if num is not None and int(num) == expected_processed_count:
                    found_processed_ok = True
            found_skipped_ok = False
            m_skipped = re.search(r"skipped[^0-9]*(\d+)|(\d+)[^0-9]*skipped", md_text, flags=re.IGNORECASE | re.DOTALL)
            if m_skipped:
                num = next((g for g in m_skipped.groups() if g), None)
                if num is not None and int(num) == len(malformed_lines):
                    found_skipped_ok = True
            totals_ok = bool(found_csv_count_ok and found_processed_ok and found_skipped_ok)
        scores["status_summary_totals_correct"] = 1.0 if totals_ok else 0.0

        skipped_ok = False
        if expected_malformed_line_numbers:
            per_line_hits = []
            for ln in expected_malformed_line_numbers:
                hit = bool(re.search(rf"line[^0-9]*{ln}\b", md_text, flags=re.IGNORECASE) or re.search(rf"\b{ln}\b", md_text))
                per_line_hits.append(hit)
            skipped_ok = all(per_line_hits)
        else:
            if re.search(r"skipped[^0-9]*0|\b0\b[^0-9]*skipped", md_text, flags=re.IGNORECASE):
                skipped_ok = True
        scores["status_summary_skipped_lines_reported"] = 1.0 if skipped_ok else 0.0

        field_count_ok = False
        if re.search(r"field[-\s]?count|fields? count|fields? check", md_text, flags=re.IGNORECASE):
            near_ok = True
            for ln in expected_malformed_line_numbers or []:
                if str(ln) not in md_text:
                    near_ok = False
                    break
            field_count_ok = near_ok
        else:
            has_fields_word = re.search(r"fields?|columns?", md_text, flags=re.IGNORECASE) is not None
            has_line_num = True
            for ln in expected_malformed_line_numbers or []:
                if str(ln) not in md_text:
                    has_line_num = False
            field_count_ok = bool(has_fields_word and has_line_num and (expected_malformed_line_numbers is not None))
        scores["status_summary_field_count_output_present"] = 1.0 if field_count_ok else 0.0

        line_counts_ok = False
        if csv_total_lines is not None and disclaimers_total_lines is not None:
            csv_line_ok = False
            disc_line_ok = False
            for line in md_text.splitlines():
                if "input/charity_list.csv" in line and re.search(rf"\b{csv_total_lines}\b", line):
                    csv_line_ok = True
                if "input/disclaimers.txt" in line and re.search(rf"\b{disclaimers_total_lines}\b", line):
                    disc_line_ok = True
            line_counts_ok = csv_line_ok and disc_line_ok
        scores["status_summary_line_counts_present"] = 1.0 if line_counts_ok else 0.0

        disc_note_ok = False
        if re.search(r"disclaimers?", md_text, flags=re.IGNORECASE):
            if re.search(r"\bnone\b", md_text, flags=re.IGNORECASE) or \
               re.search(r"no (errors?|anomalies?)", md_text, flags=re.IGNORECASE):
                disc_note_ok = True
        scores["status_summary_disclaimers_errors_note"] = 1.0 if disc_note_ok else 0.0

        ein_summary_hits = 0
        ein_summary_total = 0
        exp_csv_count = ein_source_counts.get("csv", 0)
        exp_disc_count = ein_source_counts.get("disclaimer", 0)

        ein_summary_total += 1
        m_csv = re.search(r"(ein[^.\n\r]*csv|csv[^.\n\r]*ein)[^0-9]*(\d+)", md_text, flags=re.IGNORECASE)
        if m_csv:
            num = int(m_csv.group(2))
            if num == exp_csv_count:
                ein_summary_hits += 1

        ein_summary_total += 1
        m_disc = re.search(r"(ein[^.\n\r]*disclaimer|disclaimer[^.\n\r]*ein)[^0-9]*(\d+)", md_text, flags=re.IGNORECASE)
        if m_disc:
            num = int(m_disc.group(2))
            if num == exp_disc_count:
                ein_summary_hits += 1

        if ein_summary_total > 0:
            scores["status_summary_ein_source_summary"] = ein_summary_hits / ein_summary_total

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()