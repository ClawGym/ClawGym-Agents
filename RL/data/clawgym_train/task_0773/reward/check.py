import sys
import json
import csv
import math
import re
from pathlib import Path
from datetime import datetime
from html.parser import HTMLParser


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def safe_read_json(path: Path):
    try:
        text = safe_read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def safe_read_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            header = reader.fieldnames if hasattr(reader, "fieldnames") else None
        return rows, header
    except Exception:
        return None, None


def parse_inline_list(value: str):
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        parts = [p.strip() for p in inner.split(",")]
        parts = [strip_quotes(p) for p in parts if p]
        return parts
    return [strip_quotes(value)] if value else []


def strip_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def _get_top_level_blocks(text: str):
    lines = text.splitlines()
    indices = []
    for i, line in enumerate(lines):
        stripped = line.rstrip("\n")
        if re.match(r"^[A-Za-z0-9_]+:\s*$", stripped.strip()):
            key = stripped.strip()[:-1]
            indices.append((i, key))
        elif re.match(r"^[A-Za-z0-9_]+:\s*.+$", stripped.strip()):
            key = stripped.strip().split(":", 1)[0]
            indices.append((i, key))
    blocks = {}
    for idx, (start, key) in enumerate(indices):
        end = len(lines)
        if idx + 1 < len(indices):
            end = indices[idx + 1][0]
        blocks[key] = (start, end)
    return blocks, lines


def parse_pipeline_config(text: str) -> dict:
    cfg = {}
    blocks, lines = _get_top_level_blocks(text)

    m = re.search(r"^std_type:\s*(\S+)", text, flags=re.MULTILINE)
    if m:
        cfg["std_type"] = strip_quotes(m.group(1))

    m = re.search(r"^output_base:\s*(\S+)", text, flags=re.MULTILINE)
    if m:
        cfg["output_base"] = strip_quotes(m.group(1))

    group_by = []
    if "group_by" in blocks:
        start, end = blocks["group_by"]
        block = lines[start:end]
        m2 = re.match(r"^\s*group_by:\s*(\[.*\])\s*$", block[0])
        if m2:
            group_by = parse_inline_list(m2.group(1))
        else:
            for ln in block[1:]:
                if re.match(r"^\s*-\s+", ln):
                    item = re.sub(r"^\s*-\s+", "", ln).strip()
                    group_by.append(strip_quotes(item))
    cfg["group_by"] = group_by

    agg_fields = {}
    if "aggregate_fields" in blocks:
        start, end = blocks["aggregate_fields"]
        block = lines[start:end]
        for ln in block[1:]:
            ln_stripped = ln.strip()
            if not ln_stripped:
                continue
            m3 = re.match(r"^([A-Za-z0-9_]+)\s*:\s*(\[.*\])\s*$", ln_stripped)
            if m3:
                key = m3.group(1)
                vals = parse_inline_list(m3.group(2))
                agg_fields[key] = [v.lower() for v in vals]
    cfg["aggregate_fields"] = agg_fields

    external = {}
    if "external_license" in blocks:
        start, end = blocks["external_license"]
        block = lines[start:end]
        for ln in block[1:]:
            ln_stripped = ln.strip()
            if not ln_stripped:
                continue
            m4 = re.match(r"^([A-Za-z0-9_]+)\s*:\s*(.+)$", ln_stripped)
            if not m4:
                continue
            k = m4.group(1)
            v = m4.group(2).strip()
            if v.startswith("[") and v.endswith("]"):
                external[k] = parse_inline_list(v)
            else:
                external[k] = strip_quotes(v)
    cfg["external_license"] = external

    return cfg


def parse_numeric(val):
    if val is None:
        return None
    if isinstance(val, (int, float)):
        if isinstance(val, bool):
            return None
        return float(val)
    s = str(val).strip()
    if s == "":
        return None
    s = s.replace(",", "")
    try:
        return float(s)
    except Exception:
        return None


def normalize_key_scalar(val):
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        try:
            f = float(val)
            if math.isfinite(f):
                if abs(f - round(f)) < 1e-9:
                    return str(int(round(f)))
                return f"{f:.12g}"
        except Exception:
            return str(val)
    if val is None:
        return ""
    s = str(val).strip()
    try:
        f = float(s)
        if math.isfinite(f):
            if abs(f - round(f)) < 1e-9:
                return str(int(round(f)))
            return f"{f:.12g}"
    except Exception:
        pass
    return s


def compute_group_aggregates(rows, group_by, agg_fields, std_type="sample"):
    groups = {}
    for row in rows:
        key = tuple(normalize_key_scalar(row.get(g)) for g in group_by)
        groups.setdefault(key, {"__rows__": []})["__rows__"].append(row)

    result = {}
    for key, data in groups.items():
        rlist = data["__rows__"]
        out = {}
        out["row_count"] = len(rlist)
        for field, metrics in agg_fields.items():
            vals = []
            for r in rlist:
                v = parse_numeric(r.get(field))
                if v is not None and math.isfinite(v):
                    vals.append(v)
            for metric in metrics:
                metric_l = metric.lower()
                if metric_l == "mean":
                    val = (sum(vals) / len(vals)) if len(vals) > 0 else None
                elif metric_l == "std":
                    if len(vals) < 2:
                        val = None
                    else:
                        mean = sum(vals) / len(vals)
                        var = sum((x - mean) ** 2 for x in vals)
                        if std_type == "sample":
                            var /= (len(vals) - 1)
                        else:
                            var /= len(vals)
                        val = math.sqrt(var)
                elif metric_l == "min":
                    val = min(vals) if len(vals) > 0 else None
                elif metric_l == "max":
                    val = max(vals) if len(vals) > 0 else None
                else:
                    val = None
                out[(field, metric_l)] = val
        result[key] = out
    return result


def is_close(a, b, rel_tol=1e-3, abs_tol=1e-3):
    if a is None or b is None:
        return False
    try:
        return math.isclose(float(a), float(b), rel_tol=rel_tol, abs_tol=abs_tol)
    except Exception:
        return False


def detect_metric_columns(header, group_by, agg_fields):
    mapping = {}
    lower_header = [h.lower() for h in header]
    reserved = set([g.lower() for g in group_by] + ["row_count"])
    for field, metrics in agg_fields.items():
        for metric in metrics:
            metric_l = metric.lower()
            candidates = []
            for h, hl in zip(header, lower_header):
                if hl in reserved:
                    continue
                if field.lower() in hl and metric_l in hl:
                    candidates.append(h)
            if len(candidates) == 1:
                mapping[(field, metric_l)] = candidates[0]
            else:
                return None
    return mapping


class SimpleHTMLTitleHeadingsParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_title = False
        self.title = ""
        self.current_tag = None
        self.headings = []
        self._buffer = ""

    def handle_starttag(self, tag, attrs):
        tag_l = tag.lower()
        if tag_l == "title":
            self.in_title = True
            self._buffer = ""
        if tag_l in ("h1", "h2"):
            self.current_tag = tag_l
            self._buffer = ""

    def handle_endtag(self, tag):
        tag_l = tag.lower()
        if tag_l == "title" and self.in_title:
            self.in_title = False
            text = self._buffer.strip()
            self.title += text
            self._buffer = ""
        if tag_l in ("h1", "h2") and self.current_tag == tag_l:
            text = self._buffer.strip()
            if text:
                self.headings.append(text)
            self.current_tag = None
            self._buffer = ""

    def handle_data(self, data):
        if self.in_title or self.current_tag in ("h1", "h2"):
            self._buffer += data


def normalize_whitespace(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def validate_iso8601_utc(ts: str) -> bool:
    if not isinstance(ts, str):
        return False
    s = ts.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        datetime.fromisoformat(s)
        return True
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "run_script_exists_executable": 0.0,
        "run_log_exists": 0.0,
        "aggregates_csv_present": 0.0,
        "aggregates_json_present": 0.0,
        "external_html_present": 0.0,
        "external_metadata_present": 0.0,
        "aggregates_csv_correct": 0.0,
        "aggregates_json_correct": 0.0,
        "csv_json_groups_match": 0.0,
        "external_metadata_matches_html_and_config": 0.0,
    }

    config_path = workspace / "config" / "pipeline.yml"
    input_csv_path = workspace / "input" / "data" / "reactions.csv"
    run_script_path = workspace / "ci" / "run_pipeline.sh"
    run_log_path = workspace / "ci" / "run.log"
    agg_csv_path = workspace / "output" / "summary" / "aggregates.csv"
    agg_json_path = workspace / "output" / "summary" / "aggregates.json"
    html_path = workspace / "output" / "external" / "cc-by-4.0-legalcode.html"
    metadata_path = workspace / "output" / "external" / "cc-by-4.0-metadata.json"

    try:
        if run_script_path.exists() and run_script_path.is_file() and (run_script_path.stat().st_mode & 0o111):
            scores["run_script_exists_executable"] = 1.0
    except Exception:
        pass

    try:
        if run_log_path.exists() and run_log_path.is_file():
            content = safe_read_text(run_log_path)
            if content is not None and len(content.strip()) > 0:
                scores["run_log_exists"] = 1.0
    except Exception:
        pass

    if agg_csv_path.exists() and agg_csv_path.is_file():
        scores["aggregates_csv_present"] = 1.0
    if agg_json_path.exists() and agg_json_path.is_file():
        scores["aggregates_json_present"] = 1.0
    if html_path.exists() and html_path.is_file():
        scores["external_html_present"] = 1.0
    if metadata_path.exists() and metadata_path.is_file():
        scores["external_metadata_present"] = 1.0

    cfg_text = safe_read_text(config_path) if config_path.exists() else None
    cfg = parse_pipeline_config(cfg_text) if cfg_text else None

    expected = None
    if cfg and input_csv_path.exists():
        input_rows, _ = safe_read_csv_dicts(input_csv_path)
        if input_rows is not None:
            group_by = cfg.get("group_by", [])
            agg_fields = cfg.get("aggregate_fields", {})
            std_type = cfg.get("std_type", "sample")
            try:
                expected = compute_group_aggregates(input_rows, group_by, agg_fields, std_type=std_type)
            except Exception:
                expected = None

    csv_ok = False
    if expected is not None and agg_csv_path.exists():
        rows, header = safe_read_csv_dicts(agg_csv_path)
        if rows is not None and header:
            group_by = cfg.get("group_by", []) if cfg else []
            has_group_cols = all(g in header for g in group_by)
            has_row_count_col = any(h.lower() == "row_count" for h in header)
            if has_group_cols and has_row_count_col:
                mapping = detect_metric_columns(header, group_by, cfg.get("aggregate_fields", {}))
                if mapping is not None:
                    obs = {}
                    for r in rows:
                        key = tuple(normalize_key_scalar(r.get(g)) for g in group_by)
                        obs[key] = r
                    if set(obs.keys()) == set(expected.keys()):
                        all_values_ok = True
                        for key in expected.keys():
                            exp_vals = expected[key]
                            row = obs.get(key)
                            if row is None:
                                all_values_ok = False
                                break
                            rc = row.get("row_count")
                            try:
                                rc_val = int(float(str(rc)))
                            except Exception:
                                rc_val = None
                            if rc_val != exp_vals.get("row_count"):
                                all_values_ok = False
                                break
                            # check each metric using mapping
                            for (field, metric_l), col in mapping.items():
                                exp = exp_vals.get((field, metric_l))
                                obs_val = parse_numeric(row.get(col))
                                if not is_close(obs_val, exp):
                                    all_values_ok = False
                                    break
                            if not all_values_ok:
                                break
                        if all_values_ok:
                            csv_ok = True
    scores["aggregates_csv_correct"] = 1.0 if csv_ok else 0.0

    json_ok = False
    json_groups = {}
    if expected is not None and agg_json_path.exists():
        data = safe_read_json(agg_json_path)
        if isinstance(data, list):
            group_by = cfg.get("group_by", []) if cfg else []
            mapping_json = {}
            if len(data) > 0 and isinstance(data[0], dict):
                obj0 = data[0]
                if all(g in obj0 for g in group_by) and ("row_count" in obj0):
                    header_like = list(obj0.keys())
                    mapping_json = detect_metric_columns(header_like, group_by, cfg.get("aggregate_fields", {}))
            if mapping_json:
                for obj in data:
                    if not isinstance(obj, dict):
                        mapping_json = None
                        break
                    if not all(g in obj for g in group_by) or "row_count" not in obj:
                        mapping_json = None
                        break
                    key = tuple(normalize_key_scalar(obj.get(g)) for g in group_by)
                    json_groups[key] = obj
            if mapping_json:
                if set(json_groups.keys()) == set(expected.keys()):
                    all_values_ok = True
                    for key in expected.keys():
                        exp_vals = expected[key]
                        obj = json_groups.get(key)
                        if obj is None:
                            all_values_ok = False
                            break
                        rc_val = obj.get("row_count")
                        try:
                            rc_val_int = int(rc_val)
                        except Exception:
                            try:
                                rc_val_int = int(float(rc_val))
                            except Exception:
                                rc_val_int = None
                        if rc_val_int != exp_vals.get("row_count"):
                            all_values_ok = False
                            break
                        for (field, metric_l), col in mapping_json.items():
                            exp = exp_vals.get((field, metric_l))
                            obs_val = parse_numeric(obj.get(col))
                            if not is_close(obs_val, exp):
                                all_values_ok = False
                                break
                        if not all_values_ok:
                            break
                    if all_values_ok:
                        json_ok = True
    scores["aggregates_json_correct"] = 1.0 if json_ok else 0.0

    csv_json_ok = False
    if csv_ok and json_ok:
        rows_csv, header_csv = safe_read_csv_dicts(agg_csv_path)
        group_by = cfg.get("group_by", []) if cfg else []
        csv_map = {}
        if rows_csv is not None and header_csv:
            for r in rows_csv:
                key = tuple(normalize_key_scalar(r.get(g)) for g in group_by)
                try:
                    rc = int(float(str(r.get("row_count"))))
                except Exception:
                    rc = None
                csv_map[key] = rc
        json_map = {}
        data_json = safe_read_json(agg_json_path)
        if isinstance(data_json, list):
            for obj in data_json:
                if isinstance(obj, dict) and all(g in obj for g in group_by):
                    key = tuple(normalize_key_scalar(obj.get(g)) for g in group_by)
                    try:
                        rc = int(obj.get("row_count"))
                    except Exception:
                        try:
                            rc = int(float(obj.get("row_count")))
                        except Exception:
                            rc = None
                    json_map[key] = rc
        if set(csv_map.keys()) == set(json_map.keys()) and all(csv_map[k] == json_map[k] for k in csv_map.keys()):
            csv_json_ok = True
    scores["csv_json_groups_match"] = 1.0 if csv_json_ok else 0.0

    meta_ok = False
    if metadata_path.exists() and html_path.exists() and cfg:
        meta = safe_read_json(metadata_path)
        html_text = safe_read_text(html_path)
        if isinstance(meta, dict) and isinstance(html_text, str) and len(html_text.strip()) > 0:
            parser = SimpleHTMLTitleHeadingsParser()
            try:
                parser.feed(html_text)
            except Exception:
                pass
            page_title = normalize_whitespace(parser.title)
            headings = [normalize_whitespace(h) for h in parser.headings]

            license_name_cfg = cfg.get("external_license", {}).get("name")
            site_cfg = cfg.get("external_license", {}).get("site")
            path_hint_cfg = cfg.get("external_license", {}).get("path_hint")

            license_name_ok = (meta.get("license_name") == license_name_cfg) if license_name_cfg else False
            source_description = meta.get("source_description", "")
            source_ok = isinstance(source_description, str) and (site_cfg in source_description if site_cfg else False) and (path_hint_cfg in source_description if path_hint_cfg else False)
            retrieved_ok = validate_iso8601_utc(meta.get("retrieved_at"))
            page_title_meta = normalize_whitespace(meta.get("page_title", "")) if isinstance(meta.get("page_title"), str) else ""
            title_ok = (page_title_meta == page_title) if page_title else False
            headings_meta = meta.get("headings")
            if isinstance(headings_meta, list):
                headings_meta_norm = [normalize_whitespace(str(h)) for h in headings_meta]
            else:
                headings_meta_norm = []
            headings_ok = (headings_meta_norm == headings)
            html_basic_ok = "<html" in html_text.lower()

            if all([license_name_ok, source_ok, retrieved_ok, title_ok, headings_ok, html_basic_ok]):
                meta_ok = True
    scores["external_metadata_matches_html_and_config"] = 1.0 if meta_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()