import json
import sys
import csv
import math
import re
from pathlib import Path
from html.parser import HTMLParser


def _read_csv_rows(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            sniffer = csv.Sniffer()
            sample = f.read(1024)
            f.seek(0)
            try:
                sniffer.has_header(sample)
            except Exception:
                pass
            reader = csv.DictReader(f)
            rows = [dict((k.strip() if k is not None else k, v.strip() if isinstance(v, str) else v) for k, v in row.items()) for row in reader]
            return rows, None
    except Exception as e:
        return None, str(e)


def _load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)


class _CodebookHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_codebook_table = False
        self.current_tag = None
        self.in_tbody = False
        self.in_tr = False
        self.in_td = False
        self.current_tds = []
        self.rows = []
        self._attrs_stack = []

    def handle_starttag(self, tag, attrs):
        self._attrs_stack.append(dict(attrs))
        if tag == "table":
            attrs_dict = dict(attrs)
            if attrs_dict.get("id") == "codebook":
                self.in_codebook_table = True
        if self.in_codebook_table and tag == "tbody":
            self.in_tbody = True
        if self.in_codebook_table and self.in_tbody and tag == "tr":
            self.in_tr = True
            self.current_tds = []
        if self.in_codebook_table and self.in_tbody and self.in_tr and tag == "td":
            self.in_td = True
            self.current_tag = tag

    def handle_endtag(self, tag):
        if tag == "td" and self.in_td:
            self.in_td = False
        if tag == "tr" and self.in_tr:
            self.in_tr = False
            if self.current_tds:
                self.rows.append(self.current_tds)
            self.current_tds = []
        if tag == "tbody" and self.in_tbody:
            self.in_tbody = False
        if tag == "table" and self.in_codebook_table:
            self.in_codebook_table = False
        if self._attrs_stack:
            self._attrs_stack.pop()

    def handle_data(self, data):
        if self.in_codebook_table and self.in_tbody and self.in_tr and self.in_td:
            text = data.strip()
            if text:
                self.current_tds.append(text)


def _parse_codebook_html(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        return None, f"read error: {e}"
    parser = _CodebookHTMLParser()
    try:
        parser.feed(text)
    except Exception as e:
        return None, f"parse error: {e}"
    mapping = {}
    for row in parser.rows:
        if len(row) >= 2:
            code = row[0].strip()
            label = row[1].strip()
            if code and label:
                mapping[code] = label
    if not mapping:
        return None, "no mapping found"
    return mapping, None


def _safe_int(x):
    try:
        return int(x)
    except Exception:
        return None


def _safe_float(x):
    try:
        return float(x)
    except Exception:
        return None


def _compute_exposures(adolescents_rows, friendships_rows):
    students = {}
    for row in adolescents_rows:
        sid = _safe_int(row.get("id"))
        if sid is None:
            continue
        students[sid] = {
            "school_id": row.get("school_id"),
            "grade": row.get("grade"),
            "B1": _safe_int(row.get("B1")),
            "B2": _safe_int(row.get("B2")),
        }
    adj = {}
    for sid in students.keys():
        adj[sid] = set()
    for row in friendships_rows:
        from_id = _safe_int(row.get("from_id"))
        to_id = _safe_int(row.get("to_id"))
        if from_id is None or to_id is None:
            continue
        if from_id not in students or to_id not in students:
            continue
        if students[from_id]["school_id"] != students[to_id]["school_id"]:
            continue
        adj.setdefault(from_id, set()).add(to_id)
    exposures_by_id = {}
    for sid, info in students.items():
        step1 = set(adj.get(sid, set()))
        step2_neighbors = set()
        for n in step1:
            step2_neighbors.update(adj.get(n, set()))
        up_to_two = (step1 | step2_neighbors)
        if sid in up_to_two:
            up_to_two.discard(sid)

        def frac_with_behavior(alter_set, behavior_key):
            if not alter_set or len(alter_set) == 0:
                return None
            vals = []
            for aid in alter_set:
                a = students.get(aid)
                if a is None:
                    continue
                vals.append(1 if a.get(behavior_key) == 1 else 0)
            if len(vals) == 0:
                return None
            return sum(vals) / float(len(vals))

        exposures_by_id[sid] = {
            "school_id": info["school_id"],
            "grade": info["grade"],
            "B1_1": frac_with_behavior(step1, "B1"),
            "B1_2": frac_with_behavior(up_to_two, "B1"),
            "B2_1": frac_with_behavior(step1, "B2"),
            "B2_2": frac_with_behavior(up_to_two, "B2"),
        }
    return exposures_by_id, students


def _compare_float(a, b, tol=1e-9):
    if a is None and b is None:
        return True
    if (a is None) != (b is None):
        return False
    return abs(float(a) - float(b)) <= tol


def _read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8"), None
    except Exception as e:
        return None, str(e)


def _parse_exposures_csv(path: Path, b1_label: str, b2_label: str):
    rows, err = _read_csv_rows(path)
    if rows is None:
        return None, None, f"read error: {err}"
    expected_headers = [
        "id",
        "school_id",
        "grade",
        f"{b1_label}_1step",
        f"{b1_label}_2step",
        f"{b2_label}_1step",
        f"{b2_label}_2step",
    ]
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)
            header = [h.strip() for h in header]
    except Exception:
        header = list(rows[0].keys()) if rows else []
    return rows, (header, expected_headers), None


def _parse_summary_by_grade_csv(path: Path):
    rows, err = _read_csv_rows(path)
    if rows is None:
        return None, f"read error: {err}"
    norm = []
    for r in rows:
        norm.append({
            "school_id": r.get("school_id"),
            "grade": r.get("grade"),
            "behavior_label": r.get("behavior_label"),
            "radius": r.get("radius"),
            "mean_exposure": _safe_float(r.get("mean_exposure")),
            "n_students_used": _safe_int(r.get("n_students_used")),
        })
    return norm, None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "codebook_json_mapping_correct": 0.0,
        "exposures_csv_headers_correct": 0.0,
        "exposures_values_match_expected": 0.0,
        "exposures_na_representation_correct": 0.0,
        "summary_by_grade_values_correct": 0.0,
        "validation_log_pass_and_label": 0.0,
        "status_md_covers_definitions": 0.0,
        "status_md_confirms_validation_and_command": 0.0,
        "status_md_summarizes_key_numbers": 0.0,
    }

    input_dir = workspace / "input"
    outputs_dir = workspace / "outputs"
    logs_dir = workspace / "logs"
    reports_dir = workspace / "reports"

    codebook_html_path = input_dir / "codebook.html"
    codebook_map, cb_err = _parse_codebook_html(codebook_html_path) if codebook_html_path.exists() else (None, "missing input codebook")
    expected_code_to_label = {}
    if codebook_map:
        if "B1" in codebook_map and "B2" in codebook_map:
            expected_code_to_label = {"B1": codebook_map["B1"], "B2": codebook_map["B2"]}
        else:
            expected_code_to_label = codebook_map

    codebook_json_path = outputs_dir / "codebook.json"
    if codebook_json_path.exists():
        cb_json, err = _load_json(codebook_json_path)
        if cb_json is not None and isinstance(cb_json, dict) and expected_code_to_label:
            expected = {"B1": expected_code_to_label.get("B1"), "B2": expected_code_to_label.get("B2")}
            if set(cb_json.keys()) == set(expected.keys()):
                if all(cb_json.get(k) == expected.get(k) for k in expected.keys()):
                    scores["codebook_json_mapping_correct"] = 1.0

    adolescents_path = input_dir / "adolescents.csv"
    friendships_path = input_dir / "friendships.csv"
    exposures_expected = None
    students_info = None
    if adolescents_path.exists() and friendships_path.exists():
        ad_rows, ad_err = _read_csv_rows(adolescents_path)
        fr_rows, fr_err = _read_csv_rows(friendships_path)
        if ad_rows is not None and fr_rows is not None:
            exposures_expected, students_info = _compute_exposures(ad_rows, fr_rows)

    exposures_csv_path = outputs_dir / "exposures.csv"
    if exposures_csv_path.exists() and expected_code_to_label:
        b1_label = expected_code_to_label.get("B1")
        b2_label = expected_code_to_label.get("B2")
        rows, headers_info, err = _parse_exposures_csv(exposures_csv_path, b1_label, b2_label)
        if rows is not None and headers_info is not None:
            actual_header, expected_header = headers_info
            if actual_header == expected_header:
                scores["exposures_csv_headers_correct"] = 1.0
            row_by_id = {}
            all_na_format_ok = True
            values_ok = True
            if exposures_expected and students_info:
                for r in rows:
                    rid = _safe_int(r.get("id"))
                    if rid is not None:
                        row_by_id[rid] = r
                if set(row_by_id.keys()) == set(exposures_expected.keys()):
                    for sid, exp in exposures_expected.items():
                        r = row_by_id.get(sid)
                        if r is None:
                            values_ok = False
                            break
                        if str(r.get("school_id")) != str(exp["school_id"]) or str(r.get("grade")) != str(exp["grade"]):
                            values_ok = False
                            break
                        checks = [
                            (f"{b1_label}_1step", exp["B1_1"]),
                            (f"{b1_label}_2step", exp["B1_2"]),
                            (f"{b2_label}_1step", exp["B2_1"]),
                            (f"{b2_label}_2step", exp["B2_2"]),
                        ]
                        for col, expected_val in checks:
                            cell = r.get(col)
                            if expected_val is None:
                                if cell != "NA":
                                    all_na_format_ok = False
                            else:
                                fv = _safe_float(cell)
                                if fv is None or (not _compare_float(fv, expected_val)):
                                    values_ok = False
                    if values_ok:
                        scores["exposures_values_match_expected"] = 1.0
                    if all_na_format_ok:
                        scores["exposures_na_representation_correct"] = 1.0

    summary_path = outputs_dir / "summary_by_grade.csv"
    if summary_path.exists() and exposures_expected and expected_code_to_label:
        summary_rows, s_err = _parse_summary_by_grade_csv(summary_path)
        if summary_rows is not None:
            b1_label = expected_code_to_label.get("B1")
            b2_label = expected_code_to_label.get("B2")
            group_keys = {}
            for sid, info in exposures_expected.items():
                sg = (info["school_id"], str(students_info[sid]["grade"]))
                group_keys.setdefault(sg, []).append(sid)
            expected_summary = {}
            for (school_id, grade), sids in group_keys.items():
                for label, behavior_prefix in [(b1_label, "B1"), (b2_label, "B2")]:
                    for radius, suffix in [("1step", "1"), ("2step", "2")]:
                        vals = []
                        for sid in sids:
                            v = exposures_expected[sid][f"{behavior_prefix}_{suffix}"]
                            if v is not None and not (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
                                vals.append(float(v))
                        n_used = len(vals)
                        mean_val = (sum(vals) / n_used) if n_used > 0 else None
                        key = (school_id, grade, label, radius)
                        expected_summary[key] = (mean_val, n_used)
            actual_summary = {}
            for r in summary_rows:
                key = (r.get("school_id"), str(r.get("grade")), r.get("behavior_label"), r.get("radius"))
                actual_summary[key] = (r.get("mean_exposure"), r.get("n_students_used"))
            if set(actual_summary.keys()) == set(expected_summary.keys()):
                all_ok = True
                for key, (mean_val, n_used) in expected_summary.items():
                    act_mean, act_n = actual_summary.get(key)
                    if n_used == 0:
                        if act_n != 0:
                            all_ok = False
                            break
                    else:
                        if act_n != n_used:
                            all_ok = False
                            break
                        if act_mean is None:
                            all_ok = False
                            break
                        if not _compare_float(act_mean, mean_val):
                            all_ok = False
                            break
                if all_ok:
                    scores["summary_by_grade_values_correct"] = 1.0

    validation_log_path = logs_dir / "validation.txt"
    if validation_log_path.exists():
        txt, err = _read_text(validation_log_path)
        if txt is not None:
            contains_pass = ("PASS" in txt)
            label_ok = False
            if expected_code_to_label:
                b1_label = expected_code_to_label.get("B1")
                if b1_label and (f"{b1_label}_1step" in txt):
                    label_ok = True
            if contains_pass and label_ok:
                scores["validation_log_pass_and_label"] = 1.0

    status_md_path = reports_dir / "status.md"
    if status_md_path.exists():
        status_txt, err = _read_text(status_md_path)
        if status_txt is not None:
            lower = status_txt.lower()
            defs_ok = all([
                ("1-step" in lower or "1step" in lower or "one-step" in lower),
                ("2-step" in lower or "2step" in lower or "two-step" in lower),
                ("na" in lower and ("zero" in lower or "0-friend" in lower or "no friends" in lower or "0 friend" in lower)),
                ("unique" in lower or "de-dup" in lower or "dedup" in lower or "de-duplicate" in lower or "de duplicate" in lower),
                ("directed" in lower or "outgoing" in lower),
                (("within" in lower and "school" in lower) or ("same school" in lower)),
            ])
            if defs_ok:
                scores["status_md_covers_definitions"] = 1.0

            has_validation = ("validation" in lower and "pass" in lower)
            has_command = any(tok in lower for tok in ["python ", "make ", "./", "bash ", "sh "])
            if has_validation and has_command:
                scores["status_md_confirms_validation_and_command"] = 1.0

            labels_ok = True
            if expected_code_to_label:
                b1_label = expected_code_to_label.get("B1")
                b2_label = expected_code_to_label.get("B2")
                labels_ok = (b1_label in status_txt) and (b2_label in status_txt)
            has_numbers = bool(re.search(r"\d+(\.\d+)?", status_txt))
            has_summary_context = ("summary" in lower or "mean" in lower or "average" in lower)
            if labels_ok and has_numbers and has_summary_context:
                scores["status_md_summarizes_key_numbers"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()