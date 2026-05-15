import json
import csv
import sys
from pathlib import Path
from datetime import datetime
from html.parser import HTMLParser
from typing import List, Dict, Optional, Tuple, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_simple_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Parse a very simple YAML consisting of flat key: value pairs (strings or integers).
    Ignores empty lines and comments starting with '#'.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    data: Dict[str, Any] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            return None
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val_unquoted = val[1:-1]
        else:
            val_unquoted = val
        try:
            int_val = int(val_unquoted)
            data[key] = int_val
        except ValueError:
            data[key] = val_unquoted
    required_keys = [
        "severity_threshold",
        "top_n",
        "inbox_dir",
        "normalized_dir",
        "top_hazards_dir",
        "emails_dir",
        "index_path",
        "processed_log",
    ]
    for k in required_keys:
        if k not in data:
            return None
    return data


def _read_csv(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            rows = [row for row in reader]
            return reader.fieldnames, rows
    except Exception:
        return None


def _to_int(s: Any) -> Optional[int]:
    try:
        if isinstance(s, int):
            return s
        if isinstance(s, float):
            return int(s)
        return int(str(s).strip())
    except Exception:
        return None


def _is_iso_like(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    t = s.replace("Z", "+00:00") if s.endswith("Z") else s
    try:
        datetime.fromisoformat(t)
        return True
    except Exception:
        return False


class _AssessmentHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_client = False
        self.in_hazards_table = False
        self.in_tbody = False
        self.current_td = False
        self.current_div_class = None
        self.data_buffer = ""
        self.client: Dict[str, str] = {"client_name": "", "email": "", "address": ""}
        self.hazards: List[List[str]] = []
        self.row_cells: List[str] = []
        self._tag_stack: List[str] = []

    def handle_starttag(self, tag, attrs):
        self._tag_stack.append(tag)
        attrdict = dict(attrs)
        if tag.lower() == "section" and attrdict.get("id", "") == "client":
            self.in_client = True
        if tag.lower() == "div" and self.in_client:
            self.current_div_class = attrdict.get("class", "")
        if tag.lower() == "table" and attrdict.get("id", "") == "hazards":
            self.in_hazards_table = True
        if tag.lower() == "tbody" and self.in_hazards_table:
            self.in_tbody = True
        if tag.lower() == "tr" and self.in_tbody:
            self.row_cells = []
        if tag.lower() == "td" and self.in_tbody:
            self.current_td = True
            self.data_buffer = ""

    def handle_endtag(self, tag):
        if tag.lower() == "td" and self.in_tbody and self.current_td:
            self.current_td = False
            self.row_cells.append(self.data_buffer.strip())
            self.data_buffer = ""
        if tag.lower() == "tr" and self.in_tbody:
            if self.row_cells:
                self.hazards.append(self.row_cells)
            self.row_cells = []
        if tag.lower() == "div" and self.in_client:
            self.current_div_class = None
        if tag.lower() == "tbody" and self.in_hazards_table:
            self.in_tbody = False
        if tag.lower() == "table" and self.in_hazards_table:
            self.in_hazards_table = False
        if tag.lower() == "section" and self.in_client:
            self.in_client = False
        if self._tag_stack:
            self._tag_stack.pop()

    def handle_data(self, data):
        if self.in_client and self.current_div_class in ("name", "email", "address"):
            key = "client_name" if self.current_div_class == "name" else self.current_div_class
            self.client[key] += data.strip()
        if self.current_td:
            self.data_buffer += data


def _parse_csv_assessment(path: Path) -> Optional[Dict[str, Any]]:
    res = _read_csv(path)
    if res is None:
        return None
    header, rows = res
    expected_cols = ["client_name", "email", "address", "room", "hazard_category", "severity", "notes"]
    if header != expected_cols:
        return None
    if not rows:
        return None
    client_name = rows[0]["client_name"].strip()
    email = rows[0]["email"].strip()
    address = rows[0]["address"].strip()
    hazards: List[Dict[str, Any]] = []
    for r in rows:
        sev = _to_int(r.get("severity", ""))
        if sev is None:
            return None
        hazards.append({
            "room": r.get("room", "").strip(),
            "hazard_category": r.get("hazard_category", "").strip(),
            "severity": sev,
            "notes": r.get("notes", "").strip(),
        })
    return {
        "client_name": client_name,
        "email": email,
        "address": address,
        "hazards": hazards,
    }


def _parse_html_assessment(path: Path) -> Optional[Dict[str, Any]]:
    text = _read_text(path)
    if text is None:
        return None
    parser = _AssessmentHTMLParser()
    try:
        parser.feed(text)
    except Exception:
        return None
    client_name = parser.client.get("client_name", "").strip()
    email = parser.client.get("email", "").strip()
    address = parser.client.get("address", "").strip()
    if not (client_name and email and address):
        return None
    hazards: List[Dict[str, Any]] = []
    for cells in parser.hazards:
        if len(cells) != 4:
            return None
        room, cat, sev_s, notes = [c.strip() for c in cells]
        sev = _to_int(sev_s)
        if sev is None:
            return None
        hazards.append({
            "room": room,
            "hazard_category": cat,
            "severity": sev,
            "notes": notes,
        })
    if not hazards:
        return None
    return {
        "client_name": client_name,
        "email": email,
        "address": address,
        "hazards": hazards,
    }


def _sort_and_rank_hazards(hazards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sorted_h = sorted(hazards, key=lambda h: (-int(h["severity"]), str(h["hazard_category"])))
    ranked: List[Dict[str, Any]] = []
    for idx, h in enumerate(sorted_h, start=1):
        item = {
            "room": h["room"],
            "hazard_category": h["hazard_category"],
            "severity": int(h["severity"]),
            "notes": h["notes"],
            "rank": idx,
        }
        ranked.append(item)
    return ranked


def _expected_email_bullets(top_hazards: List[Dict[str, Any]], guidelines: Dict[str, str]) -> List[str]:
    bullets: List[str] = []
    for h in top_hazards:
        rec = guidelines.get(h["hazard_category"], guidelines.get("default", ""))
        bullets.append(f"- {h['room']} - {h['hazard_category']} (Severity {h['severity']}): {rec}")
    return bullets


def _parse_normalized_json(path: Path) -> Optional[Dict[str, Any]]:
    data = _load_json(path)
    if not isinstance(data, dict):
        return None
    if not all(k in data for k in ["client_name", "email", "address", "hazards"]):
        return None
    if not isinstance(data["hazards"], list):
        return None
    return data


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "normalized_harper_exists": 0.0,
        "normalized_harper_structure_and_content": 0.0,
        "normalized_patel_exists": 0.0,
        "normalized_patel_structure_and_content": 0.0,
        "top_hazards_harper_exists": 0.0,
        "top_hazards_harper_content": 0.0,
        "top_hazards_patel_exists": 0.0,
        "top_hazards_patel_content": 0.0,
        "email_harper_exists": 0.0,
        "email_harper_content": 0.0,
        "email_patel_exists": 0.0,
        "email_patel_content": 0.0,
        "index_exists": 0.0,
        "index_header_and_rows": 0.0,
        "index_sorted_order": 0.0,
        "processed_log_exists": 0.0,
        "processed_log_content": 0.0,
    }

    # Load config (required to resolve output paths)
    config_path = workspace / "input" / "automation_config.yaml"
    config = _parse_simple_yaml(config_path) if config_path.exists() else None

    # Load guidelines
    guidelines_path = workspace / "input" / "hazard_guidelines.json"
    guidelines = _load_json(guidelines_path) if guidelines_path.exists() else None
    if not isinstance(guidelines, dict):
        guidelines = None

    # If config missing, we cannot locate outputs; return zeros for all checks gracefully.
    if not config:
        return scores

    # Resolve paths from config
    inbox_dir = workspace / str(config["inbox_dir"])
    normalized_dir = workspace / str(config["normalized_dir"])
    top_hazards_dir = workspace / str(config["top_hazards_dir"])
    emails_dir = workspace / str(config["emails_dir"])
    index_path = workspace / str(config["index_path"])
    processed_log_path = workspace / str(config["processed_log"])
    severity_threshold = int(config["severity_threshold"])
    top_n = int(config["top_n"])

    # Input files: expected specific samples
    harper_base = "harper_family_assessment"
    patel_base = "patel_family_assessment"
    harper_input = inbox_dir / f"{harper_base}.csv"
    patel_input = inbox_dir / f"{patel_base}.html"

    # Parse inputs to compute expectations
    harper_assess = _parse_csv_assessment(harper_input) if harper_input.exists() else None
    patel_assess = _parse_html_assessment(patel_input) if patel_input.exists() else None

    # Helper to validate normalized JSON
    def validate_normalized(assess: Optional[Dict[str, Any]], path: Path) -> Tuple[bool, bool]:
        exists = path.exists()
        structure_ok = False
        if exists and assess is not None:
            parsed = _parse_normalized_json(path)
            if parsed:
                basic_ok = (
                    parsed.get("client_name") == assess["client_name"]
                    and parsed.get("email") == assess["email"]
                    and parsed.get("address") == assess["address"]
                )
                hazards = parsed.get("hazards", [])
                all_fields_ok = True
                severities_int = True
                ranks_int = True
                expected_ranked = _sort_and_rank_hazards(assess["hazards"])
                if len(hazards) != len(expected_ranked):
                    all_fields_ok = False
                else:
                    for h_json, h_exp in zip(hazards, expected_ranked):
                        if not all(k in h_json for k in ["room", "hazard_category", "severity", "notes", "rank"]):
                            all_fields_ok = False
                            break
                        if not isinstance(h_json["severity"], int):
                            severities_int = False
                        if not isinstance(h_json["rank"], int):
                            ranks_int = False
                        if (
                            h_json.get("room") != h_exp["room"]
                            or h_json.get("hazard_category") != h_exp["hazard_category"]
                            or h_json.get("severity") != h_exp["severity"]
                            or h_json.get("notes") != h_exp["notes"]
                            or h_json.get("rank") != h_exp["rank"]
                        ):
                            all_fields_ok = False
                            break
                structure_ok = all([basic_ok, all_fields_ok, severities_int, ranks_int])
        return exists, structure_ok

    # Expected normalized paths
    harper_norm_path = normalized_dir / f"{harper_base}.json"
    patel_norm_path = normalized_dir / f"{patel_base}.json"

    # Validate normalized outputs
    harper_exists, harper_ok = validate_normalized(harper_assess, harper_norm_path)
    scores["normalized_harper_exists"] = 1.0 if harper_exists else 0.0
    scores["normalized_harper_structure_and_content"] = 1.0 if harper_ok else 0.0

    patel_exists, patel_ok = validate_normalized(patel_assess, patel_norm_path)
    scores["normalized_patel_exists"] = 1.0 if patel_exists else 0.0
    scores["normalized_patel_structure_and_content"] = 1.0 if patel_ok else 0.0

    # Helper to compute expected top hazards rows
    def compute_expected_top_rows(assess: Optional[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
        if assess is None:
            return None
        ranked_all = _sort_and_rank_hazards(assess["hazards"])
        filtered = [h for h in ranked_all if int(h["severity"]) >= severity_threshold]
        top = filtered[:top_n]
        return top

    # Validate top hazards CSV
    def validate_top_csv(path: Path, assess: Optional[Dict[str, Any]]) -> Tuple[bool, bool]:
        exists = path.exists()
        content_ok = False
        if exists and assess is not None and guidelines is not None:
            exp_top = compute_expected_top_rows(assess)
            parsed = _read_csv(path)
            if parsed is not None and exp_top is not None:
                header, rows = parsed
                expected_header = ["rank", "room", "hazard_category", "severity", "recommendation"]
                if header == expected_header and len(rows) == len(exp_top):
                    row_ok = True
                    for r, h in zip(rows, exp_top):
                        rank = _to_int(r.get("rank"))
                        sev = _to_int(r.get("severity"))
                        if rank != h["rank"] or sev != h["severity"]:
                            row_ok = False
                            break
                        if r.get("room", "").strip() != h["room"]:
                            row_ok = False
                            break
                        if r.get("hazard_category", "").strip() != h["hazard_category"]:
                            row_ok = False
                            break
                        rec_expected = guidelines.get(h["hazard_category"], guidelines.get("default", ""))
                        if r.get("recommendation", "").strip() != rec_expected:
                            row_ok = False
                            break
                    content_ok = row_ok
        return exists, content_ok

    harper_top_path = top_hazards_dir / f"{harper_base}_top{top_n}.csv"
    patel_top_path = top_hazards_dir / f"{patel_base}_top{top_n}.csv"

    h_top_exists, h_top_ok = validate_top_csv(harper_top_path, harper_assess)
    scores["top_hazards_harper_exists"] = 1.0 if h_top_exists else 0.0
    scores["top_hazards_harper_content"] = 1.0 if h_top_ok else 0.0

    p_top_exists, p_top_ok = validate_top_csv(patel_top_path, patel_assess)
    scores["top_hazards_patel_exists"] = 1.0 if p_top_exists else 0.0
    scores["top_hazards_patel_content"] = 1.0 if p_top_ok else 0.0

    # Validate emails
    def validate_email(path: Path, assess: Optional[Dict[str, Any]]) -> Tuple[bool, bool]:
        exists = path.exists()
        content_ok = False
        if exists and assess is not None and guidelines is not None:
            text = _read_text(path)
            if text is not None:
                lines = text.splitlines()
                if len(lines) >= 2:
                    line1_ok = lines[0].strip() == f"To: {assess['email']}"
                    line2_ok = lines[1].strip() == "Subject: Your baby-proofing assessment summary"
                    greeting_ok = any(assess["client_name"] in ln for ln in lines[2:]) if len(lines) > 2 else False
                    exp_top = compute_expected_top_rows(assess)
                    bullets_ok = False
                    if exp_top is not None:
                        exp_bullets = _expected_email_bullets(exp_top, guidelines)
                        idx = 0
                        for ln in lines:
                            if idx < len(exp_bullets) and ln.strip() == exp_bullets[idx]:
                                idx += 1
                        bullets_ok = (idx == len(exp_bullets))
                    closings = ("Best regards", "Regards", "Sincerely", "Thank you", "Thanks")
                    closing_ok = any(cl.lower() in text.lower() for cl in closings)
                    content_ok = all([line1_ok, line2_ok, greeting_ok, bullets_ok, closing_ok])
        return exists, content_ok

    harper_email_path = emails_dir / f"{harper_base}.txt"
    patel_email_path = emails_dir / f"{patel_base}.txt"

    h_email_exists, h_email_ok = validate_email(harper_email_path, harper_assess)
    scores["email_harper_exists"] = 1.0 if h_email_exists else 0.0
    scores["email_harper_content"] = 1.0 if h_email_ok else 0.0

    p_email_exists, p_email_ok = validate_email(patel_email_path, patel_assess)
    scores["email_patel_exists"] = 1.0 if p_email_exists else 0.0
    scores["email_patel_content"] = 1.0 if p_email_ok else 0.0

    # Validate index.csv
    scores["index_exists"] = 1.0 if index_path.exists() else 0.0
    if index_path.exists():
        parsed = _read_csv(index_path)
        if parsed is not None:
            header, rows = parsed
            expected_header = [
                "assessment_file",
                "client_name",
                "email",
                "address",
                "highest_severity",
                "high_risk_count",
                "last_processed",
            ]
            header_ok = (header == expected_header)
            row_map = {row.get("assessment_file", ""): row for row in rows}
            expected_files = {
                harper_base: harper_assess,
                patel_base: patel_assess,
            }
            rows_ok = True
            for base, assess in expected_files.items():
                if assess is None or base not in row_map:
                    rows_ok = False
                    break
                row = row_map[base]
                if row.get("client_name", "").strip() != assess["client_name"]:
                    rows_ok = False
                    break
                if row.get("email", "").strip() != assess["email"]:
                    rows_ok = False
                    break
                if row.get("address", "").strip() != assess["address"]:
                    rows_ok = False
                    break
                hs = _to_int(row.get("highest_severity"))
                if hs is None:
                    rows_ok = False
                    break
                expected_hs = max(int(h["severity"]) for h in assess["hazards"])
                if hs != expected_hs:
                    rows_ok = False
                    break
                hrc = _to_int(row.get("high_risk_count"))
                if hrc is None:
                    rows_ok = False
                    break
                expected_hrc = sum(1 for h in assess["hazards"] if int(h["severity"]) >= severity_threshold)
                if hrc != expected_hrc:
                    rows_ok = False
                    break
                if not _is_iso_like(row.get("last_processed", "")):
                    rows_ok = False
                    break
            if header_ok and rows_ok:
                scores["index_header_and_rows"] = 1.0
            try:
                def sort_key(r: Dict[str, str]):
                    hs = _to_int(r.get("highest_severity")) or -10**9
                    hrc = _to_int(r.get("high_risk_count")) or -10**9
                    name = r.get("client_name", "")
                    return (-hs, -hrc, name)
                sorted_rows = sorted(rows, key=sort_key)
                if [r["assessment_file"] for r in sorted_rows] == [r["assessment_file"] for r in rows]:
                    scores["index_sorted_order"] = 1.0
            except Exception:
                pass

    # Validate processed.jsonl
    scores["processed_log_exists"] = 1.0 if processed_log_path.exists() else 0.0
    if processed_log_path.exists():
        text = _read_text(processed_log_path)
        if text is not None:
            last_by_filename: Dict[str, Dict[str, Any]] = {}
            ok_lines = True
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict) and "filename" in obj:
                        last_by_filename[obj["filename"]] = obj
                except Exception:
                    ok_lines = False
                    break
            if ok_lines:
                log_ok = True
                for fname, assess in [
                    (f"{harper_base}.csv", harper_assess),
                    (f"{patel_base}.html", patel_assess),
                ]:
                    if assess is None or fname not in last_by_filename:
                        log_ok = False
                        break
                    entry = last_by_filename[fname]
                    if entry.get("client_name") != assess["client_name"]:
                        log_ok = False
                        break
                    if not _is_iso_like(entry.get("processed_at", "")):
                        log_ok = False
                        break
                    hc = entry.get("hazard_count", None)
                    if _to_int(hc) != len(assess["hazards"]):
                        log_ok = False
                        break
                if log_ok:
                    scores["processed_log_content"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()