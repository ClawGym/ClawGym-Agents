import json
import math
import sys
import csv
from pathlib import Path
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple, Any


def safe_read_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        if not path.exists():
            return None
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            if reader.fieldnames is None:
                return None
            return rows
    except Exception:
        return None


def safe_read_json(path: Path) -> Optional[Any]:
    try:
        if not path.exists():
            return None
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def parse_preferences_yaml(path: Path) -> Optional[Dict[str, Any]]:
    try:
        if not path.exists():
            return None
        with path.open(encoding="utf-8") as f:
            lines = f.readlines()
        prefs: Dict[str, Any] = {}
        state = None  # None | 'list' | 'weights'
        list_accum: Optional[List[str]] = None
        weights_map: Optional[Dict[str, float]] = None
        for raw in lines:
            line = raw.split("#", 1)[0].rstrip("\n")
            if not line.strip():
                continue
            if not line.startswith(" "):  # top-level
                state = None
                if ":" in line:
                    key, val = line.split(":", 1)
                    key = key.strip()
                    val = val.strip()
                    if val == "":
                        if key == "must_have_certifications":
                            list_accum = []
                            prefs[key] = list_accum
                            state = "list"
                        elif key == "weights":
                            weights_map = {}
                            prefs[key] = weights_map
                            state = "weights"
                        else:
                            prefs[key] = {}
                            state = None
                    else:
                        if key in ("preferred_zip", "max_distance_miles", "max_budget", "min_years_experience"):
                            try:
                                prefs[key] = int(val)
                            except ValueError:
                                try:
                                    prefs[key] = float(val)
                                except ValueError:
                                    prefs[key] = val
                        else:
                            try:
                                if "." in val:
                                    prefs[key] = float(val)
                                else:
                                    prefs[key] = int(val)
                            except ValueError:
                                prefs[key] = val
            else:
                stripped = line.strip()
                if state == "list":
                    if stripped.startswith("- "):
                        item = stripped[2:].strip()
                        if list_accum is not None:
                            list_accum.append(item)
                elif state == "weights":
                    if ":" in stripped:
                        k2, v2 = stripped.split(":", 1)
                        k2 = k2.strip()
                        v2 = v2.strip()
                        try:
                            weights_val = float(v2)
                        except ValueError:
                            try:
                                weights_val = float(int(v2))
                            except Exception:
                                return None
                        if weights_map is not None:
                            weights_map[k2] = float(weights_val)
        required_keys = ["preferred_zip", "max_distance_miles", "max_budget", "min_years_experience", "must_have_certifications", "weights"]
        for rk in required_keys:
            if rk not in prefs:
                return None
        if not isinstance(prefs["must_have_certifications"], list):
            return None
        if not isinstance(prefs["weights"], dict):
            return None
        return prefs
    except Exception:
        return None


class ProfilesHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_license = False
        self.in_certs_ul = False
        self.in_li = False
        self.current: Optional[Dict[str, Any]] = None
        self.results: Dict[str, Dict[str, Any]] = {}

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag.lower() == "div":
            cls = attrs_dict.get("class", "")
            if "inspector" in cls.split():
                self.current = {"inspector_id": attrs_dict.get("data-id"), "license": None, "certs": []}
        elif self.current is not None:
            if tag.lower() == "span":
                cls = attrs_dict.get("class", "")
                if "license" in cls.split():
                    self.in_license = True
            elif tag.lower() == "ul":
                cls = attrs_dict.get("class", "")
                if "certs" in cls.split():
                    self.in_certs_ul = True
            elif tag.lower() == "li" and self.in_certs_ul:
                self.in_li = True

    def handle_endtag(self, tag):
        if self.current is not None:
            if tag.lower() == "div":
                ins_id = self.current.get("inspector_id")
                if ins_id:
                    self.results[ins_id] = {"license": self.current.get("license"), "certifications": self.current.get("certs", [])}
                self.current = None
                self.in_license = False
                self.in_certs_ul = False
                self.in_li = False
            elif tag.lower() == "span" and self.in_license:
                self.in_license = False
            elif tag.lower() == "ul" and self.in_certs_ul:
                self.in_certs_ul = False
            elif tag.lower() == "li" and self.in_li:
                self.in_li = False

    def handle_data(self, data):
        if self.current is not None:
            if self.in_license:
                text = data.strip()
                if text:
                    self.current["license"] = text
            elif self.in_certs_ul and self.in_li:
                text = data.strip()
                if text:
                    self.current.setdefault("certs", []).append(text)


def safe_parse_profiles_html(path: Path) -> Optional[Dict[str, Dict[str, Any]]]:
    try:
        if not path.exists():
            return None
        parser = ProfilesHTMLParser()
        with path.open(encoding="utf-8") as f:
            parser.feed(f.read())
        return parser.results
    except Exception:
        return None


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 3958.8
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def to_float_safe(v: Any) -> Optional[float]:
    try:
        return float(v)
    except Exception:
        return None


def to_int_safe(v: Any) -> Optional[int]:
    try:
        return int(v)
    except Exception:
        return None


def parse_bool_flexible(v: Any) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "t", "1", "yes", "y"):
            return True
        if s in ("false", "f", "0", "no", "n"):
            return False
    return None


def load_zip_coords(path: Path) -> Optional[Dict[str, Tuple[float, float]]]:
    rows = safe_read_csv(path)
    if rows is None:
        return None
    result: Dict[str, Tuple[float, float]] = {}
    for r in rows:
        z = r.get("zip")
        lat = to_float_safe(r.get("lat"))
        lng = to_float_safe(r.get("lng"))
        if z is None or lat is None or lng is None:
            return None
        result[z] = (lat, lng)
    return result


def compute_expected(workspace: Path) -> Optional[Dict[str, Any]]:
    inspectors_path = workspace / "input" / "inspectors.csv"
    complaints_path = workspace / "input" / "complaints.json"
    profiles_path = workspace / "input" / "profiles.html"
    zip_coords_path = workspace / "input" / "zip_coords.csv"
    prefs_path = workspace / "config" / "preferences.yaml"

    inspectors = safe_read_csv(inspectors_path)
    complaints = safe_read_json(complaints_path)
    profiles = safe_parse_profiles_html(profiles_path)
    zip_coords = load_zip_coords(zip_coords_path)
    prefs = parse_preferences_yaml(prefs_path)

    if inspectors is None or complaints is None or profiles is None or zip_coords is None or prefs is None:
        return None

    complaints_map: Dict[str, int] = {}
    try:
        for item in complaints:
            lic = item.get("license_number")
            cnt = item.get("complaint_count")
            if lic is None or cnt is None:
                return None
            complaints_map[lic] = int(cnt)
    except Exception:
        return None

    preferred_zip = str(prefs["preferred_zip"])
    if preferred_zip not in zip_coords:
        return None
    preferred_coords = zip_coords[preferred_zip]

    max_distance = float(prefs["max_distance_miles"])
    max_budget = float(prefs["max_budget"])
    min_years = float(prefs["min_years_experience"])
    must_have = set(prefs.get("must_have_certifications", []))
    weights = prefs.get("weights", {})

    expected_records: Dict[str, Dict[str, Any]] = {}
    eligible_ids: List[str] = []

    for r in inspectors:
        inspector_id = r.get("inspector_id")
        if not inspector_id:
            return None
        name = r.get("name", "")
        company = r.get("company", "")
        base_price = to_float_safe(r.get("base_price"))
        zip_code = r.get("zip")
        service_radius = to_float_safe(r.get("service_radius_miles"))
        years_exp = to_float_safe(r.get("years_experience"))
        license_csv = r.get("license_number", "")

        if None in (base_price, service_radius, years_exp) or zip_code is None or license_csv is None:
            return None

        profile = profiles.get(inspector_id, {})
        license_html = profile.get("license")
        certs_list = profile.get("certifications", [])
        certs_set = set(certs_list)

        license_match = (license_html == license_csv)

        if zip_code not in zip_coords:
            return None
        latlng_ins = zip_coords[zip_code]
        dist = haversine_miles(preferred_coords[0], preferred_coords[1], latlng_ins[0], latlng_ins[1])

        eligible = True
        if dist > max_distance or dist > service_radius:
            eligible = False
        if base_price > max_budget:
            eligible = False
        if years_exp < min_years:
            eligible = False
        if not must_have.issubset(certs_set):
            eligible = False

        complaint_count = complaints_map.get(license_csv, 0)

        normalized_experience = min(years_exp / 20.0, 1.0)
        if "InterNACHI" in certs_set:
            cert_points = 1.0
        elif "ASHI" in certs_set:
            cert_points = 0.7
        else:
            cert_points = 0.0
        normalized_complaints = min(complaint_count / 5.0, 1.0)
        normalized_price = min(base_price / 500.0, 1.0)

        reliability = (
            weights.get("experience", 0.0) * normalized_experience
            + weights.get("certifications", 0.0) * cert_points
            - weights.get("complaints", 0.0) * normalized_complaints
            - weights.get("price", 0.0) * normalized_price
        )

        expected_records[inspector_id] = {
            "inspector_id": inspector_id,
            "name": name,
            "company": company,
            "license_number_csv": license_csv,
            "license_number_html": license_html,
            "license_match": license_match,
            "certifications": certs_list,
            "base_price": base_price,
            "years_experience": years_exp,
            "complaint_count": complaint_count,
            "distance_miles": dist,
            "reliability_score": reliability,
            "eligible": eligible,
        }
        if eligible:
            eligible_ids.append(inspector_id)

    eligible_sorted = sorted(eligible_ids, key=lambda x: expected_records[x]["reliability_score"], reverse=True)

    mismatch_list = [rid for rid, rec in expected_records.items() if rec["license_match"] is False]

    expected = {
        "records": expected_records,
        "eligible_sorted": eligible_sorted,
        "mismatch_list": mismatch_list,
        "preferences": prefs,
    }
    return expected


def safe_read_output_shortlist(path: Path) -> Optional[List[Dict[str, str]]]:
    return safe_read_csv(path)


def safe_read_output_report(path: Path) -> Optional[Dict[str, Any]]:
    return safe_read_json(path)


def approx_equal(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "shortlist_file_and_columns": 0.0,
        "shortlist_eligibility_set_correct": 0.0,
        "reliability_scores_correct": 0.0,
        "distances_correct": 0.0,
        "license_fields_and_match_correct": 0.0,
        "certifications_list_correct": 0.0,
        "sorting_descending_by_reliability": 0.0,
        "report_json_fields_correct": 0.0,
        "report_top_consistency": 0.0,
    }

    expected = compute_expected(workspace)
    if expected is None:
        return scores

    shortlist_path = workspace / "output" / "shortlist.csv"
    report_path = workspace / "output" / "report.json"
    shortlist = safe_read_output_shortlist(shortlist_path)
    report = safe_read_output_report(report_path)

    required_columns = [
        "inspector_id",
        "name",
        "company",
        "license_number_csv",
        "license_number_html",
        "license_match",
        "certifications",
        "base_price",
        "years_experience",
        "complaint_count",
        "distance_miles",
        "reliability_score",
    ]

    if shortlist is not None and isinstance(shortlist, list):
        if len(shortlist) == 0:
            try:
                with shortlist_path.open(encoding="utf-8") as f:
                    header_line = f.readline()
                headers = [h.strip() for h in header_line.strip().split(",")]
            except Exception:
                headers = []
        else:
            headers = list(shortlist[0].keys())
        if all(col in headers for col in required_columns):
            scores["shortlist_file_and_columns"] = 1.0

    expected_ids_set = set(expected["eligible_sorted"])
    got_ids_set: Optional[set] = None
    if shortlist is not None:
        try:
            got_ids_set = set(row.get("inspector_id", "") for row in shortlist)
        except Exception:
            got_ids_set = None
    if got_ids_set is not None and got_ids_set == expected_ids_set:
        scores["shortlist_eligibility_set_correct"] = 1.0

    license_ok = True
    if shortlist is None or (len(shortlist) == 0 and len(expected_ids_set) > 0):
        license_ok = False
    if shortlist is not None:
        for row in shortlist:
            rid = row.get("inspector_id", "")
            exp_rec = expected["records"].get(rid)
            if exp_rec is None:
                license_ok = False
                break
            lic_csv = row.get("license_number_csv")
            lic_html = row.get("license_number_html")
            lic_match_val = parse_bool_flexible(row.get("license_match"))
            if lic_csv != exp_rec["license_number_csv"]:
                license_ok = False
                break
            if (lic_html or "") != (exp_rec["license_number_html"] or ""):
                license_ok = False
                break
            if lic_match_val is None or lic_match_val != exp_rec["license_match"]:
                license_ok = False
                break
    if license_ok:
        scores["license_fields_and_match_correct"] = 1.0

    dist_ok = True
    if shortlist is None:
        dist_ok = False
    else:
        for row in shortlist:
            rid = row.get("inspector_id", "")
            exp_rec = expected["records"].get(rid)
            if exp_rec is None:
                dist_ok = False
                break
            d_out = to_float_safe(row.get("distance_miles"))
            if d_out is None:
                dist_ok = False
                break
            if not approx_equal(d_out, float(exp_rec["distance_miles"]), tol=0.3):
                dist_ok = False
                break
    if dist_ok:
        scores["distances_correct"] = 1.0

    certs_ok = True
    if shortlist is None:
        certs_ok = False
    else:
        for row in shortlist:
            rid = row.get("inspector_id", "")
            exp_rec = expected["records"].get(rid)
            if exp_rec is None:
                certs_ok = False
                break
            out_certs_raw = row.get("certifications", "")
            out_certs = [c.strip() for c in out_certs_raw.split(";") if c.strip() != ""]
            if set(out_certs) != set(exp_rec["certifications"]):
                certs_ok = False
                break
    if certs_ok:
        scores["certifications_list_correct"] = 1.0

    rel_ok = True
    if shortlist is None:
        rel_ok = False
    else:
        for row in shortlist:
            rid = row.get("inspector_id", "")
            exp_rec = expected["records"].get(rid)
            if exp_rec is None:
                rel_ok = False
                break
            r_out = to_float_safe(row.get("reliability_score"))
            if r_out is None:
                rel_ok = False
                break
            if not approx_equal(r_out, float(exp_rec["reliability_score"]), tol=1e-3):
                rel_ok = False
                break
    if rel_ok:
        scores["reliability_scores_correct"] = 1.0

    sorting_ok = True
    if shortlist is None:
        sorting_ok = False
    else:
        got_order = [row.get("inspector_id", "") for row in shortlist]
        expected_order = list(expected["eligible_sorted"])
        if got_order != expected_order:
            try:
                rels = [to_float_safe(row.get("reliability_score")) for row in shortlist]
                if any(r is None for r in rels):
                    sorting_ok = False
                else:
                    rels_f = [float(r) for r in rels if r is not None]
                    for i in range(1, len(rels_f)):
                        if rels_f[i] > rels_f[i - 1] + 1e-6:
                            sorting_ok = False
                            break
                    unique_scores = len(set(rels_f)) == len(rels_f)
                    if unique_scores and got_order != expected_order:
                        sorting_ok = False
            except Exception:
                sorting_ok = False
    if sorting_ok:
        scores["sorting_descending_by_reliability"] = 1.0

    report_ok = True
    if report is None:
        report_ok = False
    else:
        req_keys = ["total_inspectors_considered", "eligible_count_after_filters", "mismatch_list", "top_inspector"]
        if any(k not in report for k in req_keys):
            report_ok = False
        else:
            total_considered = report.get("total_inspectors_considered")
            eligible_count = report.get("eligible_count_after_filters")
            if to_int_safe(total_considered) != len(expected["records"]):
                report_ok = False
            if to_int_safe(eligible_count) != len(expected["eligible_sorted"]):
                report_ok = False
            r_mismatch = report.get("mismatch_list")
            if not isinstance(r_mismatch, list):
                report_ok = False
            else:
                exp_mismatch_set = set(expected["mismatch_list"])
                try:
                    r_mismatch_set = set(map(str, r_mismatch))
                except Exception:
                    report_ok = False
                    r_mismatch_set = set()
                if r_mismatch_set != exp_mismatch_set:
                    report_ok = False
            top = report.get("top_inspector")
            if not isinstance(top, dict):
                report_ok = False
            else:
                exp_top_id = expected["eligible_sorted"][0] if expected["eligible_sorted"] else None
                exp_top_rec = expected["records"].get(exp_top_id) if exp_top_id else None
                if exp_top_rec is None:
                    report_ok = False
                else:
                    if str(top.get("inspector_id")) != str(exp_top_rec["inspector_id"]):
                        report_ok = False
                    if str(top.get("name")) != str(exp_top_rec["name"]):
                        report_ok = False
                    try:
                        top_rel = float(top.get("reliability_score"))
                    except Exception:
                        report_ok = False
                        top_rel = None
                    if top_rel is None or not approx_equal(top_rel, float(exp_top_rec["reliability_score"]), 1e-3):
                        report_ok = False
            filters_summary = report.get("filters_summary") or report.get("filters") or report.get("applied_filters")
            if filters_summary is None or not isinstance(filters_summary, dict):
                report_ok = False
            else:
                prefs = expected["preferences"]
                keys_to_check = ["preferred_zip", "max_distance_miles", "max_budget", "min_years_experience", "must_have_certifications", "weights"]
                for k in keys_to_check:
                    if k not in filters_summary:
                        report_ok = False
                        break
                if report_ok:
                    try:
                        if int(filters_summary.get("preferred_zip")) != int(prefs["preferred_zip"]):
                            report_ok = False
                        if float(filters_summary.get("max_distance_miles")) != float(prefs["max_distance_miles"]):
                            report_ok = False
                        if float(filters_summary.get("max_budget")) != float(prefs["max_budget"]):
                            report_ok = False
                        if float(filters_summary.get("min_years_experience")) != float(prefs["min_years_experience"]):
                            report_ok = False
                        fm = filters_summary.get("must_have_certifications")
                        if not isinstance(fm, list):
                            report_ok = False
                        else:
                            if set(map(str, fm)) != set(map(str, prefs["must_have_certifications"])):
                                report_ok = False
                        fw = filters_summary.get("weights")
                        if not isinstance(fw, dict):
                            report_ok = False
                        else:
                            for wk, wv in prefs["weights"].items():
                                if wk not in fw:
                                    report_ok = False
                                    break
                                try:
                                    if not approx_equal(float(fw[wk]), float(wv), tol=1e-9):
                                        report_ok = False
                                        break
                                except Exception:
                                    report_ok = False
                                    break
                    except Exception:
                        report_ok = False
    if report_ok:
        scores["report_json_fields_correct"] = 1.0

    top_consistency_ok = True
    if shortlist is None or report is None:
        top_consistency_ok = False
    else:
        if len(shortlist) == 0:
            top_consistency_ok = False
        else:
            top_row = shortlist[0]
            top_id_csv = top_row.get("inspector_id")
            top_name_csv = top_row.get("name")
            top_rel_csv = to_float_safe(top_row.get("reliability_score"))
            top_report = report.get("top_inspector") if isinstance(report, dict) else None
            if not isinstance(top_report, dict):
                top_consistency_ok = False
            else:
                if str(top_report.get("inspector_id")) != str(top_id_csv):
                    top_consistency_ok = False
                if str(top_report.get("name")) != str(top_name_csv):
                    top_consistency_ok = False
                if top_rel_csv is None:
                    top_consistency_ok = False
                else:
                    try:
                        rep_rel = float(top_report.get("reliability_score"))
                    except Exception:
                        top_consistency_ok = False
                        rep_rel = None
                    if rep_rel is None or not approx_equal(rep_rel, float(top_rel_csv), 1e-3):
                        top_consistency_ok = False
    if top_consistency_ok:
        scores["report_top_consistency"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()