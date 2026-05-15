import csv
import json
import re
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    if not path.exists():
        return None, None
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames[:] if reader.fieldnames else []
            rows = [row for row in reader]
            return fieldnames, rows
    except Exception:
        return None, None


def _parse_simple_yaml_targets(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML parser for the provided targets.yaml structure.
    Supports:
      - top-level keys: surnames (list), counties (list), weights (mapping), top_n (int), newsletter_title (str)
      - weights contains: surname_match (int/float), county_match (int/float), relation_hint_bonus (mapping str->int/float), source_quality_multiplier (int/float)
    """
    text = _safe_read_text(path)
    if text is None:
        return None

    def strip_quotes(s: str) -> str:
        s = s.strip()
        if (s.startswith("'") and s.endswith("'")) or (s.startswith('"') and s.endswith('"')):
            return s[1:-1]
        return s

    lines = text.splitlines()
    i = 0
    n = len(lines)

    result: Dict[str, Any] = {}
    current_key: Optional[str] = None
    current_indent = 0

    def parse_list(start_index: int, indent: int) -> Tuple[List[str], int]:
        items: List[str] = []
        idx = start_index
        while idx < n:
            line = lines[idx]
            if not line.strip():
                idx += 1
                continue
            leading = len(line) - len(line.lstrip(' '))
            if leading < indent or not line.lstrip().startswith('- '):
                break
            value = line.lstrip()[2:]
            items.append(strip_quotes(value.strip()))
            idx += 1
        return items, idx

    def parse_mapping(start_index: int, indent: int) -> Tuple[Dict[str, Any], int]:
        mapping: Dict[str, Any] = {}
        idx = start_index
        while idx < n:
            raw = lines[idx]
            if not raw.strip():
                idx += 1
                continue
            leading = len(raw) - len(raw.lstrip(' '))
            if leading < indent:
                break
            line = raw.lstrip()
            if ': ' in line or line.endswith(':'):
                key, sep, rest = line.partition(':')
                key = strip_quotes(key.strip())
                rest_val = rest.strip()
                if rest_val == "":
                    # Could be nested list or mapping
                    # Peek next line to determine
                    next_idx = idx + 1
                    # If next is a list item with greater indent, parse list
                    if next_idx < n:
                        nxt = lines[next_idx]
                        nxt_leading = len(nxt) - len(nxt.lstrip(' '))
                        if nxt.strip().startswith('- ') and nxt_leading > leading:
                            lst, new_idx = parse_list(next_idx, nxt_leading)
                            mapping[key] = lst
                            idx = new_idx
                            continue
                        elif nxt_leading > leading:
                            # Nested mapping
                            submap, new_idx = parse_mapping(next_idx, nxt_leading)
                            mapping[key] = submap
                            idx = new_idx
                            continue
                    # Empty/None value
                    mapping[key] = None
                    idx += 1
                else:
                    # Scalar value
                    val_s = strip_quotes(rest_val)
                    # Try to parse number
                    if re.fullmatch(r'-?\d+', val_s):
                        mapping[key] = int(val_s)
                    elif re.fullmatch(r'-?\d+\.\d*', val_s):
                        mapping[key] = float(val_s)
                    else:
                        mapping[key] = val_s
                    idx += 1
            else:
                break
        return mapping, idx

    while i < n:
        raw = lines[i]
        if not raw.strip():
            i += 1
            continue
        leading = len(raw) - len(raw.lstrip(' '))
        line = raw.lstrip()
        if ': ' in line or line.endswith(':'):
            key, sep, rest = line.partition(':')
            key = strip_quotes(key.strip())
            rest_val = rest.strip()
            if rest_val == "":
                # Could be a list or mapping
                next_i = i + 1
                if next_i < n:
                    nxt = lines[next_i]
                    nxt_leading = len(nxt) - len(nxt.lstrip(' '))
                    if nxt.strip().startswith('- ') and nxt_leading > leading:
                        lst, new_idx = parse_list(next_i, nxt_leading)
                        result[key] = lst
                        i = new_idx
                        continue
                    elif nxt_leading > leading:
                        submap, new_idx = parse_mapping(next_i, nxt_leading)
                        result[key] = submap
                        i = new_idx
                        continue
                result[key] = None
                i += 1
            else:
                val_s = strip_quotes(rest_val)
                if re.fullmatch(r'-?\d+', val_s):
                    result[key] = int(val_s)
                elif re.fullmatch(r'-?\d+\.\d*', val_s):
                    result[key] = float(val_s)
                else:
                    result[key] = val_s
                i += 1
        else:
            i += 1

    # Validate required structure
    try:
        surnames = [str(x) for x in result.get("surnames", [])]
        counties = [str(x) for x in result.get("counties", [])]
        weights = result.get("weights", {})
        surname_match = float(weights.get("surname_match", 0))
        county_match = float(weights.get("county_match", 0))
        relation_hint_bonus = weights.get("relation_hint_bonus", {}) or {}
        rhb_norm: Dict[str, float] = {}
        for k, v in relation_hint_bonus.items():
            rhb_norm[str(k).strip().lower()] = float(v)
        sqm = float(weights.get("source_quality_multiplier", 0))
        top_n = int(result.get("top_n", 0))
        newsletter_title = str(result.get("newsletter_title", "")).strip()
    except Exception:
        return None

    return {
        "surnames": surnames,
        "counties": counties,
        "weights": {
            "surname_match": surname_match,
            "county_match": county_match,
            "relation_hint_bonus": rhb_norm,
            "source_quality_multiplier": sqm,
        },
        "top_n": top_n,
        "newsletter_title": newsletter_title,
    }


@dataclass
class ObitRecord:
    full_name: str
    surname: str
    county: str
    state: str
    event_year: int
    relation_hint: str
    source_quality: float
    source_id: str
    url: str


class _ObitHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_obit = False
        self.current: Dict[str, Any] = {}
        self.records: List[ObitRecord] = []
        self.current_field: Optional[str] = None
        self._field_text: List[str] = []

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        if tag.lower() == "div":
            cls = attr.get("class", "")
            classes = set(cls.split())
            if "obit" in classes:
                self.in_obit = True
                self.current = {
                    "source_id": attr.get("data-source-id", "").strip()
                }
                self.current_field = None
        if not self.in_obit:
            return
        if tag.lower() in ("h2", "span", "a"):
            cls = attr.get("class", "")
            classes = set(cls.split())
            if "name" in classes and tag.lower() == "h2":
                self.current_field = "full_name"
                self._field_text = []
            elif "date" in classes and tag.lower() == "span":
                self.current_field = "date"
                self._field_text = []
            elif "county" in classes and tag.lower() == "span":
                self.current_field = "county"
                self._field_text = []
            elif "state" in classes and tag.lower() == "span":
                self.current_field = "state"
                self._field_text = []
            elif "relation_hint" in classes and tag.lower() == "span":
                self.current_field = "relation_hint"
                self._field_text = []
            elif "source_quality" in classes and tag.lower() == "span":
                self.current_field = "source_quality"
                self._field_text = []
            elif "url" in classes and tag.lower() == "a":
                href = attr.get("href", "").strip()
                self.current["url"] = href

    def handle_endtag(self, tag):
        if not self.in_obit:
            return
        if tag.lower() in ("h2", "span"):
            if self.current_field and self._field_text is not None:
                value = "".join(self._field_text).strip()
                self.current[self.current_field] = value
            self.current_field = None
            self._field_text = []
        if tag.lower() == "div" and self.in_obit:
            # finalize record
            full_name = self.current.get("full_name", "").strip()
            surname = full_name.split()[-1] if full_name else ""
            county = self.current.get("county", "").strip()
            state = self.current.get("state", "").strip()
            date = self.current.get("date", "").strip()
            m = re.match(r"(\d{4})", date)
            event_year = int(m.group(1)) if m else 0
            relation_hint = self.current.get("relation_hint", "").strip()
            sq_raw = self.current.get("source_quality", "").strip()
            try:
                source_quality = float(sq_raw)
            except Exception:
                source_quality = 0.0
            source_id = self.current.get("source_id", "").strip()
            url = self.current.get("url", "").strip()
            self.records.append(ObitRecord(
                full_name=full_name,
                surname=surname,
                county=county,
                state=state,
                event_year=event_year,
                relation_hint=relation_hint,
                source_quality=source_quality,
                source_id=source_id,
                url=url
            ))
            self.in_obit = False
            self.current = {}
            self.current_field = None
            self._field_text = []

    def handle_data(self, data):
        if self.in_obit and self.current_field is not None:
            self._field_text.append(data)


def _parse_obituaries_html(path: Path) -> Optional[List[ObitRecord]]:
    text = _safe_read_text(path)
    if text is None:
        return None
    try:
        parser = _ObitHTMLParser()
        parser.feed(text)
        return parser.records
    except Exception:
        return None


def _normalize_str(s: str) -> str:
    return s.strip().lower()


def _compute_expected_records(workspace: Path) -> Tuple[Optional[List[Dict[str, Any]]], Optional[List[Dict[str, Any]]], int]:
    # Load inputs
    census_path = workspace / "input" / "new_records" / "census_1920.csv"
    obits_path = workspace / "input" / "new_records" / "obituaries.html"
    targets_path = workspace / "input" / "targets.yaml"

    targets = _parse_simple_yaml_targets(targets_path)
    census_fields, census_rows = _safe_read_csv(census_path)
    obits = _parse_obituaries_html(obits_path)

    if targets is None or census_rows is None or obits is None:
        # return None markers
        total_records_parsed = 0
        if census_rows is not None:
            total_records_parsed += len(census_rows)
        if obits is not None:
            total_records_parsed += len(obits)
        return None, None, total_records_parsed

    surnames_set = {_normalize_str(x) for x in targets["surnames"]}
    counties_set = {_normalize_str(x) for x in targets["counties"]}
    weights = targets["weights"]
    rhb = weights["relation_hint_bonus"]
    sqm = weights["source_quality_multiplier"]

    all_records: List[Dict[str, Any]] = []
    # Parse census rows
    for row in census_rows:
        try:
            full_name = row.get("full_name", "").strip()
            surname = row.get("surname", "").strip()
            county = row.get("county", "").strip()
            state = row.get("state", "").strip()
            event_year = int(str(row.get("event_year", "0")).strip() or "0")
            relation_hint = row.get("relation_hint", "").strip()
            source_quality = float(str(row.get("source_quality", "0")).strip() or "0")
            source_id = row.get("source_id", "").strip()
        except Exception:
            # Malformed row; treat as unparseable -> skip
            continue
        surname_match = _normalize_str(surname) in surnames_set
        county_match = _normalize_str(county) in counties_set
        if not (surname_match or county_match):
            continue
        bonus = rhb.get(_normalize_str(relation_hint), 0.0)
        score = (weights["surname_match"] if surname_match else 0.0) \
                + (weights["county_match"] if county_match else 0.0) \
                + float(bonus) \
                + (source_quality * float(sqm))
        rec = {
            "full_name": full_name,
            "surname": surname,
            "county": county,
            "state": state,
            "event_type": "census",
            "event_year": event_year,
            "relation_hint": relation_hint,
            "source_quality": float(source_quality),
            "source_id": source_id,
            "source": "census_1920",
            "score": float(score),
        }
        all_records.append(rec)

    # Parse obituaries
    for ob in obits:
        full_name = ob.full_name
        surname = ob.surname
        county = ob.county
        state = ob.state
        event_year = ob.event_year
        relation_hint = ob.relation_hint
        source_quality = ob.source_quality
        source_id = ob.source_id
        surname_match = _normalize_str(surname) in surnames_set
        county_match = _normalize_str(county) in counties_set
        if not (surname_match or county_match):
            continue
        bonus = rhb.get(_normalize_str(relation_hint), 0.0)
        score = (weights["surname_match"] if surname_match else 0.0) \
                + (weights["county_match"] if county_match else 0.0) \
                + float(bonus) \
                + (source_quality * float(sqm))
        rec = {
            "full_name": full_name,
            "surname": surname,
            "county": county,
            "state": state,
            "event_type": "obituary",
            "event_year": event_year,
            "relation_hint": relation_hint,
            "source_quality": float(source_quality),
            "source_id": source_id,
            "source": "obituaries",
            "score": float(score),
        }
        all_records.append(rec)

    # Sort kept records by score desc; tie-break by full_name asc (case-insensitive)
    all_records_sorted = sorted(all_records, key=lambda r: (-r["score"], _normalize_str(r["full_name"])))
    top_n = int(targets["top_n"])
    top_records = all_records_sorted[:min(top_n, len(all_records_sorted))]
    total_records_parsed = (len(census_rows) if census_rows else 0) + (len(obits) if obits else 0)
    return all_records_sorted, top_records, total_records_parsed


def _load_output_csv(path: Path) -> Tuple[bool, List[str], List[Dict[str, Any]]]:
    fieldnames, rows = _safe_read_csv(path)
    if fieldnames is None or rows is None:
        return False, [], []
    # Return rows as parsed with numeric fields if possible left as strings; we will coerce later.
    return True, fieldnames, rows


def _coerce_row_types(row: Dict[str, str]) -> Dict[str, Any]:
    out: Dict[str, Any] = dict(row)
    # Coerce known numeric fields
    if "event_year" in out:
        try:
            out["event_year"] = int(str(out["event_year"]).strip())
        except Exception:
            out["event_year"] = None
    if "source_quality" in out:
        try:
            out["source_quality"] = float(str(out["source_quality"]).strip())
        except Exception:
            out["source_quality"] = None
    if "score" in out:
        try:
            out["score"] = float(str(out["score"]).strip())
        except Exception:
            out["score"] = None
    if "rank" in out:
        try:
            out["rank"] = int(str(out["rank"]).strip())
        except Exception:
            out["rank"] = None
    return out


def _float_equal(a: Optional[float], b: Optional[float], tol: float = 1e-6) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def _iso_timestamp_like(s: str) -> bool:
    # Accept ISO formats like YYYY-MM-DDTHH:MM:SS or with Z/offset
    # Simple check: starts with YYYY-MM-DD
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", s))


def _parse_email_draft(path: Path) -> Tuple[bool, Optional[str], Optional[str], str, List[str]]:
    text = _safe_read_text(path)
    if text is None:
        return False, None, None, "", []
    lines = [ln.rstrip('\n') for ln in text.splitlines()]
    to_line = None
    subject_line = None
    body_start_index = 0
    for idx, ln in enumerate(lines):
        if ln.strip().lower().startswith("to:"):
            to_line = ln
        if ln.strip().lower().startswith("subject:"):
            subject_line = ln
            # Body likely begins after subject
            body_start_index = idx + 1
            break
    body = "\n".join(lines[body_start_index:]) if body_start_index < len(lines) else ""
    # Bullet lines: lines starting with one of "-", "*", "•" followed by space
    bullets = []
    for ln in lines[body_start_index:]:
        s = ln.lstrip()
        if s.startswith("- ") or s.startswith("* ") or s.startswith("• "):
            bullets.append(s)
    return True, to_line, subject_line, body, bullets


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "reports_all_scored_header_correct": 0.0,
        "reports_all_scored_content_correct": 0.0,
        "reports_top_ranked_header_correct": 0.0,
        "reports_top_ranked_content_correct": 0.0,
        "email_to_line_correct": 0.0,
        "email_subject_correct": 0.0,
        "email_body_intro_present": 0.0,
        "email_bullets_count_correct": 0.0,
        "email_bullets_content_correct": 0.0,
        "log_line_present_and_iso": 0.0,
        "log_counts_correct": 0.0,
    }

    expected_all, expected_top, total_records_parsed = _compute_expected_records(workspace)

    # Determine expected kept and top counts
    expected_kept_count = len(expected_all) if expected_all is not None else 0
    expected_top_count = len(expected_top) if expected_top is not None else 0

    # Paths
    all_scored_path = workspace / "output" / "reports" / "all_scored.csv"
    top_ranked_path = workspace / "output" / "reports" / "top_ranked.csv"
    email_path = workspace / "output" / "drafts" / "email_to_subscribers.txt"
    log_path = workspace / "output" / "logs" / "run.log"
    subscribers_path = workspace / "input" / "subscribers.csv"
    targets_path = workspace / "input" / "targets.yaml"

    # Expected headers
    expected_cols = ["full_name", "surname", "county", "state", "event_type", "event_year", "relation_hint", "source_quality", "source_id", "source", "score"]
    expected_top_cols = expected_cols + ["rank"]

    # Check all_scored.csv
    ok_all, all_fields, all_rows_raw = _load_output_csv(all_scored_path)
    if ok_all and all_fields == expected_cols:
        scores["reports_all_scored_header_correct"] = 1.0
    else:
        scores["reports_all_scored_header_correct"] = 0.0

    if ok_all and expected_all is not None and all_fields == expected_cols:
        # Coerce and compare
        all_rows = [_coerce_row_types(r) for r in all_rows_raw]
        # Check count equal expected
        if len(all_rows) == len(expected_all):
            # Check full content and order
            match_all = True
            for i, exp in enumerate(expected_all):
                if i >= len(all_rows):
                    match_all = False
                    break
                got = all_rows[i]
                for k in expected_cols:
                    if k not in got:
                        match_all = False
                        break
                    if k in ("event_year",):
                        if got[k] != exp[k]:
                            match_all = False
                            break
                    elif k in ("source_quality", "score"):
                        if not _float_equal(got[k], exp[k]):
                            match_all = False
                            break
                    else:
                        # compare as exact string
                        if str(got[k]).strip() != str(exp[k]).strip():
                            match_all = False
                            break
                if not match_all:
                    break
            if match_all:
                scores["reports_all_scored_content_correct"] = 1.0
            else:
                scores["reports_all_scored_content_correct"] = 0.0
        else:
            scores["reports_all_scored_content_correct"] = 0.0
    else:
        scores["reports_all_scored_content_correct"] = 0.0

    # Check top_ranked.csv
    ok_top, top_fields, top_rows_raw = _load_output_csv(top_ranked_path)
    if ok_top and top_fields == expected_top_cols:
        scores["reports_top_ranked_header_correct"] = 1.0
    else:
        scores["reports_top_ranked_header_correct"] = 0.0

    if ok_top and expected_top is not None and top_fields == expected_top_cols:
        top_rows = [_coerce_row_types(r) for r in top_rows_raw]
        # Count must be expected top count
        if len(top_rows) == expected_top_count:
            # Check rows correspond to expected_top in order and rank 1..N
            match_top = True
            for i, exp in enumerate(expected_top):
                if i >= len(top_rows):
                    match_top = False
                    break
                got = top_rows[i]
                # Check rank
                if got.get("rank") != i + 1:
                    match_top = False
                    break
                # Compare columns excluding rank
                for k in expected_cols:
                    if k not in got:
                        match_top = False
                        break
                    if k in ("event_year",):
                        if got[k] != exp[k]:
                            match_top = False
                            break
                    elif k in ("source_quality", "score"):
                        if not _float_equal(got[k], exp[k]):
                            match_top = False
                            break
                    else:
                        if str(got[k]).strip() != str(exp[k]).strip():
                            match_top = False
                            break
                if not match_top:
                    break
            if match_top:
                scores["reports_top_ranked_content_correct"] = 1.0
            else:
                scores["reports_top_ranked_content_correct"] = 0.0
        else:
            scores["reports_top_ranked_content_correct"] = 0.0
    else:
        scores["reports_top_ranked_content_correct"] = 0.0

    # Email checks
    email_ok, to_line, subject_line, body, bullets = _parse_email_draft(email_path)
    # To line
    subs_fields, subs_rows = _safe_read_csv(subscribers_path)
    if email_ok and to_line is not None and subs_rows is not None:
        # Extract emails from subscribers
        sub_emails = []
        for r in subs_rows:
            em = str(r.get("email", "")).strip()
            if em:
                sub_emails.append(em)
        # Extract emails from To line
        # Format: To: email1, email2, ...
        tl = to_line.strip()
        m = re.match(r"(?i)^to:\s*(.*)$", tl)
        if m:
            listed = m.group(1)
            to_emails = [e.strip() for e in listed.split(",") if e.strip()]
            if set(to_emails) == set(sub_emails) and len(to_emails) == len(sub_emails):
                scores["email_to_line_correct"] = 1.0
            else:
                scores["email_to_line_correct"] = 0.0
        else:
            scores["email_to_line_correct"] = 0.0
    else:
        scores["email_to_line_correct"] = 0.0

    # Subject line
    targets = _parse_simple_yaml_targets(targets_path)
    if email_ok and subject_line is not None and targets is not None:
        m = re.match(r"(?i)^subject:\s*(.*)$", subject_line.strip())
        if m and m.group(1).strip() == targets.get("newsletter_title", "").strip():
            scores["email_subject_correct"] = 1.0
        else:
            scores["email_subject_correct"] = 0.0
    else:
        scores["email_subject_correct"] = 0.0

    # Body intro
    if email_ok:
        if body.strip().startswith("Hi there, fellow researchers,"):
            scores["email_body_intro_present"] = 1.0
        else:
            scores["email_body_intro_present"] = 0.0
    else:
        scores["email_body_intro_present"] = 0.0

    # Bullet count and content
    if email_ok and targets is not None and expected_top is not None:
        top_n = int(targets["top_n"])
        if len(bullets) == min(top_n, len(expected_top)):
            scores["email_bullets_count_correct"] = 1.0
        else:
            scores["email_bullets_count_correct"] = 0.0

        # Content: each bullet must include required fields
        # We will match each expected top record to a bullet line that contains:
        # full_name, event_type, county, state, event_year, and score rounded to 1 decimal
        unmatched = list(bullets)
        all_match = True
        for rec in expected_top:
            needed = [
                rec["full_name"],
                rec["event_type"],
                rec["county"],
                rec["state"],
                str(rec["event_year"]),
            ]
            score_str = f"{rec['score']:.1f}"
            matched_index = -1
            for idx, b in enumerate(unmatched):
                ok = True
                for token in needed:
                    if token not in b:
                        ok = False
                        break
                if ok and (score_str in b):
                    matched_index = idx
                    break
            if matched_index >= 0:
                unmatched.pop(matched_index)
            else:
                all_match = False
                break
        scores["email_bullets_content_correct"] = 1.0 if all_match else 0.0
    else:
        scores["email_bullets_count_correct"] = 0.0
        scores["email_bullets_content_correct"] = 0.0

    # Log checks
    log_text = _safe_read_text(log_path)
    if log_text is not None and log_text.strip():
        last_line = log_text.strip().splitlines()[-1].strip()
        # Expect ISO timestamp at start
        parts = last_line.split(None, 1)
        if parts:
            ts = parts[0]
            if _iso_timestamp_like(ts):
                scores["log_line_present_and_iso"] = 1.0
            else:
                scores["log_line_present_and_iso"] = 0.0
        else:
            scores["log_line_present_and_iso"] = 0.0

        # Parse counts from remainder
        if len(parts) > 1 and expected_all is not None and targets is not None:
            remainder = parts[1]
            # Extract integers from remainder (excluding potential year from timestamp already removed)
            nums = re.findall(r"\d+", remainder)
            # We expect exactly 3 integers: total_records_parsed, kept_records_after_filter, top_n_exported
            try:
                ints = [int(x) for x in nums]
            except Exception:
                ints = []
            kept = expected_kept_count
            top_n = int(targets["top_n"])
            top_exported = min(top_n, kept)
            if len(ints) == 3 and ints[0] == total_records_parsed and ints[1] == kept and ints[2] == top_exported:
                scores["log_counts_correct"] = 1.0
            else:
                scores["log_counts_correct"] = 0.0
        else:
            scores["log_counts_correct"] = 0.0
    else:
        scores["log_line_present_and_iso"] = 0.0
        scores["log_counts_correct"] = 0.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()