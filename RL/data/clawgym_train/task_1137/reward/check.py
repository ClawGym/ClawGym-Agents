import json
import csv
import sys
from pathlib import Path
from html.parser import HTMLParser
from typing import List, Dict, Optional, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


class _HTMLTableParser(HTMLParser):
    def __init__(self, target_table_id: Optional[str] = None):
        super().__init__()
        self.target_table_id = target_table_id
        self.in_target_table = False
        self.current_table_has_id = False
        self.in_thead = False
        self.in_tbody = False
        self.in_tr = False
        self.in_th = False
        self.in_td = False
        self.current_cell_text = []
        self.headers: List[str] = []
        self.current_row: List[str] = []
        self.rows: List[List[str]] = []
        self.table_stack = 0
        self.pending_table_id = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.table_stack += 1
            attrs_dict = dict(attrs)
            self.pending_table_id = attrs_dict.get("id")
            if self.target_table_id is None or attrs_dict.get("id") == self.target_table_id:
                self.in_target_table = True
                self.current_table_has_id = True
        if not self.in_target_table:
            return
        if tag == "thead":
            self.in_thead = True
        elif tag == "tbody":
            self.in_tbody = True
        elif tag == "tr":
            self.in_tr = True
            self.current_row = []
        elif tag == "th":
            self.in_th = True
            self.current_cell_text = []
        elif tag == "td":
            self.in_td = True
            self.current_cell_text = []

    def handle_endtag(self, tag):
        if tag == "table":
            if self.in_target_table and self.current_table_has_id:
                self.in_target_table = False
                self.current_table_has_id = False
            self.table_stack = max(0, self.table_stack - 1)
            self.pending_table_id = None
        if not self.in_target_table:
            return
        if tag == "thead":
            self.in_thead = False
        elif tag == "tbody":
            self.in_tbody = False
        elif tag == "tr":
            if self.in_tr:
                if self.in_thead and self.current_row:
                    pass
                elif self.in_tbody and self.current_row:
                    self.rows.append(self.current_row)
                self.current_row = []
            self.in_tr = False
        elif tag == "th":
            if self.in_th:
                text = "".join(self.current_cell_text).strip()
                self.headers.append(text)
                self.current_cell_text = []
            self.in_th = False
        elif tag == "td":
            if self.in_td:
                text = "".join(self.current_cell_text).strip()
                self.current_row.append(text)
                self.current_cell_text = []
            self.in_td = False

    def handle_data(self, data):
        if not self.in_target_table:
            return
        if self.in_th or self.in_td:
            self.current_cell_text.append(data)


def _parse_html_methods(path: Path) -> Optional[List[Dict[str, str]]]:
    html = _read_text_safe(path)
    if html is None:
        return None
    parser = _HTMLTableParser(target_table_id="methods")
    try:
        parser.feed(html)
    except Exception:
        return None
    header_map = {
        "Method Name": "method_name",
        "Explanation Type": "explanation_type",
        "Approach": "approach",
        "Model Compatibility": "model_compatibility",
        "Compute Cost": "compute_cost",
        "Faithfulness": "faithfulness",
        "Open Source": "open_source",
    }
    if not parser.headers:
        return None
    norm_headers = []
    for h in parser.headers:
        if h not in header_map:
            return None
        norm_headers.append(header_map[h])
    records: List[Dict[str, str]] = []
    for row in parser.rows:
        if len(row) != len(norm_headers):
            return None
        rec = {}
        for i, key in enumerate(norm_headers):
            rec[key] = row[i].strip()
        records.append(rec)
    return records


def _parse_csv_methods(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            required = [
                "method_name",
                "explanation_type",
                "approach",
                "model_compatibility",
                "compute_cost",
                "faithfulness",
                "open_source",
            ]
            if reader.fieldnames is None:
                return None
            fieldnames_lower = [h.strip() for h in reader.fieldnames]
            if any(h not in fieldnames_lower for h in required):
                lower_to_orig = {h.lower(): h for h in reader.fieldnames}
                if any(req not in lower_to_orig for req in required):
                    return None
                f.seek(0)
                reader = csv.DictReader(f)
            records = []
            for row in reader:
                if row is None:
                    return None
                rec = {}
                for k in required:
                    val = row.get(k, None)
                    if val is None:
                        found = None
                        for key in row.keys():
                            if key.strip().lower() == k:
                                found = row[key]
                                break
                        if found is None:
                            return None
                        val = found
                    rec[k] = (val or "").strip()
                records.append(rec)
            return records
    except Exception:
        return None


def _extract_yaml_block_from_markdown(md_text: str) -> Optional[str]:
    lines = md_text.splitlines()
    inside = False
    collected: List[str] = []
    for i, line in enumerate(lines):
        if not inside:
            if line.strip().startswith("```yaml"):
                inside = True
                continue
        else:
            if line.strip().startswith("```"):
                break
            else:
                collected.append(line.rstrip("\n"))
    if not collected:
        return None
    return "\n".join(collected).strip() + "\n"


def _parse_simple_yaml(yaml_text: str) -> Optional[dict]:
    try:
        lines = [ln.rstrip() for ln in yaml_text.splitlines() if ln.strip() != "" and not ln.strip().startswith("#")]
        root: dict = {}
        stack: List[Tuple[int, dict, Optional[str]]] = [(0, root, None)]
        for raw_line in lines:
            indent = len(raw_line) - len(raw_line.lstrip(" "))
            line = raw_line.strip()
            while stack and indent < stack[-1][0]:
                stack.pop()
            if not stack:
                return None
            current_container = stack[-1][1]
            if ":" not in line:
                return None
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            if val == "":
                new_map: dict = {}
                current_container[key] = new_map
                stack.append((indent + 2, new_map, key))
            else:
                parsed_val = _parse_yaml_scalar(val)
                current_container[key] = parsed_val
        return root
    except Exception:
        return None


def _parse_yaml_scalar(val: str):
    v = val.strip()
    if v.startswith('"') and v.endswith('"'):
        v = v[1:-1]
        return v
    if v.startswith("'") and v.endswith("'"):
        v = v[1:-1]
        return v
    if v.lower() == "true":
        return True
    if v.lower() == "false":
        return False
    try:
        return int(v)
    except ValueError:
        pass
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if inner == "":
            return []
        parts = []
        buf = ""
        in_quote = False
        quote_char = ""
        for ch in inner:
            if ch in ("'", '"'):
                if not in_quote:
                    in_quote = True
                    quote_char = ch
                elif in_quote and ch == quote_char:
                    in_quote = False
                buf += ch
            elif ch == "," and not in_quote:
                parts.append(buf.strip())
                buf = ""
            else:
                buf += ch
        if buf:
            parts.append(buf.strip())
        cleaned: List[str] = []
        for p in parts:
            pv = p.strip()
            if pv.startswith('"') and pv.endswith('"'):
                pv = pv[1:-1]
            elif pv.startswith("'") and pv.endswith("'"):
                pv = pv[1:-1]
            cleaned.append(pv)
        return cleaned
    return v


def _normalize_record(rec: Dict[str, str]) -> Dict[str, str]:
    out = {}
    for k, v in rec.items():
        if isinstance(v, str):
            out[k] = v.strip()
        else:
            out[k] = v
    return out


def _index_by_method_name(records: List[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    idx = {}
    for rec in records:
        name = rec.get("method_name", "")
        idx[name.lower()] = rec
    return idx


def _compute_score(rec: Dict[str, str], prefs: dict) -> Optional[int]:
    try:
        weights = prefs["scoring"]["weights"]
        mappings = prefs["scoring"]["mappings"]
        tree_compat_vals = set(prefs["filters"]["tree_compatibility_definition"])
        is_tree_compatible = 1 if rec["model_compatibility"] in tree_compat_vals else 0
        is_local = 1 if rec["explanation_type"] == prefs["filters"]["required_explanation_type"] else 0
        open_source_score = 1 if rec["open_source"] == "Yes" else 0
        faithfulness_score = mappings["faithfulness"].get(rec["faithfulness"], None)
        compute_eff_score = mappings["compute_efficiency"].get(rec["compute_cost"], None)
        if faithfulness_score is None or compute_eff_score is None:
            return None
        score = (
            weights["tree_compatibility"] * is_tree_compatible
            + weights["local_explanation"] * is_local
            + weights["faithfulness"] * faithfulness_score
            + weights["compute_efficiency"] * compute_eff_score
            + weights["open_source"] * open_source_score
        )
        return int(score)
    except Exception:
        return None


def _apply_filters(rec: Dict[str, str], prefs: dict) -> bool:
    try:
        if rec.get("explanation_type") != prefs["filters"]["required_explanation_type"]:
            return False
        if rec.get("compute_cost") == prefs["filters"]["exclude_compute_cost"]:
            return False
        if prefs["filters"]["require_open_source"] and rec.get("open_source") != "Yes":
            return False
        if rec.get("model_compatibility") not in set(prefs["filters"]["tree_compatibility_definition"]):
            return False
        return True
    except Exception:
        return False


def _expected_from_inputs(workspace: Path) -> Optional[dict]:
    csv_path = workspace / "input" / "catalog" / "methods_catalog.csv"
    html_path = workspace / "input" / "webpage" / "interpretability_methods.html"
    md_path = workspace / "input" / "notes" / "preferences.md"
    csv_records = _parse_csv_methods(csv_path)
    html_records = _parse_html_methods(html_path)
    md_text = _read_text_safe(md_path)
    if csv_records is None or html_records is None or md_text is None:
        return None
    yaml_text = _extract_yaml_block_from_markdown(md_text)
    if yaml_text is None:
        return None
    prefs = _parse_simple_yaml(yaml_text)
    if prefs is None:
        return None
    csv_norm = [_normalize_record(r) for r in csv_records]
    html_norm = [_normalize_record(r) for r in html_records]
    idx_csv = _index_by_method_name(csv_norm)
    idx_html = _index_by_method_name(html_norm)
    common_keys = sorted(set(idx_csv.keys()) & set(idx_html.keys()))
    merged_records = []
    for key in common_keys:
        base = dict(idx_csv[key])
        merged_records.append(base)
    scored_merged = []
    for rec in merged_records:
        score = _compute_score(rec, prefs)
        scored_merged.append((rec, score))
    filtered = []
    for rec, score in scored_merged:
        if _apply_filters(rec, prefs):
            filtered.append((rec, score))
    faith_map = prefs["scoring"]["mappings"]["faithfulness"]
    eff_map = prefs["scoring"]["mappings"]["compute_efficiency"]

    def sort_key(item):
        rec, score = item
        sc = score if score is not None else -10**6
        faith = faith_map.get(rec["faithfulness"], -10**6)
        eff = eff_map.get(rec["compute_cost"], -10**6)
        return (-sc, -faith, -eff, rec["method_name"].lower())

    filtered_sorted = sorted(filtered, key=sort_key)
    top3 = filtered_sorted[:3]
    all_names = set(idx_csv.keys()) | set(idx_html.keys())
    expected = {
        "prefs_yaml_text": yaml_text,
        "prefs_dict": prefs,
        "merged_records": [r for r, _ in scored_merged],
        "merged_scores": {r["method_name"]: (s if s is not None else None) for r, s in scored_merged},
        "filtered_records": [r for r, _ in filtered_sorted],
        "filtered_scores": {r["method_name"]: (s if s is not None else None) for r, s in filtered_sorted},
        "top3": [{"method_name": rec["method_name"], "computed_score": int(score if score is not None else -10**6), "rec": rec} for rec, score in top3],
        "consistency_union": sorted(all_names),
        "in_html": {name: (name in idx_html) for name in all_names},
        "in_csv": {name: (name in idx_csv) for name in all_names},
    }
    return expected


def _split_merged_csv_sections(path: Path) -> Optional[Tuple[List[Dict[str, str]], List[Dict[str, str]], str]]:
    text = _read_text_safe(path)
    if text is None:
        return None
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: List[List[str]] = []
    current: List[str] = []
    for ln in lines:
        if ln.strip() == "":
            if current:
                blocks.append(current)
                current = []
        else:
            current.append(ln)
    if current:
        blocks.append(current)
    if len(blocks) != 2:
        return None
    block1, block2 = blocks
    if not block1 or not block2:
        return None
    header1 = block1[0]
    header2 = block2[0]
    expected_header = "method_name,explanation_type,approach,model_compatibility,compute_cost,faithfulness,open_source,sources,computed_score"
    if header1.strip() != expected_header or header2.strip() != expected_header:
        return None
    try:
        merged_section_rows: List[Dict[str, str]] = []
        filtered_section_rows: List[Dict[str, str]] = []
        reader1 = csv.DictReader(block1)
        for row in reader1:
            if row:
                merged_section_rows.append({k: (v or "").strip() for k, v in row.items()})
        reader2 = csv.DictReader(block2)
        for row in reader2:
            if row:
                filtered_section_rows.append({k: (v or "").strip() for k, v in row.items()})
        return merged_section_rows, filtered_section_rows, expected_header
    except Exception:
        return None


def _parse_json_file(path: Path) -> Optional[object]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_tsv_file(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            lines = [ln.rstrip("\n") for ln in f.readlines()]
        if not lines:
            return None
        header = lines[0]
        if header != "method_name\tin_html\tin_csv":
            return None
        rows: List[Dict[str, str]] = []
        for ln in lines[1:]:
            if not ln:
                continue
            parts = ln.split("\t")
            if len(parts) != 3:
                return None
            rows.append({"method_name": parts[0], "in_html": parts[1], "in_csv": parts[2]})
        return rows
    except Exception:
        return None


def _bool_str(value: bool) -> str:
    return "true" if value else "false"


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "merged_csv_present_and_headers": 0.0,
        "merged_csv_merged_section_correct_rows": 0.0,
        "merged_csv_filtered_section_correct_rows": 0.0,
        "merged_csv_computed_scores_correct": 0.0,
        "merged_csv_sources_field_correct": 0.0,
        "top3_json_structure_and_order": 0.0,
        "top3_json_scores_match": 0.0,
        "top3_json_why_attributes_cited": 0.0,
        "consistency_report_complete_and_correct": 0.0,
        "preferences_extracted_yaml_correct": 0.0,
    }

    expected = _expected_from_inputs(workspace)

    merged_csv_path = workspace / "output" / "normalized" / "methods_merged.csv"
    sections = _split_merged_csv_sections(merged_csv_path)
    if sections is not None and expected is not None:
        merged_rows, filtered_rows, _ = sections
        scores["merged_csv_present_and_headers"] = 1.0

        exp_merged_recs = expected["merged_records"]
        exp_merged_names = set([r["method_name"] for r in exp_merged_recs])

        got_merged_names = set([r.get("method_name", "") for r in merged_rows if r.get("method_name", "") != ""])
        if got_merged_names == exp_merged_names and len(merged_rows) == len(exp_merged_names):
            all_match = True
            for got in merged_rows:
                mname = got["method_name"]
                exp_rec = next((r for r in exp_merged_recs if r["method_name"] == mname), None)
                if exp_rec is None:
                    all_match = False
                    break
                for field in ["explanation_type", "approach", "model_compatibility", "compute_cost", "faithfulness", "open_source"]:
                    if got.get(field, "") != exp_rec.get(field, ""):
                        all_match = False
                        break
                if not all_match:
                    break
            if all_match:
                scores["merged_csv_merged_section_correct_rows"] = 1.0

        exp_filtered_recs = []
        for rec in expected["filtered_records"]:
            exp_filtered_recs.append(rec)
        exp_filtered_names = set([r["method_name"] for r in exp_filtered_recs])
        got_filtered_names = set([r.get("method_name", "") for r in filtered_rows if r.get("method_name", "") != ""])
        if got_filtered_names == exp_filtered_names and len(filtered_rows) == len(exp_filtered_names):
            all_match_f = True
            for got in filtered_rows:
                mname = got["method_name"]
                exp_rec = next((r for r in exp_filtered_recs if r["method_name"] == mname), None)
                if exp_rec is None:
                    all_match_f = False
                    break
                for field in ["explanation_type", "approach", "model_compatibility", "compute_cost", "faithfulness", "open_source"]:
                    if got.get(field, "") != exp_rec.get(field, ""):
                        all_match_f = False
                        break
                if not all_match_f:
                    break
            if all_match_f:
                scores["merged_csv_filtered_section_correct_rows"] = 1.0

        scores_ok = True
        if scores["merged_csv_present_and_headers"] == 1.0:
            for got in merged_rows:
                mname = got["method_name"]
                exp_score = expected["merged_scores"].get(mname, None)
                got_score_str = got.get("computed_score", "").strip()
                try:
                    got_score = int(got_score_str)
                except Exception:
                    scores_ok = False
                    break
                if exp_score is None or got_score != int(exp_score):
                    scores_ok = False
                    break
            if scores_ok:
                for got in filtered_rows:
                    mname = got["method_name"]
                    exp_score = expected["filtered_scores"].get(mname, None)
                    got_score_str = got.get("computed_score", "").strip()
                    try:
                        got_score = int(got_score_str)
                    except Exception:
                        scores_ok = False
                        break
                    if exp_score is None or got_score != int(exp_score):
                        scores_ok = False
                        break
        if scores_ok:
            scores["merged_csv_computed_scores_correct"] = 1.0

        sources_ok = True
        for row in merged_rows + filtered_rows:
            sources_field = row.get("sources", "")
            parts = [p.strip().lower() for p in sources_field.split(",") if p.strip() != ""]
            if set(parts) != {"html", "csv"}:
                sources_ok = False
                break
        if sources_ok:
            scores["merged_csv_sources_field_correct"] = 1.0

    top3_path = workspace / "output" / "filtered" / "top3_methods.json"
    top3_data = _parse_json_file(top3_path)
    if top3_data is not None and isinstance(top3_data, list) and expected is not None:
        exp_top3 = expected["top3"]
        names_ok = False
        scores_match = False
        why_ok = False
        if len(top3_data) == len(exp_top3) == 3:
            got_names = [item.get("method_name") for item in top3_data]
            exp_names = [item["method_name"] for item in exp_top3]
            if got_names == exp_names:
                names_ok = True
            score_all_ok = True
            for got_item, exp_item in zip(top3_data, exp_top3):
                got_score = got_item.get("computed_score", None)
                exp_score = exp_item.get("computed_score", None)
                if not isinstance(got_score, int) or got_score != exp_score:
                    score_all_ok = False
                    break
            if score_all_ok:
                scores_match = True
            why_all_ok = True
            for idx, got_item in enumerate(top3_data):
                why = got_item.get("why", "")
                if not isinstance(why, str) or why.strip() == "":
                    why_all_ok = False
                    break
                rec = exp_top3[idx]["rec"]
                attribute_values = [
                    rec.get("explanation_type", ""),
                    rec.get("model_compatibility", ""),
                    rec.get("compute_cost", ""),
                    rec.get("faithfulness", ""),
                    rec.get("open_source", ""),
                ]
                attribute_names = ["explanation_type", "model_compatibility", "compute_cost", "faithfulness", "open_source"]
                why_lower = why.lower()
                count = 0
                cited = set()
                for name in attribute_names:
                    if name in why_lower and name not in cited:
                        cited.add(name)
                        count += 1
                for val in attribute_values:
                    vlow = str(val).lower()
                    if vlow and vlow in why_lower and vlow not in cited:
                        cited.add(vlow)
                        count += 1
                if count < 3:
                    why_all_ok = False
                    break
            if why_all_ok:
                why_ok = True
        if names_ok:
            scores["top3_json_structure_and_order"] = 1.0
        if scores_match:
            scores["top3_json_scores_match"] = 1.0
        if why_ok:
            scores["top3_json_why_attributes_cited"] = 1.0

    report_path = workspace / "output" / "reports" / "consistency_report.tsv"
    tsv_rows = _parse_tsv_file(report_path)
    if tsv_rows is not None and expected is not None:
        exp_names_set = set([name for name in expected["consistency_union"]])
        got_names_set = set([row["method_name"].lower() for row in tsv_rows])
        if got_names_set == exp_names_set and len(tsv_rows) == len(exp_names_set):
            bools_ok = True
            exp_in_html = expected["in_html"]
            exp_in_csv = expected["in_csv"]
            for row in tsv_rows:
                key_lower = row["method_name"].lower()
                expected_html = exp_in_html.get(key_lower, False)
                expected_csv = exp_in_csv.get(key_lower, False)
                got_html = row["in_html"].strip().lower()
                got_csv = row["in_csv"].strip().lower()
                if got_html not in ("true", "false") or got_csv not in ("true", "false"):
                    bools_ok = False
                    break
                if got_html != _bool_str(expected_html) or got_csv != _bool_str(expected_csv):
                    bools_ok = False
                    break
            if bools_ok:
                scores["consistency_report_complete_and_correct"] = 1.0

    prefs_out_path = workspace / "output" / "parsed" / "preferences_extracted.yaml"
    prefs_out_text = _read_text_safe(prefs_out_path)
    if prefs_out_text is not None and expected is not None:
        got_prefs = _parse_simple_yaml(prefs_out_text)
        if got_prefs is not None:
            if got_prefs == expected["prefs_dict"]:
                scores["preferences_extracted_yaml_correct"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()