import json
import csv
import sys
import re
import ast
from html.parser import HTMLParser
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_file(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_jsonl_file(path: Path) -> Optional[List[Any]]:
    try:
        records = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                records.append(json.loads(line))
        return records
    except Exception:
        return None


class InventoryHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_inventory_table = False
        self.in_tbody = False
        self.in_tr = False
        self.in_td = False
        self.current_cells: List[str] = []
        self.rows: List[List[str]] = []
        self._current_table_id: Optional[str] = None

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "table":
            attrs_dict = dict(attrs)
            self._current_table_id = attrs_dict.get("id", None)
            if self._current_table_id == "inventory":
                self.in_inventory_table = True
        if self.in_inventory_table and tag.lower() == "tbody":
            self.in_tbody = True
        if self.in_inventory_table and self.in_tbody and tag.lower() == "tr":
            self.in_tr = True
            self.current_cells = []
        if self.in_inventory_table and self.in_tbody and self.in_tr and tag.lower() == "td":
            self.in_td = True

    def handle_endtag(self, tag):
        if self.in_inventory_table and self.in_tbody and tag.lower() == "td":
            self.in_td = False
        if self.in_inventory_table and tag.lower() == "tr" and self.in_tr:
            if self.current_cells:
                self.rows.append(self.current_cells[:])
            self.in_tr = False
        if self.in_inventory_table and tag.lower() == "tbody":
            self.in_tbody = False
        if tag.lower() == "table" and self.in_inventory_table:
            self.in_inventory_table = False
            self._current_table_id = None

    def handle_data(self, data):
        if self.in_inventory_table and self.in_tbody and self.in_tr and self.in_td:
            text = data.strip()
            if text:
                self.current_cells.append(text)


def parse_inventory_html(path: Path) -> Optional[List[Dict[str, Any]]]:
    html = read_text(path)
    if html is None:
        return None
    parser = InventoryHTMLParser()
    try:
        parser.feed(html)
    except Exception:
        return None
    rows = parser.rows
    parsed: List[Dict[str, Any]] = []
    for cells in rows:
        if len(cells) != 4:
            return None
        node, device, model, capacity = cells
        try:
            cap = float(capacity)
        except Exception:
            return None
        parsed.append({
            "node": node,
            "device": device,
            "model": model,
            "capacity_tb": cap,
        })
    return parsed


def parse_metrics_mapping_from_py(path: Path) -> Optional[Dict[Tuple[str, str, int], Dict[str, Any]]]:
    text = read_text(path)
    if text is None:
        return None
    try:
        tree = ast.parse(text)
    except Exception:
        return None
    metrics_dict = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "metrics":
                    try:
                        metrics_dict = ast.literal_eval(node.value)
                    except Exception:
                        return None
    if not isinstance(metrics_dict, dict):
        return None
    conv: Dict[Tuple[str, str, int], Dict[str, Any]] = {}
    for k, v in metrics_dict.items():
        if not (isinstance(k, tuple) and len(k) == 3 and isinstance(k[0], str) and isinstance(k[1], str) and isinstance(k[2], int)):
            return None
        if not isinstance(v, dict):
            return None
        conv[(k[0], k[1], k[2])] = v
    return conv


def float_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def load_csv_dicts(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None
            rows = [row for row in reader]
            return header, rows
    except Exception:
        return None


def normalize_csv_row_types(row: Dict[str, str]) -> Optional[Dict[str, Any]]:
    try:
        return {
            "device": row["device"],
            "model": row["model"],
            "fs": row["fs"],
            "qd": int(row["qd"]),
            "throughput_mb_s": float(row["throughput_mb_s"]),
            "latency_ms": float(row["latency_ms"]),
        }
    except Exception:
        return None


def compare_enriched_rows(expected: List[Dict[str, Any]], actual: List[Dict[str, Any]]) -> bool:
    if len(expected) != len(actual):
        return False
    for e, a in zip(expected, actual):
        if list(e.keys()) != list(a.keys()):
            return False
        if e["device"] != a["device"]:
            return False
        if e["model"] != a["model"]:
            return False
        if e["fs"] != a["fs"]:
            return False
        if int(e["qd"]) != int(a["qd"]):
            return False
        if not float_equal(float(e["throughput_mb_s"]), float(a["throughput_mb_s"])):
            return False
        if not float_equal(float(e["latency_ms"]), float(a["latency_ms"])):
            return False
    return True


def extract_failures_from_text(lines: List[str]) -> List[Tuple[str, str, int, str]]:
    results: List[Tuple[str, str, int, str]] = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        m = re.search(r"device\s*=\s*([A-Za-z0-9_-]+).*fs\s*=\s*([A-Za-z0-9_-]+).*qd\s*=\s*(\d+)\s*:\s*(.+)$", s)
        if m:
            d, fs, qd, msg = m.group(1), m.group(2), int(m.group(3)), m.group(4).strip()
            results.append((d, fs, qd, msg))
            continue
        m2 = re.match(r"^\s*([A-Za-z0-9_-]+)\s*,\s*([A-Za-z0-9_-]+)\s*,\s*(\d+)\s*,\s*(.+)$", s)
        if m2:
            d, fs, qd, msg = m2.group(1), m2.group(2), int(m2.group(3)), m2.group(4).strip()
            results.append((d, fs, qd, msg))
            continue
        m3 = re.match(r"^\s*device\s*[:=]\s*([A-Za-z0-9_-]+)\s+fs\s*[:=]\s*([A-Za-z0-9_-]+)\s+qd\s*[:=]\s*(\d+)\s*[-:]\s*(.+)$", s, flags=re.IGNORECASE)
        if m3:
            d, fs, qd, msg = m3.group(1), m3.group(2), int(m3.group(3)), m3.group(4).strip()
            results.append((d, fs, qd, msg))
            continue
        colon_idx = s.find(":")
        if colon_idx != -1:
            left = s[:colon_idx]
            right = s[colon_idx+1:].strip()
            d_match = re.search(r"(nvme\d+)", left)
            fs_match = re.search(r"\b(ext4|xfs)\b", left, flags=re.IGNORECASE)
            qd_match = re.search(r"\bqd\s*=?\s*(\d+)\b|\bqueue\s*depth\s*(\d+)\b", left, flags=re.IGNORECASE)
            if d_match and fs_match and qd_match:
                d = d_match.group(1)
                fs = fs_match.group(1).lower()
                qd = int(qd_match.group(1) or qd_match.group(2))
                results.append((d, fs, qd, right))
                continue
    return results


def get_email_subject_and_body(text: str) -> Tuple[Optional[str], str]:
    lines = text.splitlines()
    subject_line = None
    subject_idx = None
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("subject:"):
            subject_line = line.strip()[len("subject:"):].strip()
            subject_idx = i
            break
    if subject_line is None:
        for i, line in enumerate(lines):
            if line.strip():
                subject_line = line.strip()
                subject_idx = i
                break
    body = ""
    if subject_idx is not None:
        body_lines = lines[subject_idx+1:]
        body = "\n".join(body_lines).strip()
    else:
        body = text.strip()
    return subject_line, body


def safe_lower_contains(s: Optional[str], needle: str) -> bool:
    if s is None:
        return False
    return needle.lower() in s.lower()


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "inventory_json_extracted": 0.0,
        "metrics_enriched_csv_join_and_sort": 0.0,
        "top3_json_matches_expected": 0.0,
        "failures_txt_from_stderr": 0.0,
        "email_draft_subject_best_config": 0.0,
        "email_draft_body_top3_summary": 0.0,
        "email_draft_body_failure_count_and_causes": 0.0,
        "email_draft_recommendation_present": 0.0,
    }

    inv_html_path = workspace / "input" / "inventory.html"
    simulate_py_path = workspace / "tools" / "simulate_bench.py"

    expected_inventory = parse_inventory_html(inv_html_path) if inv_html_path.exists() else None
    metrics_map = parse_metrics_mapping_from_py(simulate_py_path) if simulate_py_path.exists() else None

    expected_success_records: List[Dict[str, Any]] = []
    expected_failures: List[Tuple[str, str, int, str]] = []
    if metrics_map is not None:
        for (d, fs, qd), val in metrics_map.items():
            if "error" in val:
                expected_failures.append((d, fs, qd, val["error"]))
            else:
                expected_success_records.append({
                    "device": d,
                    "fs": fs,
                    "qd": qd,
                    "throughput_mb_s": float(val["throughput_mb_s"]),
                    "latency_ms": float(val["latency_ms"]),
                })

    expected_enriched: List[Dict[str, Any]] = []
    if expected_inventory is not None and expected_success_records:
        model_by_device = {row["device"]: row["model"] for row in expected_inventory}
        for rec in expected_success_records:
            d = rec["device"]
            if d not in model_by_device:
                expected_enriched = []
                break
            enriched = {
                "device": d,
                "model": model_by_device[d],
                "fs": rec["fs"],
                "qd": rec["qd"],
                "throughput_mb_s": rec["throughput_mb_s"],
                "latency_ms": rec["latency_ms"],
            }
            expected_enriched.append(enriched)
        expected_enriched.sort(key=lambda r: (-float(r["throughput_mb_s"]), float(r["latency_ms"])))
    expected_top3 = expected_enriched[:3] if expected_enriched else []

    inv_json_path = workspace / "output" / "inventory.json"
    inv_json = load_json_file(inv_json_path) if inv_json_path.exists() else None
    if inv_json is not None and isinstance(inv_json, list) and expected_inventory is not None:
        def norm_inv_item(item: Any) -> Optional[Dict[str, Any]]:
            if not isinstance(item, dict):
                return None
            expected_keys = {"node", "device", "model", "capacity_tb"}
            if set(item.keys()) != expected_keys:
                return None
            try:
                node = str(item["node"])
                device = str(item["device"])
                model = str(item["model"])
                cap = float(item["capacity_tb"])
            except Exception:
                return None
            return {"node": node, "device": device, "model": model, "capacity_tb": cap}

        actual_norm = []
        bad = False
        for it in inv_json:
            n = norm_inv_item(it)
            if n is None:
                bad = True
                break
            actual_norm.append(n)
        if not bad:
            exp_sorted = sorted(expected_inventory, key=lambda r: r["device"])
            act_sorted = sorted(actual_norm, key=lambda r: r["device"])
            if len(exp_sorted) == len(act_sorted):
                ok = True
                for e, a in zip(exp_sorted, act_sorted):
                    if e["node"] != a["node"] or e["device"] != a["device"] or e["model"] != a["model"]:
                        ok = False
                        break
                    if not float_equal(float(e["capacity_tb"]), float(a["capacity_tb"])):
                        ok = False
                        break
                if ok:
                    scores["inventory_json_extracted"] = 1.0

    enriched_csv_path = workspace / "output" / "metrics_enriched.csv"
    header_rows = load_csv_dicts(enriched_csv_path) if enriched_csv_path.exists() else None
    if header_rows is not None and expected_enriched:
        header, rows = header_rows
        expected_header = ["device", "model", "fs", "qd", "throughput_mb_s", "latency_ms"]
        if header == expected_header:
            actual_norm_rows = []
            invalid = False
            for r in rows:
                nr = normalize_csv_row_types(r)
                if nr is None:
                    invalid = True
                    break
                actual_norm_rows.append(nr)
            if not invalid:
                if compare_enriched_rows(expected_enriched, actual_norm_rows):
                    scores["metrics_enriched_csv_join_and_sort"] = 1.0

    top3_path = workspace / "output" / "top3.json"
    top3_json = load_json_file(top3_path) if top3_path.exists() else None
    if top3_json is not None and isinstance(top3_json, list) and expected_top3:
        def norm_top_item(item: Any) -> Optional[Dict[str, Any]]:
            if not isinstance(item, dict):
                return None
            expected_keys = ["device", "model", "fs", "qd", "throughput_mb_s", "latency_ms"]
            if list(item.keys()) != expected_keys and set(item.keys()) != set(expected_keys):
                return None
            try:
                return {
                    "device": str(item["device"]),
                    "model": str(item["model"]),
                    "fs": str(item["fs"]),
                    "qd": int(item["qd"]),
                    "throughput_mb_s": float(item["throughput_mb_s"]),
                    "latency_ms": float(item["latency_ms"]),
                }
            except Exception:
                return None

        actual_top3 = []
        bad = False
        if len(top3_json) == 3:
            for it in top3_json:
                n = norm_top_item(it)
                if n is None:
                    bad = True
                    break
                actual_top3.append(n)
        else:
            bad = True
        if not bad:
            if compare_enriched_rows(expected_top3, actual_top3):
                scores["top3_json_matches_expected"] = 1.0

    failures_path = workspace / "output" / "failures.txt"
    fail_text = read_text(failures_path) if failures_path.exists() else None
    if fail_text is not None and expected_failures:
        parsed = extract_failures_from_text(fail_text.splitlines())
        expected_set = set(expected_failures)
        parsed_set = set(parsed)
        if parsed_set == expected_set and len(parsed) == len(expected_failures):
            scores["failures_txt_from_stderr"] = 1.0

    email_path = workspace / "output" / "email_draft.txt"
    email_text = read_text(email_path) if email_path.exists() else None

    best = expected_top3[0] if expected_top3 else None
    fail_count = len(expected_failures) if expected_failures is not None else None
    failure_messages = [msg for (_d, _fs, _qd, msg) in expected_failures] if expected_failures else []

    if email_text is not None and best is not None and fail_count is not None:
        subj, body = get_email_subject_and_body(email_text)
        subj_ok = False
        if subj:
            has_device = safe_lower_contains(subj, best["device"])
            has_model = safe_lower_contains(subj, best["model"])
            has_fs = safe_lower_contains(subj, best["fs"])
            has_qd_label = ("qd" in subj.lower()) or ("queue depth" in subj.lower())
            has_qd_num = str(best["qd"]) in subj
            thr_str_int = str(int(round(best["throughput_mb_s"])))
            thr_str_float = f"{best['throughput_mb_s']}"
            lat_str = f"{best['latency_ms']}".rstrip("0").rstrip(".") if isinstance(best["latency_ms"], float) else str(best["latency_ms"])
            has_thr = (thr_str_int in subj) or (thr_str_float in subj)
            has_lat = (lat_str in subj) or (str(best["latency_ms"]) in subj)
            subj_ok = has_device and has_model and has_fs and has_qd_num and has_lat and has_thr and has_qd_label
        if subj_ok and ("storage-lab@dept.edu".lower() in email_text.lower()):
            scores["email_draft_subject_best_config"] = 1.0

        body_ok = False
        if body:
            top3_present = True
            for rec in expected_top3:
                tokens_ok = all([
                    rec["device"].lower() in body.lower(),
                    rec["model"].lower() in body.lower(),
                    rec["fs"].lower() in body.lower(),
                    str(rec["qd"]) in body,
                ])
                thr_present = (str(int(round(rec["throughput_mb_s"]))) in body) or (str(rec["throughput_mb_s"]) in body)
                lat_val = rec["latency_ms"]
                lat_present = (str(lat_val) in body) or (f"{lat_val}".rstrip("0").rstrip(".") in body)
                if not (tokens_ok and thr_present and lat_present):
                    top3_present = False
                    break
            body_ok = top3_present
        if body_ok:
            scores["email_draft_body_top3_summary"] = 1.0

        fail_ok = False
        if body:
            has_fail_word = ("fail" in body.lower())
            has_count = re.search(rf"\b{fail_count}\b", body) is not None
            causes_ok = True
            for msg in failure_messages:
                key_sub = msg
                if "(" in msg:
                    key_sub = msg.split("(")[0].strip()
                if key_sub and key_sub.lower() not in body.lower():
                    causes_ok = False
                    break
            fail_ok = has_fail_word and has_count and causes_ok
        if fail_ok:
            scores["email_draft_body_failure_count_and_causes"] = 1.0

        rec_ok = False
        if body:
            rec_ok = any(tok in body.lower() for tok in ["re-run", "rerun", "retry", "investigate", "next step", "recommend"])
        if rec_ok:
            scores["email_draft_recommendation_present"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()