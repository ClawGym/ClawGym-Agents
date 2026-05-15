import sys
import json
import csv
import re
from pathlib import Path


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_load_csv_rows(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                try:
                    rows.append({
                        "year": int(row["year"]),
                        "sector": row["sector"],
                        "workers": int(row["workers"]),
                        "respiratory_cases": int(row["respiratory_cases"]),
                        "injury_cases": int(row["injury_cases"]),
                    })
                except Exception:
                    return None
            return rows
    except Exception:
        return None


def _find_section_range(lines, section_keyword: str):
    sec_kw = section_keyword.lower()
    start = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if re.match(r"^\s*#+\s*", stripped) or stripped.lower() == sec_kw or sec_kw in stripped.lower():
            if re.search(rf"\b{re.escape(sec_kw)}\b", stripped.lower()):
                start = i
                break
    if start is None:
        return None, None
    for j in range(start + 1, len(lines)):
        nxt = lines[j].strip()
        if re.match(r"^\s*#+\s*", nxt):
            return start, j
        if j + 1 < len(lines):
            if re.match(r"^[A-Za-z0-9 ][A-Za-z0-9 ,\-\(\)]+$", nxt) and re.match(r"^[-=]{3,}\s*$", lines[j + 1]):
                return start, j
        if any(k in nxt.lower() for k in ["overview", "methods", "statistics", "quality", "footer"]):
            if j > start + 1:
                return start, j
    return start, len(lines)


def _extract_numbers(text: str):
    nums = []
    for m in re.finditer(r"[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?|[-+]?\d+(?:\.\d+)?", text):
        token = m.group(0)
        token = token.replace(",", "")
        try:
            if "." in token or token.startswith(("+", "-")):
                nums.append(float(token))
            else:
                nums.append(int(token))
        except Exception:
            continue
    return nums


def _contains_two_numbers_close(line: str, a: float, b: float, tol_a: float = 0.6, tol_b: float = 0.6) -> bool:
    nums = _extract_numbers(line)
    found_a = any(abs((float(n)) - a) <= tol_a for n in nums)
    found_b = any(abs((float(n)) - b) <= tol_b for n in nums)
    return found_a and found_b


def _line_contains_all_ints(line: str, ints: list) -> bool:
    tokens = _extract_numbers(line)
    token_ints = [int(n) if float(n).is_integer() else None for n in tokens]
    needed = list(ints)
    for v in needed[:]:
        if v in token_ints:
            token_ints.remove(v)
            needed.remove(v)
    return len(needed) == 0


def _approx_number_in_text(text: str, value: float, tol: float = 0.6) -> bool:
    nums = _extract_numbers(text)
    return any(abs(float(n) - value) <= tol for n in nums)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "report_file_exists": 0.0,
        "overview_bullets_correct": 0.0,
        "methods_section_present": 0.0,
        "statistics_rows_listed": 0.0,
        "statistics_totals_and_rates": 0.0,
        "qc_footer_present": 0.0,
        "pamphlet_structure_and_replacement": 0.0,
        "pamphlet_word_count": 0.0,
        "pamphlet_trends_accuracy": 0.0,
        "email_subject_and_greeting": 0.0,
        "email_body_and_attachments": 0.0,
        "email_numeric_rate_present": 0.0,
        "email_sign_off_present": 0.0,
    }

    csv_path = workspace / "input" / "worker_health_1846_1850.csv"
    pamphlet_draft_path = workspace / "input" / "pamphlet_draft.md"
    mentor_json_path = workspace / "input" / "mentor_contact.json"

    rows = _safe_load_csv_rows(csv_path)
    mentor = _safe_load_json(mentor_json_path)
    pamphlet_draft = _safe_read_text(pamphlet_draft_path)

    computed = {}
    totals_workers = 0
    totals_resp = 0
    totals_injury = 0
    if rows is not None:
        for r in rows:
            y = r["year"]
            s = r["sector"]
            w = r["workers"]
            rc = r["respiratory_cases"]
            ic = r["injury_cases"]
            rr = (rc / w) * 1000.0 if w else 0.0
            ir = (ic / w) * 1000.0 if w else 0.0
            computed[(y, s)] = {
                "workers": w,
                "respiratory_cases": rc,
                "injury_cases": ic,
                "resp_rate": rr,
                "inj_rate": ir,
            }
            totals_workers += w
            totals_resp += rc
            totals_injury += ic

    overall_resp_rate = (totals_resp / totals_workers) * 1000.0 if rows else None
    overall_injury_rate = (totals_injury / totals_workers) * 1000.0 if rows else None

    coal_resp_1846 = None
    coal_resp_1850 = None
    textiles_injury_1846 = None
    textiles_injury_1850 = None
    total_workers_1846 = None
    total_workers_1850 = None

    if rows is not None:
        totals_by_year = {}
        for r in rows:
            totals_by_year.setdefault(r["year"], 0)
            totals_by_year[r["year"]] += r["workers"]
        total_workers_1846 = totals_by_year.get(1846)
        total_workers_1850 = totals_by_year.get(1850)
        if (1846, "Coal Mining") in computed:
            coal_resp_1846 = computed[(1846, "Coal Mining")]["resp_rate"]
        if (1850, "Coal Mining") in computed:
            coal_resp_1850 = computed[(1850, "Coal Mining")]["resp_rate"]
        if (1846, "Textiles") in computed:
            textiles_injury_1846 = computed[(1846, "Textiles")]["inj_rate"]
        if (1850, "Textiles") in computed:
            textiles_injury_1850 = computed[(1850, "Textiles")]["inj_rate"]

    report_path = workspace / "outputs" / "health_trends_report.md"
    pamphlet_updated_path = workspace / "outputs" / "pamphlet_updated.md"
    email_path = workspace / "outputs" / "email_to_mentor.txt"

    report_text = _safe_read_text(report_path)
    if report_text is not None:
        scores["report_file_exists"] = 1.0

    if report_text is not None and rows is not None:
        lines = report_text.splitlines()

        start_o, end_o = _find_section_range(lines, "Overview")
        bullets_ok = False
        if start_o is not None:
            section_lines = lines[start_o:end_o]
            bullet_lines = [ln for ln in section_lines if ln.strip().startswith(("-", "*", "•"))]
            exact_three = len(bullet_lines) == 3
            coal_ok = False
            textiles_ok = False
            workforce_ok = False
            for bl in bullet_lines:
                bl_low = bl.lower()
                if "coal" in bl_low and "respir" in bl_low and "per 1,000" in bl and coal_resp_1846 is not None and coal_resp_1850 is not None:
                    if _contains_two_numbers_close(bl, coal_resp_1846, coal_resp_1850, 0.6, 0.6):
                        coal_ok = True
                if "textiles" in bl_low and "injur" in bl_low and "per 1,000" in bl and textiles_injury_1846 is not None and textiles_injury_1850 is not None:
                    if _contains_two_numbers_close(bl, textiles_injury_1846, textiles_injury_1850, 1.0, 1.0):
                        textiles_ok = True
                if "workforce" in bl_low and total_workers_1846 is not None and total_workers_1850 is not None:
                    if _contains_two_numbers_close(bl, float(total_workers_1846), float(total_workers_1850), 0.5, 0.5):
                        workforce_ok = True
            bullets_ok = exact_three and coal_ok and textiles_ok and workforce_ok
        scores["overview_bullets_correct"] = 1.0 if bullets_ok else 0.0

        start_m, end_m = _find_section_range(lines, "Methods")
        methods_ok = False
        if start_m is not None:
            methods_text = "\n".join(lines[start_m:end_m])
            has_path = "input/worker_health_1846_1850.csv" in methods_text
            mentions_calc = ("per 1,000" in methods_text) or ("per 1000" in methods_text)
            mentions_round = "round" in methods_text.lower()
            methods_ok = has_path and mentions_calc and mentions_round
        scores["methods_section_present"] = 1.0 if methods_ok else 0.0

        start_s, end_s = _find_section_range(lines, "Statistics")
        rows_listed_fraction = 0.0
        totals_and_rates_ok = False
        if start_s is not None and rows is not None:
            stats_lines = lines[start_s:end_s]
            found_count = 0
            for r in rows:
                year = r["year"]
                sector = r["sector"]
                workers = r["workers"]
                respiratory_cases = r["respiratory_cases"]
                injury_cases = r["injury_cases"]
                match_found = False
                for sl in stats_lines:
                    if str(year) in sl and sector.lower() in sl.lower():
                        if _line_contains_all_ints(sl, [workers, respiratory_cases, injury_cases]):
                            match_found = True
                            break
                if match_found:
                    found_count += 1
            rows_listed_fraction = found_count / len(rows) if rows else 0.0

            totals_present = any(_line_contains_all_ints(sl, [totals_workers, totals_resp, totals_injury]) for sl in stats_lines) if rows else False
            resp_rate_present = _approx_number_in_text("\n".join(stats_lines), overall_resp_rate, 0.6) if overall_resp_rate is not None else False
            inj_rate_present = _approx_number_in_text("\n".join(stats_lines), overall_injury_rate, 0.6) if overall_injury_rate is not None else False
            totals_and_rates_ok = bool(totals_present and resp_rate_present and inj_rate_present)

        scores["statistics_rows_listed"] = rows_listed_fraction
        scores["statistics_totals_and_rates"] = 1.0 if totals_and_rates_ok else 0.0

        qc_ok = False
        if rows is not None:
            idx_rows_processed = None
            for i, ln in enumerate(lines):
                if "Rows processed" in ln:
                    if re.search(r"Rows processed:\s*15\b", ln):
                        idx_rows_processed = i
                        break
            if idx_rows_processed is not None:
                tail = "\n".join(lines[idx_rows_processed: idx_rows_processed + 40])
                has_totals_tail = (str(totals_workers) in tail and str(totals_resp) in tail and str(totals_injury) in tail)
                qc_ok = has_totals_tail
        scores["qc_footer_present"] = 1.0 if qc_ok else 0.0

    pamphlet_updated_text = _safe_read_text(pamphlet_updated_path)
    if pamphlet_draft is not None and pamphlet_updated_text is not None:
        token = "[TO_FILL_HEALTH_TRENDS]"
        if token in pamphlet_draft:
            before, after = pamphlet_draft.split(token, 1)
            struct_ok = pamphlet_updated_text.startswith(before) and pamphlet_updated_text.endswith(after) and token not in pamphlet_updated_text
            scores["pamphlet_structure_and_replacement"] = 1.0 if struct_ok else 0.0

            if struct_ok:
                replaced = pamphlet_updated_text[len(before): len(pamphlet_updated_text) - len(after)]
                words = re.findall(r"\b\w+\b", replaced)
                wc = len(words)
                scores["pamphlet_word_count"] = 1.0 if 100 <= wc <= 150 else 0.0

                trends_ok = False
                if rows is not None:
                    coal_ok = ("coal" in replaced.lower() and "respir" in replaced.lower() and "per 1,000" in replaced
                               and _contains_two_numbers_close(replaced, coal_resp_1846, coal_resp_1850, 0.6, 0.6))
                    textiles_ok = ("textiles" in replaced.lower() and "injur" in replaced.lower() and "per 1,000" in replaced
                                   and _contains_two_numbers_close(replaced, textiles_injury_1846, textiles_injury_1850, 1.0, 1.0))
                    workforce_ok = ("workforce" in replaced.lower()
                                    and _contains_two_numbers_close(replaced, float(total_workers_1846), float(total_workers_1850), 0.5, 0.5))
                    trends_ok = coal_ok and textiles_ok and workforce_ok
                scores["pamphlet_trends_accuracy"] = 1.0 if trends_ok else 0.0
        else:
            scores["pamphlet_structure_and_replacement"] = 0.0
            scores["pamphlet_word_count"] = 0.0
            scores["pamphlet_trends_accuracy"] = 0.0

    email_text = _safe_read_text(email_path)
    if email_text is not None:
        lines = [ln.rstrip("\n") for ln in email_text.splitlines()]
        expected_subject = "Subject: Industrial Health Trends Report (1846–1850) — Request for Feedback"
        subj_ok = len(lines) > 0 and lines[0].strip() == expected_subject
        greet_ok = False
        if mentor is not None:
            pref = mentor.get("preferred_salutation")
            name = mentor.get("name")
            if isinstance(pref, str) and isinstance(name, str):
                expected_greet = f"{pref} {name},"
                greet_ok = any(ln.strip() == expected_greet for ln in lines)
        scores["email_subject_and_greeting"] = 1.0 if (subj_ok and greet_ok) else 0.0

        body_ok = False
        if greet_ok:
            greet_line_idx = None
            expected_greet = f"{mentor['preferred_salutation']} {mentor['name']}," if mentor else None
            if expected_greet:
                for i, ln in enumerate(lines):
                    if ln.strip() == expected_greet:
                        greet_line_idx = i
                        break
            if greet_line_idx is not None:
                after = lines[greet_line_idx + 1:]
                paragraphs = []
                current = []
                for ln in after:
                    if ln.strip() == "":
                        if current:
                            paragraphs.append("\n".join(current))
                            current = []
                    else:
                        current.append(ln)
                if current:
                    paragraphs.append("\n".join(current))

                def _is_signoff(p):
                    low = p.lower().strip()
                    return any(low.startswith(x) for x in ["sincerely", "regards", "yours", "kind regards", "best"]) and len(p.splitlines()) <= 2

                content_paras = [p for p in paragraphs if not _is_signoff(p)]
                para_count_ok = 1 <= len(content_paras) <= 2
                attach_ok = ("outputs/health_trends_report.md" in email_text and
                             "outputs/pamphlet_updated.md" in email_text)
                body_ok = para_count_ok and attach_ok
        scores["email_body_and_attachments"] = 1.0 if body_ok else 0.0

        rate_ok = False
        if rows is not None:
            target_rates = []
            if coal_resp_1846 is not None:
                target_rates.append(coal_resp_1846)
            if coal_resp_1850 is not None:
                target_rates.append(coal_resp_1850)
            if textiles_injury_1846 is not None:
                target_rates.append(textiles_injury_1846)
            if textiles_injury_1850 is not None:
                target_rates.append(textiles_injury_1850)
            if overall_resp_rate is not None:
                target_rates.append(overall_resp_rate)
            if overall_injury_rate is not None:
                target_rates.append(overall_injury_rate)
            for ln in lines:
                if "per 1,000" in ln:
                    for t in target_rates:
                        if _approx_number_in_text(ln, t, 1.0):
                            rate_ok = True
                            break
                if rate_ok:
                    break
        scores["email_numeric_rate_present"] = 1.0 if rate_ok else 0.0

        signoff_ok = any(ln.strip().lower().startswith(("sincerely", "regards", "yours", "kind regards", "best")) for ln in lines[-5:])
        scores["email_sign_off_present"] = 1.0 if signoff_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()