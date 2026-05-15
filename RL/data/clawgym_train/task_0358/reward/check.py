import json
import csv
import re
import sys
from pathlib import Path
from html.parser import HTMLParser
from typing import Dict, List, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _count_csv_data_rows(path: Path) -> Optional[int]:
    try:
        with path.open("r", encoding="utf-8") as f:
            lines = [ln.rstrip("\n") for ln in f.readlines()]
        nonempty = [ln for ln in lines if ln.strip() != ""]
        if not nonempty:
            return 0
        return max(len(nonempty) - 1, 0)
    except Exception:
        return None


class _GuidelineHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_h2 = False
        self.current_h2_text = ""
        self.last_h2_disease: Optional[str] = None
        self.in_ul = False
        self.collecting_ul_for: Optional[str] = None
        self.in_li = False
        self.li_text = ""
        self.therapies: Dict[str, List[str]] = {"ALS": [], "MG": []}

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "h2":
            self.in_h2 = True
            self.current_h2_text = ""
        elif tag == "ul":
            if self.last_h2_disease in ("ALS", "MG"):
                self.in_ul = True
                self.collecting_ul_for = self.last_h2_disease
        elif tag == "li":
            if self.in_ul and self.collecting_ul_for in ("ALS", "MG"):
                self.in_li = True
                self.li_text = ""

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "h2":
            self.in_h2 = False
            txt = self.current_h2_text.strip()
            low = txt.lower()
            if "(als" in low or "als)" in low or "(als)" in low:
                self.last_h2_disease = "ALS"
            elif "(mg" in low or "mg)" in low or "(mg)" in low:
                self.last_h2_disease = "MG"
            else:
                self.last_h2_disease = None
            self.current_h2_text = ""
        elif tag == "ul":
            self.in_ul = False
            self.collecting_ul_for = None
        elif tag == "li":
            if self.in_li and self.collecting_ul_for in ("ALS", "MG"):
                item = self.li_text.strip()
                if item:
                    self.therapies[self.collecting_ul_for].append(item)
            self.in_li = False
            self.li_text = ""

    def handle_data(self, data):
        if self.in_h2:
            self.current_h2_text += data
        if self.in_li:
            self.li_text += data


def _parse_guidelines(html_path: Path) -> Optional[Dict[str, List[str]]]:
    text = _read_text(html_path)
    if text is None:
        return None
    try:
        parser = _GuidelineHTMLParser()
        parser.feed(text)
        therapies = {k: [v.strip() for v in parser.therapies.get(k, []) if v.strip()] for k in ("ALS", "MG")}
        return therapies
    except Exception:
        return None


def _safe_float(x: str) -> Optional[float]:
    try:
        return float(x)
    except Exception:
        return None


def _safe_int(x: str) -> Optional[int]:
    try:
        return int(x)
    except Exception:
        return None


def _read_patient_rows(csv_path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with csv_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader]
        required_cols = {"patient_id", "disease", "year", "age", "sex", "resp_support", "medications", "function_score"}
        if set(reader.fieldnames or []) >= required_cols:
            return rows
        return None
    except Exception:
        return None


def _get_patient_csv_files(workspace: Path) -> List[Path]:
    patients_dir = workspace / "input" / "patients"
    if not patients_dir.exists():
        return []
    return sorted([p for p in patients_dir.glob("*.csv") if p.is_file()])


def _compute_expected_groups(workspace: Path) -> Optional[Dict[Tuple[str, int], List[Dict[str, str]]]]:
    files = _get_patient_csv_files(workspace)
    groups: Dict[Tuple[str, int], List[Dict[str, str]]] = {}
    for p in files:
        rows = _read_patient_rows(p)
        if rows is None:
            return None
        for row in rows:
            disease = (row.get("disease") or "").strip()
            year_s = (row.get("year") or "").strip()
            y = _safe_int(year_s)
            if not disease or y is None:
                return None
            key = (disease, y)
            groups.setdefault(key, []).append(row)
    return groups


def _normalize_med_list(med_str: str) -> List[str]:
    if med_str is None:
        return []
    parts = [m.strip() for m in med_str.split(";")]
    parts = [p for p in parts if p != "" and p.lower() != "none"]
    return parts


def _compute_expected_aggregates(workspace: Path) -> Optional[Dict[Tuple[str, int], Dict[str, float]]]:
    groups = _compute_expected_groups(workspace)
    if groups is None:
        return None
    guidelines_path = workspace / "input" / "guidelines" / "neuromuscular_guidelines.html"
    therapies = _parse_guidelines(guidelines_path)
    if therapies is None:
        return None
    therapy_sets: Dict[str, set] = {}
    for disease, items in therapies.items():
        therapy_sets[disease] = set([i.casefold() for i in items])

    out: Dict[Tuple[str, int], Dict[str, float]] = {}
    for (disease, year), rows in groups.items():
        n = len(rows)
        if n == 0:
            continue
        ages: List[float] = []
        func_scores: List[float] = []
        n_female = 0
        n_resp = 0
        n_guideline = 0
        for row in rows:
            age = _safe_float((row.get("age") or "").strip())
            fs = _safe_float((row.get("function_score") or "").strip())
            sex = (row.get("sex") or "").strip()
            resp = (row.get("resp_support") or "").strip()
            meds = (row.get("medications") or "").strip()
            if age is None or fs is None:
                return None
            ages.append(age)
            func_scores.append(fs)
            if sex.upper() == "F":
                n_female += 1
            if resp.lower() != "none" and resp != "":
                n_resp += 1
            meds_list = _normalize_med_list(meds)
            disease_therapies = therapy_sets.get(disease, set())
            on_guideline = any((m.casefold() in disease_therapies) for m in meds_list)
            if on_guideline:
                n_guideline += 1
        mean_age = sum(ages) / n
        mean_fs = sum(func_scores) / n
        pct_female = n_female / n
        pct_resp = n_resp / n
        pct_guideline = n_guideline / n
        out[(disease, year)] = {
            "n_patients": float(n),
            "mean_age": mean_age,
            "pct_female": pct_female,
            "pct_on_respiratory_support": pct_resp,
            "pct_on_guideline_therapy": pct_guideline,
            "mean_function_score": mean_fs,
        }
    return out


def _parse_aggregates_csv(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None
            rows = [row for row in reader]
        return (headers, rows)
    except Exception:
        return None


def _almost_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _find_bullet_lines(md_text: str) -> List[str]:
    lines = md_text.splitlines()
    bullets = []
    for ln in lines:
        if re.match(r"^\s*[-*]\s+", ln):
            bullets.append(ln.strip())
    return bullets


def _line_contains_file_and_count(line: str, filename: str, count: int) -> bool:
    base = Path(filename).name
    if base not in line and filename not in line:
        return False
    pattern = r"(?<!\d){}(?!\d)".format(re.escape(str(count)))
    if re.search(pattern, line) is None:
        return False
    return True


def _md_contains_therapies(md_text: str, therapies: Dict[str, List[str]]) -> bool:
    text_low = md_text.lower()
    if ("als" not in text_low) or ("mg" not in text_low):
        return False
    for disease, items in therapies.items():
        for item in items:
            pat = r"\b{}\b".format(re.escape(item))
            if re.search(pat, md_text, flags=re.IGNORECASE) is None:
                return False
    return True


def _prepare_numeric_strings(value: float) -> List[str]:
    variants = set()
    for fmt in ["{:.0f}", "{:.1f}", "{:.2f}"]:
        variants.add(fmt.format(value))
    as_str = "{:.6f}".format(value).rstrip("0").rstrip(".")
    variants.add(as_str)
    perc = value * 100.0
    for fmt in ["{:.0f}%", "{:.1f}%", "{:.2f}%"]:
        variants.add(fmt.format(perc))
    return list(variants)


def _md_summary_references_numbers(md_text: str, aggregates: Dict[Tuple[str, int], Dict[str, float]]) -> bool:
    text_low = md_text.lower()
    if "als" not in text_low or "mg" not in text_low:
        return False
    candidates = set()
    for (_d, _y), metrics in aggregates.items():
        candidates.update(_prepare_numeric_strings(metrics["n_patients"]))
        candidates.update(_prepare_numeric_strings(metrics["mean_age"]))
        candidates.update(_prepare_numeric_strings(metrics["pct_female"]))
        candidates.update(_prepare_numeric_strings(metrics["pct_on_respiratory_support"]))
        candidates.update(_prepare_numeric_strings(metrics["pct_on_guideline_therapy"]))
        candidates.update(_prepare_numeric_strings(metrics["mean_function_score"]))
    found = 0
    for s in candidates:
        if s in md_text:
            found += 1
            if found >= 2:
                return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "aggregates_csv_exists": 0.0,
        "aggregates_csv_columns_and_order_correct": 0.0,
        "aggregates_groups_complete": 0.0,
        "aggregates_metrics_correct": 0.0,
        "briefing_md_exists": 0.0,
        "md_lists_processed_files_with_row_counts": 0.0,
        "md_lists_guideline_therapies": 0.0,
        "md_includes_summary_referencing_aggregates": 0.0,
    }

    patient_files = _get_patient_csv_files(workspace)
    expected_counts: Dict[str, Optional[int]] = {}
    for p in patient_files:
        cnt = _count_csv_data_rows(p)
        expected_counts[str(p)] = cnt

    guidelines_path = workspace / "input" / "guidelines" / "neuromuscular_guidelines.html"
    therapies = _parse_guidelines(guidelines_path)

    expected_groups = _compute_expected_groups(workspace)
    expected_aggs = _compute_expected_aggregates(workspace)

    out_agg_path = workspace / "output" / "aggregates.csv"
    if out_agg_path.exists() and out_agg_path.is_file():
        scores["aggregates_csv_exists"] = 1.0
        parsed = _parse_aggregates_csv(out_agg_path)
        if parsed is not None:
            headers, rows = parsed
            required_headers = [
                "disease",
                "year",
                "n_patients",
                "mean_age",
                "pct_female",
                "pct_on_respiratory_support",
                "pct_on_guideline_therapy",
                "mean_function_score",
            ]
            if headers == required_headers:
                scores["aggregates_csv_columns_and_order_correct"] = 1.0
            if expected_groups is not None:
                groups_out = set()
                ok_parse_rows = True
                for r in rows:
                    d = (r.get("disease") or "").strip()
                    ys = (r.get("year") or "").strip()
                    y = _safe_int(ys)
                    if not d or y is None:
                        ok_parse_rows = False
                        break
                    groups_out.add((d, y))
                if ok_parse_rows and groups_out == set(expected_groups.keys()):
                    scores["aggregates_groups_complete"] = 1.0
            if expected_aggs is not None:
                ok_vals = True
                csv_map: Dict[Tuple[str, int], Dict[str, float]] = {}
                for r in rows:
                    d = (r.get("disease") or "").strip()
                    y = _safe_int((r.get("year") or "").strip())
                    if not d or y is None:
                        ok_vals = False
                        break
                    key = (d, y)
                    try:
                        n_pat_val = _safe_float(r.get("n_patients", ""))
                        mean_age_val = _safe_float(r.get("mean_age", ""))
                        pct_female_val = _safe_float(r.get("pct_female", ""))
                        pct_resp_val = _safe_float(r.get("pct_on_respiratory_support", ""))
                        pct_guideline_val = _safe_float(r.get("pct_on_guideline_therapy", ""))
                        mean_fs_val = _safe_float(r.get("mean_function_score", ""))
                        if None in (n_pat_val, mean_age_val, pct_female_val, pct_resp_val, pct_guideline_val, mean_fs_val):
                            ok_vals = False
                            break
                        csv_map[key] = {
                            "n_patients": float(n_pat_val),
                            "mean_age": float(mean_age_val),
                            "pct_female": float(pct_female_val),
                            "pct_on_respiratory_support": float(pct_resp_val),
                            "pct_on_guideline_therapy": float(pct_guideline_val),
                            "mean_function_score": float(mean_fs_val),
                        }
                    except Exception:
                        ok_vals = False
                        break
                if ok_vals and set(csv_map.keys()) == set(expected_aggs.keys()):
                    for key, exp in expected_aggs.items():
                        got = csv_map.get(key)
                        if got is None:
                            ok_vals = False
                            break
                        for metric in [
                            "n_patients",
                            "mean_age",
                            "pct_female",
                            "pct_on_respiratory_support",
                            "pct_on_guideline_therapy",
                            "mean_function_score",
                        ]:
                            gv = got.get(metric)
                            ev = exp.get(metric)
                            if gv is None or ev is None or not _almost_equal(float(gv), float(ev), tol=1e-6):
                                ok_vals = False
                                break
                        if not ok_vals:
                            break
                if ok_vals:
                    scores["aggregates_metrics_correct"] = 1.0

    md_path = workspace / "output" / "clinic_briefing.md"
    md_text = _read_text(md_path) if md_path.exists() and md_path.is_file() else None
    if md_text is not None:
        scores["briefing_md_exists"] = 1.0

        bullets = _find_bullet_lines(md_text)
        processed_ok = True
        for fpath, cnt in expected_counts.items():
            base = Path(fpath).name
            if cnt is None:
                processed_ok = False
                break
            found_line = False
            for bl in bullets:
                if _line_contains_file_and_count(bl, base, cnt) or _line_contains_file_and_count(bl, fpath, cnt):
                    found_line = True
                    break
            if not found_line:
                processed_ok = False
                break
        if len(expected_counts) == 0:
            processed_ok = True
        scores["md_lists_processed_files_with_row_counts"] = 1.0 if processed_ok else 0.0

        therapies_ok = False
        if therapies is not None:
            therapies_ok = _md_contains_therapies(md_text, therapies)
        scores["md_lists_guideline_therapies"] = 1.0 if therapies_ok else 0.0

        summary_ok = False
        if expected_aggs is not None:
            summary_ok = _md_summary_references_numbers(md_text, expected_aggs)
        scores["md_includes_summary_referencing_aggregates"] = 1.0 if summary_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()