import json
import csv
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any


EXPECTED_CLEAN_COLUMNS = [
    "pollster",
    "sample_size",
    "support_keep_tradition_pct",
    "oppose_pct",
    "undecided_pct",
    "is_valid",
]

AGG_JSON_KEYS = [
    "total_sample_size_valid_polls",
    "valid_poll_count",
    "invalid_poll_count",
    "weighted_support_pct",
    "weighted_oppose_pct",
    "weighted_undecided_pct",
    "expected_attendance",
    "room_capacity",
    "overflow_expected",
    "overflow_count",
    "status_quo_recommendation",
]


def parse_bool(s: str) -> bool:
    v = s.strip().lower()
    if v in ("true", "t", "1", "yes"):
        return True
    if v in ("false", "f", "0", "no"):
        return False
    if s.strip() == "True":
        return True
    if s.strip() == "False":
        return False
    raise ValueError("Invalid boolean value")


def close_float(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


class PollsTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_polls_table = False
        self.in_tbody = False
        self.in_tr = False
        self.in_td = False
        self.current_row: List[str] = []
        self.current_cell_text: List[str] = []
        self.rows: List[List[str]] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        t = tag.lower()
        if t == "table":
            attrs_dict = dict(attrs)
            if attrs_dict.get("id") == "polls":
                self.in_polls_table = True
        elif t == "tbody" and self.in_polls_table:
            self.in_tbody = True
        elif t == "tr" and self.in_tbody:
            self.in_tr = True
            self.current_row = []
        elif t == "td" and self.in_tr:
            self.in_td = True
            self.current_cell_text = []

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t == "td" and self.in_td:
            cell = "".join(self.current_cell_text).strip()
            self.current_row.append(cell)
            self.in_td = False
            self.current_cell_text = []
        elif t == "tr" and self.in_tr:
            if self.current_row:
                self.rows.append(self.current_row)
            self.in_tr = False
            self.current_row = []
        elif t == "tbody" and self.in_tbody:
            self.in_tbody = False
        elif t == "table" and self.in_polls_table:
            self.in_polls_table = False

    def handle_data(self, data: str) -> None:
        if self.in_td:
            self.current_cell_text.append(data)


def parse_polls_html(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        html_text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    parser = PollsTableParser()
    try:
        parser.feed(html_text)
    except Exception:
        return None
    expected_rows: List[Dict[str, Any]] = []
    for row in parser.rows:
        # Expect 5 cells per tbody row
        if len(row) != 5:
            return None
        try:
            pollster = row[0].strip()
            sample_size = int(row[1].strip())
            support = float(row[2].strip())
            oppose = float(row[3].strip())
            undecided = float(row[4].strip())
        except Exception:
            return None
        total = support + oppose + undecided
        is_valid = (total >= 99.5) and (total <= 100.5)
        expected_rows.append({
            "pollster": pollster,
            "sample_size": sample_size,
            "support_keep_tradition_pct": support,
            "oppose_pct": oppose,
            "undecided_pct": undecided,
            "is_valid": is_valid,
        })
    return expected_rows


def read_csv_rows(path: Path) -> Optional[Tuple[List[str], List[List[str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
    except Exception:
        return None
    if not rows:
        return None
    header = rows[0]
    data_rows = rows[1:]
    return header, data_rows


def parse_clean_polls_csv(path: Path) -> Optional[List[Dict[str, Any]]]:
    parsed = read_csv_rows(path)
    if not parsed:
        return None
    header, data_rows = parsed
    if header != EXPECTED_CLEAN_COLUMNS:
        return None
    cleaned: List[Dict[str, Any]] = []
    for r in data_rows:
        if len(r) != len(EXPECTED_CLEAN_COLUMNS):
            return None
        try:
            pollster = r[0]
            sample_size = int(r[1])
            support = float(r[2])
            oppose = float(r[3])
            undecided = float(r[4])
            is_valid = parse_bool(r[5])
        except Exception:
            return None
        cleaned.append({
            "pollster": pollster,
            "sample_size": sample_size,
            "support_keep_tradition_pct": support,
            "oppose_pct": oppose,
            "undecided_pct": undecided,
            "is_valid": is_valid,
        })
    return cleaned


def load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def sum_attendees(path: Path) -> Optional[int]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if "headcount" not in (reader.fieldnames or []):
                return None
            total = 0
            for row in reader:
                try:
                    total += int(row["headcount"])
                except Exception:
                    return None
            return total
    except Exception:
        return None


def parse_agenda_sections(text: str) -> Dict[str, List[str]]:
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    sections: Dict[str, List[str]] = {}
    current: Optional[str] = None
    for ln in lines:
        hdr = ln.strip()
        if hdr.endswith(":"):
            title = hdr[:-1]
            current = title
            if current not in sections:
                sections[current] = []
            continue
        if current is not None:
            sections[current].append(ln)
    return sections


def parse_room_capacity(path: Path) -> Optional[int]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    sections = parse_agenda_sections(text)
    logistics = sections.get("Logistics")
    if logistics:
        for line in logistics:
            m = re.search(r"Room\s+capacity:\s*(\d+)", line, flags=re.IGNORECASE)
            if m:
                try:
                    return int(m.group(1))
                except Exception:
                    return None
    m2 = re.search(r"Room\s+capacity:\s*(\d+)", text, flags=re.IGNORECASE)
    if m2:
        try:
            return int(m2.group(1))
        except Exception:
            return None
    return None


def compute_expected_aggregates(polls: List[Dict[str, Any]],
                                attendees_csv: Path,
                                agenda_md: Path) -> Optional[Dict[str, Any]]:
    valid = [r for r in polls if r.get("is_valid")]
    invalid = [r for r in polls if not r.get("is_valid")]
    total_sample = sum(int(r["sample_size"]) for r in valid)
    valid_count = len(valid)
    invalid_count = len(invalid)
    if total_sample > 0:
        w_support = sum(r["support_keep_tradition_pct"] * r["sample_size"] for r in valid) / total_sample
        w_oppose = sum(r["oppose_pct"] * r["sample_size"] for r in valid) / total_sample
        w_undec = sum(r["undecided_pct"] * r["sample_size"] for r in valid) / total_sample
    else:
        w_support = 0.0
        w_oppose = 0.0
        w_undec = 0.0
    w_support_r = round(w_support + 1e-12, 1)
    w_oppose_r = round(w_oppose + 1e-12, 1)
    w_undec_r = round(w_undec + 1e-12, 1)

    expected_attendance = sum_attendees(attendees_csv)
    room_capacity = parse_room_capacity(agenda_md)
    if expected_attendance is None or room_capacity is None:
        return None
    overflow_expected = expected_attendance > room_capacity
    overflow_count = expected_attendance - room_capacity if overflow_expected else 0
    status = "Maintain current format" if w_support_r >= 50.0 else "Do additional outreach before final decision"

    return {
        "total_sample_size_valid_polls": total_sample,
        "valid_poll_count": valid_count,
        "invalid_poll_count": invalid_count,
        "weighted_support_pct": w_support_r,
        "weighted_oppose_pct": w_oppose_r,
        "weighted_undecided_pct": w_undec_r,
        "expected_attendance": expected_attendance,
        "room_capacity": room_capacity,
        "overflow_expected": overflow_expected,
        "overflow_count": overflow_count,
        "status_quo_recommendation": status,
    }


def read_text_file(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def is_title_line(line: str, title: str) -> bool:
    s = line.strip()
    if s.startswith("#"):
        s = re.sub(r"^\s*#+\s*", "", s)
    return s == title


def extract_section_content(text: str, title: str) -> Optional[List[str]]:
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    titles = ["Data Summary", "Action Items", "Logistics"]
    start_idx: Optional[int] = None
    for i, ln in enumerate(lines):
        if is_title_line(ln, title):
            start_idx = i + 1
            break
    if start_idx is None:
        return None
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        for t in titles:
            if is_title_line(lines[j], t):
                end_idx = j
                break
        if end_idx != len(lines):
            break
    return lines[start_idx:end_idx]


def numbers_present(section_lines: List[str], value_strs: List[str]) -> bool:
    joined = "\n".join(section_lines)
    for vs in value_strs:
        if vs not in joined:
            return False
    return True


def floats_present(section_lines: List[str], float_values: List[float]) -> bool:
    joined = "\n".join(section_lines)
    for v in float_values:
        s = f"{v:.1f}"
        if s not in joined:
            return False
    return True


def parse_decisions(path: Path) -> Optional[List[str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    sections = parse_agenda_sections(text)
    decisions_block = sections.get("Decisions Needed")
    if decisions_block is None:
        return None
    decisions: List[str] = []
    for ln in decisions_block:
        s = ln.strip()
        if s.startswith("- "):
            decisions.append(s[2:].strip())
        elif s.startswith("* "):
            decisions.append(s[2:].strip())
        else:
            if decisions and s and not s.startswith("#"):
                break
    return decisions


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "clean_polls_structure": 0.0,
        "clean_polls_row_values": 0.0,
        "aggregated_json_structure": 0.0,
        "aggregated_json_values": 0.0,
        "meeting_notes_sections": 0.0,
        "meeting_notes_data_summary_alignment": 0.0,
        "meeting_notes_action_items": 0.0,
        "meeting_notes_logistics": 0.0,
    }

    polls_html_path = workspace / "input" / "polls.html"
    attendees_csv_path = workspace / "input" / "attendees.csv"
    agenda_md_path = workspace / "input" / "agenda.md"

    clean_polls_csv_path = workspace / "output" / "clean_polls.csv"
    aggregated_json_path = workspace / "output" / "aggregated_metrics.json"
    meeting_notes_md_path = workspace / "output" / "meeting_notes.md"

    expected_rows = parse_polls_html(polls_html_path) if polls_html_path.exists() else None

    clean_rows = None
    if clean_polls_csv_path.exists():
        clean_rows = parse_clean_polls_csv(clean_polls_csv_path)
    else:
        clean_rows = None

    if clean_rows is not None:
        scores["clean_polls_structure"] = 1.0
    else:
        scores["clean_polls_structure"] = 0.0

    if clean_rows is not None and expected_rows is not None:
        if len(clean_rows) == len(expected_rows):
            values_ok = True
            for got, exp in zip(clean_rows, expected_rows):
                if got["pollster"] != exp["pollster"]:
                    values_ok = False
                    break
                if got["sample_size"] != exp["sample_size"]:
                    values_ok = False
                    break
                if not close_float(float(got["support_keep_tradition_pct"]), float(exp["support_keep_tradition_pct"])):
                    values_ok = False
                    break
                if not close_float(float(got["oppose_pct"]), float(exp["oppose_pct"])):
                    values_ok = False
                    break
                if not close_float(float(got["undecided_pct"]), float(exp["undecided_pct"])):
                    values_ok = False
                    break
                total = float(got["support_keep_tradition_pct"]) + float(got["oppose_pct"]) + float(got["undecided_pct"])
                is_valid_def = (total >= 99.5) and (total <= 100.5)
                if bool(got["is_valid"]) != bool(exp["is_valid"]) or bool(got["is_valid"]) != is_valid_def:
                    values_ok = False
                    break
            scores["clean_polls_row_values"] = 1.0 if values_ok else 0.0
        else:
            scores["clean_polls_row_values"] = 0.0
    else:
        scores["clean_polls_row_values"] = 0.0

    agg_json = load_json(aggregated_json_path) if aggregated_json_path.exists() else None
    if agg_json is not None and isinstance(agg_json, dict):
        keys_ok = set(agg_json.keys()) == set(AGG_JSON_KEYS)
        types_ok = True
        if keys_ok:
            if not isinstance(agg_json["total_sample_size_valid_polls"], int):
                types_ok = False
            if not isinstance(agg_json["valid_poll_count"], int):
                types_ok = False
            if not isinstance(agg_json["invalid_poll_count"], int):
                types_ok = False
            for k in ["weighted_support_pct", "weighted_oppose_pct", "weighted_undecided_pct"]:
                v = agg_json.get(k)
                if not isinstance(v, (int, float)):
                    types_ok = False
                else:
                    v = float(v)
                    if abs(v - round(v, 1)) > 1e-9:
                        types_ok = False
            if not isinstance(agg_json["expected_attendance"], int):
                types_ok = False
            if not isinstance(agg_json["room_capacity"], int):
                types_ok = False
            if not isinstance(agg_json["overflow_expected"], bool):
                types_ok = False
            if not isinstance(agg_json["overflow_count"], int):
                types_ok = False
            if not isinstance(agg_json["status_quo_recommendation"], str):
                types_ok = False
        scores["aggregated_json_structure"] = 1.0 if (keys_ok and types_ok) else 0.0
    else:
        scores["aggregated_json_structure"] = 0.0

    if agg_json is not None and expected_rows is not None:
        expected_agg = compute_expected_aggregates(expected_rows, attendees_csv_path, agenda_md_path)
        if expected_agg is not None:
            values_ok = True
            try:
                if agg_json["total_sample_size_valid_polls"] != expected_agg["total_sample_size_valid_polls"]:
                    values_ok = False
                if agg_json["valid_poll_count"] != expected_agg["valid_poll_count"]:
                    values_ok = False
                if agg_json["invalid_poll_count"] != expected_agg["invalid_poll_count"]:
                    values_ok = False
                for k in ["weighted_support_pct", "weighted_oppose_pct", "weighted_undecided_pct"]:
                    v = float(agg_json[k])
                    ev = float(expected_agg[k])
                    if abs(v - ev) > 0.05:
                        values_ok = False
                if agg_json["expected_attendance"] != expected_agg["expected_attendance"]:
                    values_ok = False
                if agg_json["room_capacity"] != expected_agg["room_capacity"]:
                    values_ok = False
                if bool(agg_json["overflow_expected"]) != expected_agg["overflow_expected"]:
                    values_ok = False
                if int(agg_json["overflow_count"]) != expected_agg["overflow_count"]:
                    values_ok = False
                if agg_json["status_quo_recommendation"] != expected_agg["status_quo_recommendation"]:
                    values_ok = False
            except Exception:
                values_ok = False
            scores["aggregated_json_values"] = 1.0 if values_ok else 0.0
        else:
            scores["aggregated_json_values"] = 0.0
    else:
        scores["aggregated_json_values"] = 0.0

    notes_text = read_text_file(meeting_notes_md_path) if meeting_notes_md_path.exists() else None
    if notes_text is None:
        return scores

    sections_ok = True
    for title in ["Data Summary", "Action Items", "Logistics"]:
        content = extract_section_content(notes_text, title)
        if content is None:
            sections_ok = False
            break
    scores["meeting_notes_sections"] = 1.0 if sections_ok else 0.0

    data_summary_ok = False
    if agg_json is not None:
        ds_content = extract_section_content(notes_text, "Data Summary")
        if ds_content is not None:
            ints_needed = [
                str(agg_json.get("valid_poll_count")),
                str(agg_json.get("invalid_poll_count")),
                str(agg_json.get("total_sample_size_valid_polls")),
            ]
            floats_needed_vals = [
                float(agg_json.get("weighted_support_pct")),
                float(agg_json.get("weighted_oppose_pct")),
                float(agg_json.get("weighted_undecided_pct")),
            ]
            if numbers_present(ds_content, ints_needed) and floats_present(ds_content, floats_needed_vals):
                data_summary_ok = True
    scores["meeting_notes_data_summary_alignment"] = 1.0 if data_summary_ok else 0.0

    action_items_ok = False
    decisions = parse_decisions(agenda_md_path) if agenda_md_path.exists() else None
    if decisions is not None:
        ai_content = extract_section_content(notes_text, "Action Items")
        if ai_content is not None:
            expected_lines = {f"Action: {d}; Owner: TBD" for d in decisions}
            found_lines: List[str] = []
            for ln in ai_content:
                s = ln.strip()
                if s.startswith("- "):
                    found_lines.append(s[2:].strip())
                elif s.startswith("* "):
                    found_lines.append(s[2:].strip())
            if expected_lines.issubset(set(found_lines)):
                action_items_ok = True
    scores["meeting_notes_action_items"] = 1.0 if action_items_ok else 0.0

    logistics_ok = False
    if agg_json is not None:
        lg_content = extract_section_content(notes_text, "Logistics")
        if lg_content is not None:
            joined = "\n".join(lg_content)
            ea = str(agg_json.get("expected_attendance"))
            rc = str(agg_json.get("room_capacity"))
            oc = str(agg_json.get("overflow_count"))
            status = str(agg_json.get("status_quo_recommendation"))
            overflow_expected = bool(agg_json.get("overflow_expected"))
            numbers_ok = (ea in joined) and (rc in joined) and (oc in joined)
            status_present = status in joined
            extra_note_ok = True
            if overflow_expected:
                note_line_found = False
                for ln in lg_content:
                    if re.search(r"overflow", ln, flags=re.IGNORECASE) and (re.search(r"plan", ln, flags=re.IGNORECASE) or re.search(r"queue", ln, flags=re.IGNORECASE)):
                        note_line_found = True
                        break
                extra_note_ok = note_line_found
            logistics_ok = numbers_ok and status_present and extra_note_ok
    scores["meeting_notes_logistics"] = 1.0 if logistics_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()