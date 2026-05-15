import csv
import json
import math
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import py_compile


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [row for row in reader]
    except Exception:
        return None


def _read_csv_header(path: Path) -> Optional[List[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            row = next(reader, None)
            if row is None:
                return []
            return row
    except Exception:
        return None


def _parse_float(s: Any) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _parse_int(s: Any) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        return None


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
        return s[1:-1]
    return s


def _parse_simple_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML parser for simple key: value pairs with scalars.
    Supports:
      - strings (quoted or unquoted)
      - booleans: true/false
      - numbers (int/float)
    """
    text = _read_text(path)
    if text is None:
        return None
    data: Dict[str, Any] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        if not key:
            continue
        # Remove comments after value
        if "#" in val:
            val = val.split("#", 1)[0].strip()
        # Parse scalars
        sval = _strip_quotes(val)
        lval = sval.lower()
        if lval in ("true", "false"):
            data[key] = (lval == "true")
        else:
            # Try int, then float, else string
            ival = _parse_int(sval)
            if ival is not None:
                data[key] = ival
            else:
                fval = _parse_float(sval)
                if fval is not None:
                    data[key] = fval
                else:
                    data[key] = sval
    return data


class _CatalogHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_table = False
        self.table_id = None
        self.in_thead = False
        self.in_tbody = False
        self.in_tr = False
        self.in_td = False
        self.current_cell_data = ""
        self.current_row: List[str] = []
        self.headers: List[str] = []
        self.rows: List[List[str]] = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "table" and attrs_dict.get("id") == "catalog":
            self.in_table = True
            self.table_id = attrs_dict.get("id")
        elif self.in_table and tag == "thead":
            self.in_thead = True
        elif self.in_table and tag == "tbody":
            self.in_tbody = True
        elif self.in_table and tag == "tr":
            self.in_tr = True
            self.current_row = []
        elif self.in_table and self.in_tr and tag in ("th", "td"):
            self.in_td = True
            self.current_cell_data = ""

    def handle_endtag(self, tag):
        if tag == "table" and self.in_table:
            self.in_table = False
            self.table_id = None
        elif self.in_table and tag == "thead":
            self.in_thead = False
        elif self.in_table and tag == "tbody":
            self.in_tbody = False
        elif self.in_table and tag == "tr" and self.in_tr:
            if self.in_thead and self.current_row:
                self.headers = [cell.strip() for cell in self.current_row]
            elif self.in_tbody and self.current_row:
                self.rows.append([cell.strip() for cell in self.current_row])
            self.in_tr = False
            self.current_row = []
        elif self.in_table and self.in_tr and tag in ("th", "td"):
            if self.in_td:
                self.current_row.append(self.current_cell_data.strip())
            self.in_td = False
            self.current_cell_data = ""

    def handle_data(self, data):
        if self.in_table and self.in_tr and self.in_td:
            self.current_cell_data += data


def _parse_catalog_html(path: Path) -> Optional[List[Dict[str, Any]]]:
    """
    Returns list of dicts extracted from HTML with keys exactly matching:
    Product, Vendor, Effect Class, Peak dB (5m), Cost (USD), Safety Score, Indoor OK, Training Required
    """
    text = _read_text(path)
    if text is None:
        return None
    parser = _CatalogHTMLParser()
    try:
        parser.feed(text)
    except Exception:
        return None
    if not parser.headers or not parser.rows:
        return None
    # Build mapping
    rows = []
    for r in parser.rows:
        if len(r) != len(parser.headers):
            # malformed row
            return None
        row = {parser.headers[i]: r[i] for i in range(len(parser.headers))}
        rows.append(row)
    return rows


def _normalize_catalog_rows_from_html(html_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Normalize to expected catalog_extracted.csv schema:
    product_name,vendor,effect_class,decibels,cost_usd,safety_score,indoor_ok,training_required
    """
    normalized: List[Dict[str, Any]] = []
    for row in html_rows:
        product = row.get("Product", "").strip()
        vendor = row.get("Vendor", "").strip()
        effect_class = row.get("Effect Class", "").strip().lower()
        decibels = _parse_float(row.get("Peak dB (5m)", "").strip())
        cost = _parse_float(row.get("Cost (USD)", "").strip())
        safety = _parse_float(row.get("Safety Score", "").strip())
        indoor_ok_raw = row.get("Indoor OK", "").strip().lower()
        training_raw = row.get("Training Required", "").strip().lower()
        indoor_ok = "true" if indoor_ok_raw in ("yes", "true") else "false"
        training_required = "true" if training_raw in ("yes", "true") else "false"
        normalized.append({
            "product_name": product,
            "vendor": vendor,
            "effect_class": effect_class,
            "decibels": decibels,
            "cost_usd": cost,
            "safety_score": safety,
            "indoor_ok": indoor_ok,
            "training_required": training_required,
        })
    return normalized


def _effect_class_order(value: str) -> Optional[int]:
    order = {"small": 0, "medium": 1, "large": 2}
    return order.get(value.strip().lower()) if isinstance(value, str) else None


def _aggregate_incidents(path: Path) -> Optional[Dict[str, Dict[str, float]]]:
    """
    Returns mapping product_name -> {"incidents_count": int, "incidents_severity_total": float}
    """
    rows = _read_csv_dicts(path)
    if rows is None:
        return None
    agg: Dict[str, Dict[str, float]] = {}
    required_cols = {"product_name", "severity"}
    if rows:
        if set(rows[0].keys()) - set(rows[0].keys()) != set():
            pass
    for row in rows:
        if any(col not in row for col in required_cols):
            return None
        name = row["product_name"].strip()
        sev = _parse_float(row["severity"])
        if sev is None:
            return None
        if name not in agg:
            agg[name] = {"incidents_count": 0.0, "incidents_severity_total": 0.0}
        agg[name]["incidents_count"] += 1.0
        agg[name]["incidents_severity_total"] += sev
    return agg


def _safe_lower(s: Any) -> str:
    try:
        return str(s).lower()
    except Exception:
        return ""


def _float_equal(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_present_compiles": 0.0,
        "catalog_extracted_exists_and_schema": 0.0,
        "catalog_extracted_content_matches_html": 0.0,
        "filtered_ranked_exists_and_schema": 0.0,
        "filtered_ranked_correct_filtering": 0.0,
        "filtered_ranked_ranking_correct": 0.0,
        "meeting_notes_constraints_and_counts": 0.0,
        "meeting_notes_top3_justifications": 0.0,
        "meeting_notes_risks_and_mitigations": 0.0,
        "meeting_notes_action_items": 0.0,
    }

    # Check script presence and compiles without executing it
    script_path = workspace / "scripts" / "select_effects.py"
    if script_path.exists() and script_path.is_file():
        try:
            py_compile.compile(str(script_path), doraise=True)
            scores["script_present_compiles"] = 1.0
        except Exception:
            scores["script_present_compiles"] = 0.0

    # Parse input HTML and build expected normalized rows
    input_html_path = workspace / "input" / "vendor_catalog.html"
    html_rows = _parse_catalog_html(input_html_path) if input_html_path.exists() else None
    expected_norm_rows: List[Dict[str, Any]] = []
    if html_rows is not None:
        expected_norm_rows = _normalize_catalog_rows_from_html(html_rows)

    # Check outputs/catalog_extracted.csv
    extracted_path = workspace / "outputs" / "catalog_extracted.csv"
    expected_header = [
        "product_name",
        "vendor",
        "effect_class",
        "decibels",
        "cost_usd",
        "safety_score",
        "indoor_ok",
        "training_required",
    ]
    if extracted_path.exists() and extracted_path.is_file():
        header = _read_csv_header(extracted_path)
        if header is not None and header == expected_header:
            # Schema OK
            rows = _read_csv_dicts(extracted_path)
            if rows is not None:
                # Validate types and values
                all_types_ok = True
                all_effect_classes_valid = True
                all_booleans_valid = True
                for row in rows:
                    # Check headers present
                    if any(col not in row for col in expected_header):
                        all_types_ok = False
                        break
                    # Numeric coercion
                    d = _parse_float(row["decibels"])
                    c = _parse_float(row["cost_usd"])
                    s = _parse_float(row["safety_score"])
                    if d is None or c is None or s is None:
                        all_types_ok = False
                        break
                    # Effect class value valid
                    if _effect_class_order(row["effect_class"]) is None:
                        all_effect_classes_valid = False
                        break
                    # Booleans exactly true/false
                    indoor_ok_val = _safe_lower(row["indoor_ok"])
                    training_val = _safe_lower(row["training_required"])
                    if indoor_ok_val not in ("true", "false") or training_val not in ("true", "false"):
                        all_booleans_valid = False
                        break
                if all_types_ok and all_effect_classes_valid and all_booleans_valid:
                    scores["catalog_extracted_exists_and_schema"] = 1.0

                # Compare content to HTML if available
                if expected_norm_rows:
                    # Build maps by product_name
                    actual_by_name: Dict[str, Dict[str, Any]] = {}
                    for r in rows:
                        actual_by_name[r["product_name"]] = r
                    expected_by_name: Dict[str, Dict[str, Any]] = {}
                    for r in expected_norm_rows:
                        expected_by_name[str(r["product_name"])] = r
                    # Must have same product set
                    if set(actual_by_name.keys()) == set(expected_by_name.keys()) and len(rows) == len(expected_norm_rows):
                        content_ok = True
                        for name, exp in expected_by_name.items():
                            act = actual_by_name.get(name)
                            if act is None:
                                content_ok = False
                                break
                            # Compare vendor and effect_class exactly
                            if str(act["vendor"]).strip() != str(exp["vendor"]).strip():
                                content_ok = False
                                break
                            if str(act["effect_class"]).strip().lower() != str(exp["effect_class"]).strip().lower():
                                content_ok = False
                                break
                            # Compare numeric decibels, cost_usd, safety_score
                            ad = _parse_float(act["decibels"])
                            ac = _parse_float(act["cost_usd"])
                            asf = _parse_float(act["safety_score"])
                            if ad is None or ac is None or asf is None:
                                content_ok = False
                                break
                            if not (_float_equal(ad, float(exp["decibels"])) and
                                    _float_equal(ac, float(exp["cost_usd"])) and
                                    _float_equal(asf, float(exp["safety_score"]))):
                                content_ok = False
                                break
                            # Compare booleans exactly "true"/"false"
                            if _safe_lower(act["indoor_ok"]) != exp["indoor_ok"]:
                                content_ok = False
                                break
                            if _safe_lower(act["training_required"]) != exp["training_required"]:
                                content_ok = False
                                break
                        if content_ok:
                            scores["catalog_extracted_content_matches_html"] = 1.0

    # Compute expected filtered and ranked results
    incidents_path = workspace / "input" / "safety_incidents.csv"
    yaml_path = workspace / "input" / "shoot_requirements.yaml"
    incidents_agg = _aggregate_incidents(incidents_path) if incidents_path.exists() else None
    constraints = _parse_simple_yaml(yaml_path) if yaml_path.exists() else None

    expected_filtered_ranked: List[Dict[str, Any]] = []
    if expected_norm_rows and incidents_agg is not None and constraints is not None:
        indoor = bool(constraints.get("indoor", False))
        max_decibels = constraints.get("max_decibels", None)
        budget_per_unit_usd = constraints.get("budget_per_unit_usd", None)
        min_effect_class = constraints.get("min_effect_class", None)
        team_has_training = bool(constraints.get("team_has_training", True))

        # Validate required constraint fields exist
        if max_decibels is not None and budget_per_unit_usd is not None and min_effect_class is not None:
            min_class_ord = _effect_class_order(str(min_effect_class))
            if min_class_ord is not None:
                # Apply filters
                filtered: List[Dict[str, Any]] = []
                for r in expected_norm_rows:
                    # a copy to avoid mutation
                    rr = dict(r)
                    if indoor and rr["indoor_ok"] != "true":
                        continue
                    if rr["decibels"] is None or rr["cost_usd"] is None:
                        continue
                    if float(rr["decibels"]) > float(max_decibels):
                        continue
                    if float(rr["cost_usd"]) > float(budget_per_unit_usd):
                        continue
                    if _effect_class_order(rr["effect_class"]) is None or _effect_class_order(rr["effect_class"]) < min_class_ord:
                        continue
                    if not team_has_training and rr["training_required"] == "true":
                        continue
                    filtered.append(rr)
                # Join incidents and compute adjusted safety score
                enriched: List[Dict[str, Any]] = []
                for rr in filtered:
                    name = str(rr["product_name"])
                    inc = incidents_agg.get(name, {"incidents_count": 0.0, "incidents_severity_total": 0.0})
                    incidents_count = int(inc.get("incidents_count", 0.0))
                    incidents_severity_total = float(inc.get("incidents_severity_total", 0.0))
                    safety_score = float(rr["safety_score"])
                    adjusted = safety_score - 0.5 * incidents_severity_total
                    if adjusted < 0:
                        adjusted = 0.0
                    enriched.append({
                        "product_name": name,
                        "vendor": rr["vendor"],
                        "effect_class": rr["effect_class"],
                        "decibels": float(rr["decibels"]),
                        "cost_usd": float(rr["cost_usd"]),
                        "safety_score": safety_score,
                        "incidents_count": incidents_count,
                        "incidents_severity_total": incidents_severity_total,
                        "adjusted_safety_score": adjusted,
                    })
                # Rank: adjusted desc, cost asc, decibels asc
                enriched.sort(key=lambda x: (-x["adjusted_safety_score"], x["cost_usd"], x["decibels"]))
                # Assign rank starting at 1
                for idx, item in enumerate(enriched, start=1):
                    item["rank"] = idx
                expected_filtered_ranked = enriched

    # Check outputs/filtered_ranked.csv
    filtered_ranked_path = workspace / "outputs" / "filtered_ranked.csv"
    required_filtered_cols = [
        "rank",
        "product_name",
        "vendor",
        "effect_class",
        "decibels",
        "cost_usd",
        "safety_score",
        "incidents_count",
        "incidents_severity_total",
        "adjusted_safety_score",
    ]
    filtered_rows: Optional[List[Dict[str, str]]] = None
    if filtered_ranked_path.exists() and filtered_ranked_path.is_file():
        rows = _read_csv_dicts(filtered_ranked_path)
        if rows is not None and len(rows) >= 0:
            # Check column presence (at least these columns)
            if rows:
                cols = list(rows[0].keys())
            else:
                # Read header if empty file
                hdr = _read_csv_header(filtered_ranked_path) or []
                cols = hdr
            if all(col in cols for col in required_filtered_cols):
                scores["filtered_ranked_exists_and_schema"] = 1.0
                filtered_rows = rows

    # Validate filtering correctness and ranking
    if filtered_rows is not None and expected_filtered_ranked:
        # Build actual map and list
        actual_products = [r["product_name"] for r in filtered_rows if "product_name" in r]
        expected_products = [r["product_name"] for r in expected_filtered_ranked]
        if set(actual_products) == set(expected_products) and len(actual_products) == len(expected_products):
            scores["filtered_ranked_correct_filtering"] = 1.0

        # Ranking check: order and computed fields
        # Build actual rows indexed by rank (ensure ranks are unique and numeric)
        try:
            actual_sorted = sorted(filtered_rows, key=lambda r: int(r["rank"]))
            rank_sequence_ok = all(int(r["rank"]) == i + 1 for i, r in enumerate(actual_sorted))
        except Exception:
            rank_sequence_ok = False
            actual_sorted = filtered_rows

        ranking_ok = rank_sequence_ok
        if ranking_ok:
            # Compare product order and computed fields for each
            for exp, act in zip(expected_filtered_ranked, actual_sorted):
                if act.get("product_name") != exp["product_name"]:
                    ranking_ok = False
                    break
                # Numeric comparisons
                for key in ["decibels", "cost_usd", "safety_score", "incidents_count", "incidents_severity_total", "adjusted_safety_score"]:
                    act_val_raw = act.get(key)
                    if act_val_raw is None:
                        ranking_ok = False
                        break
                    # incidents_count may be int but stored as string
                    if key == "incidents_count":
                        act_val = _parse_int(act_val_raw)
                        exp_val = int(exp[key])
                        if act_val is None or act_val != exp_val:
                            ranking_ok = False
                            break
                    else:
                        act_val_f = _parse_float(act_val_raw)
                        exp_val_f = float(exp[key])
                        if act_val_f is None or not _float_equal(act_val_f, exp_val_f):
                            ranking_ok = False
                            break
                if not ranking_ok:
                    break
        if ranking_ok:
            scores["filtered_ranked_ranking_correct"] = 1.0

    # Meeting notes checks
    meeting_notes_path = workspace / "outputs" / "meeting_notes.md"
    notes_text = _read_text(meeting_notes_path) if meeting_notes_path.exists() else None
    if notes_text is not None:
        lower_notes = notes_text.lower()

        # Constraints and counts
        constraints_ok = False
        counts_ok = False
        if constraints is not None:
            constraint_keys = ["indoor", "max_decibels", "budget_per_unit_usd", "min_effect_class", "team_has_training"]
            # All keys mentioned
            keys_present = all(k.lower() in lower_notes for k in constraint_keys)
            # Values present (string forms)
            values_present = True
            for k in constraint_keys:
                v = constraints.get(k)
                if isinstance(v, bool):
                    if ("true" if v else "false") not in lower_notes:
                        values_present = False
                        break
                else:
                    v_str = str(v).strip('"').strip("'")
                    if v_str.lower() not in lower_notes:
                        # For numbers, allow presence in any context
                        values_present = False
                        break
            constraints_ok = keys_present and values_present

            # Counts: filtered out vs considered
            total_items = len(expected_norm_rows) if expected_norm_rows else None
            considered_items = len(expected_filtered_ranked) if expected_filtered_ranked else None
            if total_items is not None and considered_items is not None:
                filtered_out = total_items - considered_items
                # Check words and numbers presence
                has_filtered_word = "filter" in lower_notes  # matches 'filtered'/'filtering'
                has_considered_word = "consider" in lower_notes
                has_counts = (str(filtered_out) in notes_text) and (str(considered_items) in notes_text)
                counts_ok = has_filtered_word and has_considered_word and has_counts

        if constraints_ok and counts_ok:
            scores["meeting_notes_constraints_and_counts"] = 1.0

        # Top 3 justifications
        top3_ok = False
        if expected_filtered_ranked:
            # We expect at least 3, but if fewer, still verify available ones
            top_n = min(3, len(expected_filtered_ranked))
            expected_top = expected_filtered_ranked[:top_n]
            # Build lines
            lines = [ln.strip() for ln in notes_text.splitlines() if ln.strip()]
            product_line_checks = 0
            for exp in expected_top:
                pname = exp["product_name"]
                vendor = exp["vendor"]
                cost_int = int(exp["cost_usd"]) if float(exp["cost_usb"] if "cost_usb" in exp else exp["cost_usd"]).is_integer() else None  # Safe int check
                # safe cost string options
                cost_strs = {str(exp["cost_usd"])}
                if float(exp["cost_usd"]).is_integer():
                    cost_strs.add(str(int(exp["cost_usd"])))
                decibels_strs = {str(exp["decibels"])}
                if float(exp["decibels"]).is_integer():
                    decibels_strs.add(str(int(exp["decibels"])))
                adj_strs = {str(exp["adjusted_safety_score"])}
                if float(exp["adjusted_safety_score"]).is_integer():
                    adj_strs.add(str(int(exp["adjusted_safety_score"])))
                # Find a line containing product name and other fields
                found_line = False
                for line in lines:
                    if pname in line:
                        # require vendor and numbers in same line
                        has_vendor = vendor in line
                        has_cost = any(cs in line for cs in cost_strs)
                        has_db = any(ds in line for ds in decibels_strs)
                        has_adj = any(asr in line for asr in adj_strs)
                        if has_vendor and has_cost and has_db and has_adj:
                            found_line = True
                            break
                if found_line:
                    product_line_checks += 1
            top3_ok = (product_line_checks == top_n)
        if top3_ok:
            scores["meeting_notes_top3_justifications"] = 1.0

        # Risks and mitigations: at least two bullet notes tied to incident history or decibel limits
        bullets = [ln.strip() for ln in notes_text.splitlines() if ln.strip().startswith(("-", "*"))]
        risk_keywords = ("incident", "severity", "decibel", "db")
        risk_bullets = [b for b in bullets if any(k in b.lower() for k in risk_keywords)]
        if len(risk_bullets) >= 2:
            scores["meeting_notes_risks_and_mitigations"] = 1.0

        # Action items: at least four items, each assigned to an owner and a clear next step
        owner_keywords = ("sfx", "pyro", "producer", "props", "coordinator", "supervisor", "lead")
        action_verbs = ("request", "place", "test", "confirm", "review", "schedule", "procure", "verify", "prepare", "update")
        action_bullets = []
        for b in bullets:
            bl = b.lower()
            has_owner = any(ok in bl for ok in owner_keywords)
            has_action = any(av in bl for av in action_verbs)
            has_assignment_sep = (":" in b) or (" - " in b) or ("—" in b)
            if has_owner and has_action and has_assignment_sep:
                action_bullets.append(b)
        if len(action_bullets) >= 4:
            scores["meeting_notes_action_items"] = 1.0

    return {k: float(v) for k, v in scores.items()}


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()