import json
import csv
import re
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def normalize_text(s: str) -> str:
    if s is None:
        return ""
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.rstrip() for ln in s.split("\n")]
    return "\n".join(lines).strip("\n")


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_read_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for r in reader:
                rows.append(dict(r))
        return rows
    except Exception:
        return None


def parse_int(s: str) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        return None


def compute_expected_aggregates(input_rows: List[Dict[str, str]]) -> Dict[Tuple[str, str, str, str], Dict[str, str]]:
    typed = []
    for r in input_rows:
        year = parse_int(r.get("year", ""))
        county = r.get("county", "")
        disease = r.get("disease", "")
        deaths = parse_int(r.get("deaths", ""))
        population = parse_int(r.get("population", ""))
        if year is None or deaths is None or population is None or not county or not disease:
            return {}
        typed.append({"year": year, "county": county, "disease": disease, "deaths": deaths, "population": population})

    def sum_for(disease: str, years_set: set, counties: Optional[set] = None) -> Tuple[int, int]:
        total_deaths = 0
        total_pop = 0
        for r in typed:
            if r["disease"] != disease:
                continue
            if r["year"] not in years_set:
                continue
            if counties is not None and r["county"] not in counties:
                continue
            total_deaths += r["deaths"]
            total_pop += r["population"]
        return total_deaths, total_pop

    y_1918_1920 = {1918, 1919, 1920}
    y_1919_1920 = {1919, 1920}
    y_1918 = {1918}

    all_counties = set(r["county"] for r in typed)

    expected: Dict[Tuple[str, str, str, str], Dict[str, str]] = {}

    d, p = sum_for("influenza", y_1918_1920, {"Lublin"})
    rate = (d / p * 10000.0) if p > 0 else 0.0
    expected[("influenza", "county", "Lublin", "1918-1920")] = {
        "deaths": str(d),
        "population": str(p),
        "rate_per_10k": f"{rate:.2f}",
    }

    d, p = sum_for("cholera", y_1919_1920, {"Lublin"})
    rate = (d / p * 10000.0) if p > 0 else 0.0
    expected[("cholera", "county", "Lublin", "1919-1920")] = {
        "deaths": str(d),
        "population": str(p),
        "rate_per_10k": f"{rate:.2f}",
    }

    d, p = sum_for("typhus", y_1918_1920, all_counties)
    rate = (d / p * 10000.0) if p > 0 else 0.0
    expected[("typhus", "voivodeship", "Lublin Voivodeship", "1918-1920")] = {
        "deaths": str(d),
        "population": str(p),
        "rate_per_10k": f"{rate:.2f}",
    }

    d, p = sum_for("influenza", y_1918, {"Zamosc"})
    rate = (d / p * 10000.0) if p > 0 else 0.0
    expected[("influenza", "county", "Zamosc", "1918")] = {
        "deaths": str(d),
        "population": str(p),
        "rate_per_10k": f"{rate:.2f}",
    }

    d, p = sum_for("influenza", y_1918, {"Chelm"})
    rate = (d / p * 10000.0) if p > 0 else 0.0
    expected[("influenza", "county", "Chelm", "1918")] = {
        "deaths": str(d),
        "population": str(p),
        "rate_per_10k": f"{rate:.2f}",
    }

    return expected


def split_findings_section(text: str) -> Optional[Tuple[str, str, str, str]]:
    norm = normalize_text(text)
    lines = norm.split("\n")
    idx = None
    for i, ln in enumerate(lines):
        if ln.strip() == "## Findings":
            idx = i
            break
    if idx is None:
        return None
    next_idx = None
    for j in range(idx + 1, len(lines)):
        if lines[j].startswith("## "):
            next_idx = j
            break
    prefix = "\n".join(lines[:idx])
    findings_header = lines[idx]
    findings_body = "\n".join(lines[idx + 1: next_idx]) if next_idx is not None else "\n".join(lines[idx + 1:])
    suffix = "\n".join(lines[next_idx:]) if next_idx is not None else ""
    return prefix, findings_header, findings_body, suffix


def contains_all(text: str, keywords: List[str]) -> bool:
    t = text.lower()
    return all(k.lower() in t for k in keywords)


def has_number(text: str, number: int) -> bool:
    pattern = r"\b{}\b".format(re.escape(str(number)))
    return re.search(pattern, text) is not None


def word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "analysis_summary_structure": 0.0,
        "analysis_summary_values": 0.0,
        "analysis_summary_rate_format": 0.0,
        "revised_pamphlet_structure": 0.0,
        "revised_pamphlet_findings_reference": 0.0,
        "revised_pamphlet_numeric_consistency": 0.0,
        "status_update_structure_and_length": 0.0,
        "status_update_numeric_consistency": 0.0,
        "email_basic_requirements": 0.0,
    }

    input_csv_path = workspace / "input" / "morbidity_lublin_1918_1920.csv"
    input_rows = safe_read_csv(input_csv_path)

    expected_agg: Dict[Tuple[str, str, str, str], Dict[str, str]] = {}
    if input_rows is not None:
        expected_agg = compute_expected_aggregates(input_rows)

    analysis_path = workspace / "output" / "analysis_summary.csv"
    analysis_rows = safe_read_csv(analysis_path)
    expected_header = ["disease", "area_type", "area_name", "years", "deaths", "population", "rate_per_10k"]

    if analysis_rows is not None and input_rows is not None and expected_agg:
        try:
            with analysis_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, [])
        except Exception:
            header = []
        header_ok = header == expected_header

        keys_expected = set(expected_agg.keys())
        keys_actual = set()
        values_ok = True
        rate_format_ok = True
        rows_count_ok = len(analysis_rows) == 5

        for r in analysis_rows:
            key = (r.get("disease", ""), r.get("area_type", ""), r.get("area_name", ""), r.get("years", ""))
            keys_actual.add(key)
            exp = expected_agg.get(key)
            if exp is None:
                values_ok = False
                continue
            d_str = r.get("deaths", "")
            p_str = r.get("population", "")
            rate_str = r.get("rate_per_10k", "")
            d_val = parse_int(d_str)
            p_val = parse_int(p_str)
            if d_val is None or p_val is None:
                values_ok = False
            else:
                if str(d_val) != exp["deaths"] or str(p_val) != exp["population"]:
                    values_ok = False
            try:
                if rate_str != exp["rate_per_10k"]:
                    values_ok = False
                if not re.match(r"^-?\d+\.\d{2}$", rate_str):
                    rate_format_ok = False
            except Exception:
                values_ok = False
                rate_format_ok = False

        rows_keys_ok = (keys_actual == keys_expected)
        if header_ok and rows_count_ok and rows_keys_ok:
            scores["analysis_summary_structure"] = 1.0
        else:
            scores["analysis_summary_structure"] = 0.0
        if values_ok and rows_count_ok and rows_keys_ok:
            scores["analysis_summary_values"] = 1.0
        else:
            scores["analysis_summary_values"] = 0.0
        if rate_format_ok and rows_count_ok and rows_keys_ok:
            scores["analysis_summary_rate_format"] = 1.0
        else:
            scores["analysis_summary_rate_format"] = 0.0
    else:
        scores["analysis_summary_structure"] = 0.0
        scores["analysis_summary_values"] = 0.0
        scores["analysis_summary_rate_format"] = 0.0

    orig_pamphlet_path = workspace / "input" / "pamphlet_draft.md"
    revised_pamphlet_path = workspace / "output" / "revised_pamphlet.md"
    orig_text = safe_read_text(orig_pamphlet_path)
    revised_text = safe_read_text(revised_pamphlet_path)

    if orig_text is not None and revised_text is not None and expected_agg:
        orig_split = split_findings_section(orig_text)
        rev_split = split_findings_section(revised_text)
        if orig_split is not None and rev_split is not None:
            orig_prefix, orig_header, orig_findings_body, orig_suffix = orig_split
            rev_prefix, rev_header, rev_findings_body, rev_suffix = rev_split
            if normalize_text(orig_prefix) == normalize_text(rev_prefix) and normalize_text(orig_suffix) == normalize_text(rev_suffix) and normalize_text(orig_header) == normalize_text(rev_header):
                if normalize_text(orig_findings_body) != normalize_text(rev_findings_body):
                    scores["revised_pamphlet_structure"] = 1.0
            findings_lower = normalize_text(rev_findings_body).lower()
            if "see output/analysis_summary.csv" in findings_lower:
                scores["revised_pamphlet_findings_reference"] = 1.0

            exp_li = expected_agg.get(("influenza", "county", "Lublin", "1918-1920"))
            exp_ch = expected_agg.get(("cholera", "county", "Lublin", "1919-1920"))
            exp_ty = expected_agg.get(("typhus", "voivodeship", "Lublin Voivodeship", "1918-1920"))
            exp_z1918 = expected_agg.get(("influenza", "county", "Zamosc", "1918"))
            exp_c1918 = expected_agg.get(("influenza", "county", "Chelm", "1918"))

            findings_ok = True
            if not (exp_li and exp_ch and exp_ty and exp_z1918 and exp_c1918):
                findings_ok = False
            else:
                cond1 = contains_all(rev_findings_body, ["Lublin", "influenza", "1918-1920"]) and has_number(rev_findings_body, int(exp_li["deaths"]))
                cond2 = contains_all(rev_findings_body, ["Lublin", "cholera", "1919-1920"]) and has_number(rev_findings_body, int(exp_ch["deaths"]))
                cond3 = contains_all(rev_findings_body, ["Lublin Voivodeship", "typhus", "1918-1920"]) and has_number(rev_findings_body, int(exp_ty["deaths"]))
                cond4 = contains_all(rev_findings_body, ["Zamosc", "Chelm", "influenza", "1918"]) and has_number(rev_findings_body, int(exp_z1918["deaths"])) and has_number(rev_findings_body, int(exp_c1918["deaths"]))
                findings_ok = cond1 and cond2 and cond3 and cond4

            if findings_ok:
                scores["revised_pamphlet_numeric_consistency"] = 1.0
        else:
            scores["revised_pamphlet_structure"] = 0.0
            scores["revised_pamphlet_findings_reference"] = 0.0
            scores["revised_pamphlet_numeric_consistency"] = 0.0
    else:
        scores["revised_pamphlet_structure"] = 0.0
        scores["revised_pamphlet_findings_reference"] = 0.0
        scores["revised_pamphlet_numeric_consistency"] = 0.0

    status_path = workspace / "output" / "status_update.md"
    status_text = safe_read_text(status_path)
    if status_text is not None and expected_agg:
        wc = word_count(status_text)
        lines_with_arrow = [ln for ln in normalize_text(status_text).split("\n") if "->" in ln]
        has_csv_reference = ("input/morbidity_lublin_1918_1920.csv" in status_text) or ("csv" in status_text.lower())
        structure_ok = (wc <= 300 and len(lines_with_arrow) >= 4 and has_csv_reference)
        if structure_ok:
            scores["status_update_structure_and_length"] = 1.0

        exp_li = expected_agg.get(("influenza", "county", "Lublin", "1918-1920"))
        exp_ch = expected_agg.get(("cholera", "county", "Lublin", "1919-1920"))
        exp_ty = expected_agg.get(("typhus", "voivodeship", "Lublin Voivodeship", "1918-1920"))
        exp_z1918 = expected_agg.get(("influenza", "county", "Zamosc", "1918"))
        exp_c1918 = expected_agg.get(("influenza", "county", "Chelm", "1918"))

        num_ok = all([exp_li, exp_ch, exp_ty, exp_z1918, exp_c1918])
        if num_ok:
            num_ok = num_ok and contains_all(status_text, ["Lublin", "influenza", "1918-1920"]) and has_number(status_text, int(exp_li["deaths"]))
            num_ok = num_ok and contains_all(status_text, ["Lublin", "cholera", "1919-1920"]) and has_number(status_text, int(exp_ch["deaths"]))
            num_ok = num_ok and contains_all(status_text, ["Lublin Voivodeship", "typhus", "1918-1920"]) and has_number(status_text, int(exp_ty["deaths"]))
            num_ok = num_ok and contains_all(status_text, ["Zamosc", "Chelm", "influenza", "1918"]) and has_number(status_text, int(exp_z1918["deaths"])) and has_number(status_text, int(exp_c1918["deaths"]))
        if num_ok:
            scores["status_update_numeric_consistency"] = 1.0
    else:
        scores["status_update_structure_and_length"] = 0.0
        scores["status_update_numeric_consistency"] = 0.0

    email_path = workspace / "output" / "email_to_archive.txt"
    email_text = safe_read_text(email_path)
    if email_text is not None:
        t = email_text
        has_to = bool(re.search(r"(?im)^To:", t))
        subj_match = re.search(r"(?im)^Subject:\s*(.*)$", t)
        has_subject = subj_match is not None
        subject_ok = False
        if has_subject:
            subject_val = subj_match.group(1).strip().lower()
            subject_ok = "revisions to 1918-1920 health exhibit text" in subject_val
        lists_files = all(s in t for s in ["output/analysis_summary.csv", "output/revised_pamphlet.md", "output/status_update.md"])
        asks_review = "review" in t.lower()
        if has_to and subject_ok and lists_files and asks_review:
            scores["email_basic_requirements"] = 1.0
        else:
            scores["email_basic_requirements"] = 0.0
    else:
        scores["email_basic_requirements"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()