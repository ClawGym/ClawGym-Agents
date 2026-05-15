import sys
import json
import csv
import re
from pathlib import Path
from html.parser import HTMLParser
from collections import Counter
from typing import List, Tuple, Optional, Dict, Any


def _safe_read_text(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        return path.read_text(encoding="utf-8"), None
    except Exception as e:
        return None, str(e)


def _safe_load_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)


def _safe_read_csv_dicts(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None, None, "Missing header"
            header = list(reader.fieldnames)
            rows = [dict(row) for row in reader]
            return header, rows, None
    except Exception as e:
        return None, None, str(e)


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


class _RainyTipsParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_h2 = False
        self.current_h2_text_parts: List[str] = []
        self.target_section_found = False
        self.in_target_ul = False
        self.capture_li = False
        self.current_li_parts: List[str] = []
        self.tips: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "h2":
            self.in_h2 = True
            self.current_h2_text_parts = []
        if self.target_section_found and tag.lower() == "ul" and not self.in_target_ul and not self.tips:
            # The first UL after the target H2
            self.in_target_ul = True
        if self.in_target_ul and tag.lower() == "li":
            self.capture_li = True
            self.current_li_parts = []

    def handle_endtag(self, tag):
        if tag.lower() == "h2":
            self.in_h2 = False
            h2_text = "".join(self.current_h2_text_parts).strip()
            if h2_text == "Rainy Season Preparedness":
                self.target_section_found = True
        if tag.lower() == "ul" and self.in_target_ul:
            self.in_target_ul = False
        if tag.lower() == "li" and self.capture_li:
            self.capture_li = False
            li_text = "".join(self.current_li_parts).strip()
            if li_text:
                self.tips.append(li_text)

    def handle_data(self, data):
        if self.in_h2:
            self.current_h2_text_parts.append(data)
        if self.capture_li:
            self.current_li_parts.append(data)


def _parse_rainy_tips_from_html(path: Path) -> Tuple[Optional[List[str]], Optional[str]]:
    text, err = _safe_read_text(path)
    if err is not None or text is None:
        return None, err or "Failed to read HTML"
    parser = _RainyTipsParser()
    try:
        parser.feed(text)
    except Exception as e:
        return None, str(e)
    if not parser.tips:
        return None, "No tips found in HTML under the specified section"
    return parser.tips[:3], None


def _compute_incident_counts(incidents_csv: Path) -> Tuple[Optional[Dict[str, int]], Optional[str]]:
    header, rows, err = _safe_read_csv_dicts(incidents_csv)
    if err is not None or header is None or rows is None:
        return None, err or "Failed to read incidents CSV"
    if "incident_type" not in header:
        return None, "incidents.csv missing 'incident_type' column"
    counts: Dict[str, int] = {}
    for r in rows:
        itype = r.get("incident_type")
        if itype is None:
            return None, "Row missing incident_type"
        counts[itype] = counts.get(itype, 0) + 1
    return counts, None


def _compute_affected_wards(incidents_csv: Path) -> Tuple[Optional[set], Optional[str]]:
    header, rows, err = _safe_read_csv_dicts(incidents_csv)
    if err is not None or header is None or rows is None:
        return None, err or "Failed to read incidents CSV"
    if "ward" not in header:
        return None, "incidents.csv missing 'ward' column"
    wards = set()
    for r in rows:
        w = r.get("ward")
        if w is None:
            return None, "Row missing ward"
        wards.add(w)
    return wards, None


def _load_expected_clinics(clinics_json: Path, affected_wards: set) -> Tuple[Optional[List[Tuple[str, str, str]]], Optional[str]]:
    data, err = _safe_load_json(clinics_json)
    if err is not None or data is None:
        return None, err or "Failed to read clinics.json"
    if not isinstance(data, list):
        return None, "clinics.json is not a list"
    triples: List[Tuple[str, str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            return None, "clinics.json contains non-object items"
        ward = item.get("ward")
        name = item.get("name")
        phone = item.get("phone")
        if ward is None or name is None or phone is None:
            return None, "clinic entry missing ward/name/phone"
        if ward in affected_wards:
            triples.append((ward, name, phone))
    return triples, None


def _read_incident_summary_output(path: Path) -> Tuple[Optional[List[Tuple[str, int]]], Optional[str], Optional[List[str]]]:
    header, rows, err = _safe_read_csv_dicts(path)
    if err is not None or header is None or rows is None:
        return None, err or "Failed to read incident_summary.csv", None
    if header != ["incident_type", "count"]:
        return None, "Incorrect header", header
    parsed: List[Tuple[str, int]] = []
    for r in rows:
        itype = r.get("incident_type")
        count_str = r.get("count")
        if itype is None or count_str is None:
            return None, "Missing fields in row", header
        try:
            c = int(count_str)
        except Exception:
            return None, "Non-integer count value", header
        parsed.append((itype, c))
    return parsed, None, header


def _read_clinics_output(path: Path) -> Tuple[Optional[List[Tuple[str, str, str]]], Optional[str], Optional[List[str]]]:
    header, rows, err = _safe_read_csv_dicts(path)
    if err is not None or header is None or rows is None:
        return None, err or "Failed to read clinics_in_affected_wards.csv", None
    if header != ["ward", "clinic_name", "phone"]:
        return None, "Incorrect header", header
    triples: List[Tuple[str, str, str]] = []
    for r in rows:
        ward = r.get("ward")
        clinic_name = r.get("clinic_name")
        phone = r.get("phone")
        if ward is None or clinic_name is None or phone is None:
            return None, "Missing fields in row", header
        triples.append((ward, clinic_name, phone))
    return triples, None, header


def _get_section_lines(doc_text: str, title: str, other_titles: List[str]) -> List[str]:
    lines = doc_text.splitlines()
    title_idx = -1
    t_low = title.strip().lower()
    for i, line in enumerate(lines):
        if t_low in line.strip().lower():
            title_idx = i
            break
    if title_idx == -1:
        return []
    end_idx = len(lines)
    if other_titles:
        lowers = [ot.strip().lower() for ot in other_titles]
        for j in range(title_idx + 1, len(lines)):
            line_l = lines[j].strip().lower()
            if any(ot in line_l for ot in lowers):
                end_idx = j
                break
    return lines[title_idx + 1:end_idx]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "incident_summary_schema": 0.0,
        "incident_summary_counts_correct": 0.0,
        "incident_summary_sorted_descending": 0.0,
        "incident_summary_unique_types": 0.0,
        "clinics_schema": 0.0,
        "clinics_correct_filtered_set": 0.0,
        "clinics_sorted_by_ward": 0.0,
        "rainy_tips_schema": 0.0,
        "rainy_tips_content_correct": 0.0,
        "bulletin_exists_length": 0.0,
        "bulletin_key_stats_top3_correct": 0.0,
        "bulletin_where_to_seek_help_wards_listed": 0.0,
        "bulletin_where_to_seek_help_clinics_listed": 0.0,
        "bulletin_seasonal_tips_exact": 0.0,
        "script_exists": 0.0,
    }

    input_incidents = workspace / "input" / "incidents.csv"
    input_clinics = workspace / "input" / "clinics.json"
    input_health_html = workspace / "input" / "health_tips.html"

    out_incident_summary = workspace / "output" / "incident_summary.csv"
    out_clinics = workspace / "output" / "clinics_in_affected_wards.csv"
    out_rainy_tips = workspace / "output" / "rainy_tips.json"
    out_bulletin = workspace / "output" / "bulletin.md"

    # Check script exists
    script_py = workspace / "scripts" / "build_summaries.py"
    script_sh = workspace / "scripts" / "build_summaries.sh"
    if script_py.is_file() or script_sh.is_file():
        scores["script_exists"] = 1.0

    # incident_summary checks
    parsed_summary, sum_err, _ = _read_incident_summary_output(out_incident_summary)
    if parsed_summary is not None and sum_err is None:
        scores["incident_summary_schema"] = 1.0
        # Unique types
        types = [t for (t, _) in parsed_summary]
        if len(types) == len(set(types)):
            scores["incident_summary_unique_types"] = 1.0
        # Sorted nonincreasing by count
        counts = [c for (_, c) in parsed_summary]
        if all(counts[i] >= counts[i + 1] for i in range(len(counts) - 1)):
            scores["incident_summary_sorted_descending"] = 1.0
        # Counts correct vs input
        expected_counts, ce = _compute_incident_counts(input_incidents)
        if expected_counts is not None and ce is None:
            out_counts: Dict[str, int] = {}
            for itype, c in parsed_summary:
                out_counts[itype] = out_counts.get(itype, 0) + c
            if set(out_counts.keys()) == set(expected_counts.keys()):
                if all(out_counts.get(k) == expected_counts.get(k) for k in expected_counts):
                    scores["incident_summary_counts_correct"] = 1.0

    # clinics_in_affected_wards checks
    parsed_clinics, clinics_err, _ = _read_clinics_output(out_clinics)
    if parsed_clinics is not None and clinics_err is None:
        scores["clinics_schema"] = 1.0
        # Sorted by ward name nondecreasing
        wards_seq = [w for (w, _, _) in parsed_clinics]
        if all(wards_seq[i] <= wards_seq[i + 1] for i in range(len(wards_seq) - 1)):
            scores["clinics_sorted_by_ward"] = 1.0
        # Correct filtered set
        affected_wards, we = _compute_affected_wards(input_incidents)
        expected_clinics, ee = _load_expected_clinics(input_clinics, affected_wards or set())
        if affected_wards is not None and expected_clinics is not None and we is None and ee is None:
            out_counter = Counter(parsed_clinics)
            exp_counter = Counter(expected_clinics)
            if out_counter == exp_counter:
                scores["clinics_correct_filtered_set"] = 1.0

    # rainy_tips checks
    rainy_data, re_err = _safe_load_json(out_rainy_tips)
    schema_ok = False
    if re_err is None and isinstance(rainy_data, list):
        if len(rainy_data) == 3 and all(isinstance(x, str) for x in rainy_data):
            scores["rainy_tips_schema"] = 1.0
            schema_ok = True
    expected_tips, rte = _parse_rainy_tips_from_html(input_health_html)
    if schema_ok and expected_tips is not None and rte is None:
        if rainy_data == expected_tips[:3]:
            scores["rainy_tips_content_correct"] = 1.0

    # bulletin checks
    bulletin_text, be = _safe_read_text(out_bulletin)
    if be is None and bulletin_text is not None:
        wc = _word_count(bulletin_text)
        if 300 <= wc <= 500:
            scores["bulletin_exists_length"] = 1.0

        # Key Stats section: verify top 3 from incident_summary.csv appear in order with exact types and counts
        if parsed_summary is not None and len(parsed_summary) >= 3:
            top3 = parsed_summary[:3]
            ks_lines = _get_section_lines(bulletin_text, "Key Stats", ["Where to Seek Help", "Seasonal Health Tips"])
            if ks_lines:
                indices = []
                ok = True
                for itype, c in top3:
                    found_idx = -1
                    for idx, line in enumerate(ks_lines):
                        if itype in line and str(c) in line:
                            found_idx = idx
                            break
                    if found_idx == -1:
                        ok = False
                        break
                    indices.append(found_idx)
                if ok and all(indices[i] < indices[i + 1] for i in range(len(indices) - 1)):
                    scores["bulletin_key_stats_top3_correct"] = 1.0

        # Where to Seek Help: verify wards listed and clinics with phones
        if parsed_clinics is not None and len(parsed_clinics) > 0:
            wsh_lines = _get_section_lines(bulletin_text, "Where to Seek Help", ["Seasonal Health Tips"])
            # Check wards presence
            wards_set = set(w for (w, _, _) in parsed_clinics)
            wards_ok = True
            for w in wards_set:
                present = any(w in line for line in wsh_lines)
                if not present:
                    wards_ok = False
                    break
            if wards_ok:
                scores["bulletin_where_to_seek_help_wards_listed"] = 1.0
            # Check each clinic name with phone appears on some single line
            clinics_ok = True
            for (_, clinic_name, phone) in parsed_clinics:
                present = any((clinic_name in line and phone in line) for line in wsh_lines)
                if not present:
                    clinics_ok = False
                    break
            if clinics_ok:
                scores["bulletin_where_to_seek_help_clinics_listed"] = 1.0

        # Seasonal Health Tips: exactly the three tips from rainy_tips.json
        if isinstance(rainy_data, list) and len(rainy_data) == 3 and all(isinstance(x, str) for x in rainy_data):
            sht_lines = _get_section_lines(bulletin_text, "Seasonal Health Tips", [])
            filtered = [ln for ln in sht_lines if ln.strip() != ""]
            all_lines_valid = all(any(tip in ln for tip in rainy_data) for ln in filtered)
            all_tips_present = all(any(tip in ln for ln in filtered) for tip in rainy_data)
            if filtered and all_lines_valid and all_tips_present:
                unique_tips_found = set()
                for tip in rainy_data:
                    for ln in filtered:
                        if tip in ln:
                            unique_tips_found.add(tip)
                            break
                if len(unique_tips_found) == 3:
                    scores["bulletin_seasonal_tips_exact"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade(transcript=[], workspace_path=workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()