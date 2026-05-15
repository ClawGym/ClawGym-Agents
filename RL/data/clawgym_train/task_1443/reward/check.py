import json
import sys
import re
import csv
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def read_text_file(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_file(path: Path) -> Optional[object]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def read_csv_dicts(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return (reader.fieldnames or [], rows)
    except Exception:
        return None


def parse_date(date_str: str) -> Optional[datetime]:
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d")
    except Exception:
        return None


def normalize_tokens_sep(s: str, sep: str) -> List[str]:
    return [t.strip() for t in s.split(sep) if t.strip()]


def canonical_join(tokens: List[str], sep: str) -> str:
    return sep.join(tokens)


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text))


def get_yaml_inline_list(text: str, key: str) -> Optional[List[str]]:
    m = re.search(rf"{re.escape(key)}\s*:\s*\[(.*?)\]", text, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    inner = m.group(1).strip()
    if not inner:
        return []
    parts = [p.strip() for p in inner.split(",")]
    vals = []
    for p in parts:
        q = re.match(r"""^["'](.*)["']$""", p)
        if q:
            vals.append(q.group(1))
        else:
            vals.append(p)
    return vals


def get_yaml_scalar(text: str, key: str) -> Optional[str]:
    m = re.search(rf"{re.escape(key)}\s*:\s*(['\"])(.*?)\1", text)
    if m:
        return m.group(2)
    m2 = re.search(rf"{re.escape(key)}\s*:\s*([^\s#]+)", text)
    if m2:
        return m2.group(1)
    return None


def get_yaml_date_range(text: str) -> Tuple[Optional[str], Optional[str]]:
    block = re.search(r"date_range\s*:\s*(?:\n\s+.*)+", text)
    if block:
        blk = block.group(0)
        start = re.search(r"start\s*:\s*(['\"])(.*?)\1", blk)
        end = re.search(r"end\s*:\s*(['\"])(.*?)\1", blk)
        s_val = start.group(2) if start else None
        e_val = end.group(2) if end else None
        return s_val, e_val
    start = re.search(r"start\s*:\s*(['\"])(.*?)\1", text)
    end = re.search(r"end\s*:\s*(['\"])(.*?)\1", text)
    s_val = start.group(2) if start else None
    e_val = end.group(2) if end else None
    return s_val, e_val


class ExhibitionHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.gallery_name: Optional[str] = None
        self.in_h1 = False
        self.in_exhibition_div = False
        self.capture_h2 = False
        self.capture_span_type: Optional[str] = None
        self.current: Optional[Dict[str, str]] = None
        self.results: List[Dict[str, str]] = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag.lower() == "h1":
            self.in_h1 = True
        if tag.lower() == "div" and attrs_dict.get("class", "") == "exhibition":
            self.in_exhibition_div = True
            self.current = {"exhibition_title": "", "dates": "", "mediums": "", "styles": ""}
        if self.in_exhibition_div:
            if tag.lower() == "h2":
                self.capture_h2 = True
            if tag.lower() == "span":
                cls = attrs_dict.get("class", "")
                if cls in ("dates", "mediums", "styles"):
                    self.capture_span_type = cls

    def handle_endtag(self, tag):
        if tag.lower() == "h1":
            self.in_h1 = False
        if self.in_exhibition_div and tag.lower() == "h2":
            self.capture_h2 = False
        if self.in_exhibition_div and tag.lower() == "span":
            self.capture_span_type = None
        if tag.lower() == "div" and self.in_exhibition_div:
            if self.current and self.gallery_name:
                entry = {
                    "gallery_name": (self.gallery_name or "").strip(),
                    "exhibition_title": self.current.get("exhibition_title", "").strip(),
                    "dates": self.current.get("dates", "").strip(),
                    "mediums": self.current.get("mediums", "").strip(),
                    "styles": self.current.get("styles", "").strip(),
                }
                self.results.append(entry)
            self.current = None
            self.in_exhibition_div = False

    def handle_data(self, data):
        if self.in_h1:
            self.gallery_name = (self.gallery_name or "") + data
        if self.in_exhibition_div:
            if self.capture_h2 and self.current is not None:
                self.current["exhibition_title"] = self.current.get("exhibition_title", "") + data
            if self.capture_span_type and self.current is not None:
                key = self.capture_span_type
                self.current[key] = self.current.get(key, "") + data


def parse_html_exhibitions(path: Path) -> List[Dict[str, object]]:
    text = read_text_file(path)
    if text is None:
        return []
    parser = ExhibitionHTMLParser()
    parser.feed(text)
    entries = []
    for e in parser.results:
        dates = e.get("dates", "")
        m = re.match(r"\s*(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})\s*", dates)
        if not m:
            continue
        start_date = m.group(1)
        end_date = m.group(2)
        mediums_tokens = normalize_tokens_sep(e.get("mediums", ""), ";")
        styles_tokens = [t.strip() for t in e.get("styles", "").split(",") if t.strip()]
        entries.append({
            "gallery_name": e.get("gallery_name", "").strip(),
            "exhibition_title": e.get("exhibition_title", "").strip(),
            "start_date": start_date,
            "end_date": end_date,
            "mediums_tokens": mediums_tokens,
            "styles_tokens": styles_tokens,
        })
    return entries


def compute_expected_exhibitions(input_dir: Path) -> List[Dict[str, str]]:
    include_styles = {"abstract", "mixed media", "new media", "contemporary"}
    exclude_styles = {"hyperrealism", "neoclassical"}
    allowed_medium_keywords = ["oil", "printmaking", "sculpture", "mixed media"]
    start_bound = parse_date("2024-11-01")
    end_bound = parse_date("2025-12-31")

    exhibitions: List[Dict[str, object]] = []
    for html_path in sorted(input_dir.glob("*.html")):
        exhibitions.extend(parse_html_exhibitions(html_path))

    def passes_filters(entry: Dict[str, object]) -> bool:
        styles = [s.lower() for s in entry["styles_tokens"]]  # type: ignore
        styles_set = set(s.strip() for s in styles)
        if styles_set.isdisjoint(include_styles):
            return False
        if not styles_set.isdisjoint(exclude_styles):
            return False
        mediums_tokens = [m.lower() for m in entry["mediums_tokens"]]  # type: ignore
        if not any(any(kw in m for m in mediums_tokens) for kw in allowed_medium_keywords):
            return False
        sd = parse_date(entry["start_date"])  # type: ignore
        ed = parse_date(entry["end_date"])    # type: ignore
        if sd is None or ed is None or start_bound is None or end_bound is None:
            return False
        if not (sd >= start_bound and ed <= end_bound):
            return False
        return True

    filtered = [e for e in exhibitions if passes_filters(e)]
    filtered.sort(key=lambda x: x["start_date"])  # type: ignore

    canonical = []
    for e in filtered:
        mediums_str = canonical_join([t.strip() for t in e["mediums_tokens"]], "; ")  # type: ignore
        styles_str = canonical_join([t.strip() for t in e["styles_tokens"]], ", ")    # type: ignore
        canonical.append({
            "gallery_name": e["gallery_name"],                           # type: ignore
            "exhibition_title": e["exhibition_title"],                   # type: ignore
            "start_date": e["start_date"],                               # type: ignore
            "end_date": e["end_date"],                                   # type: ignore
            "mediums": mediums_str,
            "styles": styles_str,
        })
    return canonical


def parse_csv_records(path: Path) -> Optional[List[Dict[str, str]]]:
    res = read_csv_dicts(path)
    if res is None:
        return None
    headers, rows = res
    expected_headers = ["gallery_name", "exhibition_title", "start_date", "end_date", "mediums", "styles"]
    if headers != expected_headers:
        return None
    norm_rows: List[Dict[str, str]] = []
    try:
        for r in rows:
            rec = {
                "gallery_name": r.get("gallery_name", "").strip(),
                "exhibition_title": r.get("exhibition_title", "").strip(),
                "start_date": r.get("start_date", "").strip(),
                "end_date": r.get("end_date", "").strip(),
                "mediums": r.get("mediums", "").strip(),
                "styles": r.get("styles", "").strip(),
            }
            if parse_date(rec["start_date"]) is None or parse_date(rec["end_date"]) is None:
                return None
            norm_rows.append(rec)
    except Exception:
        return None
    return norm_rows


def parse_json_records(path: Path) -> Optional[List[Dict[str, str]]]:
    data = load_json_file(path)
    if not isinstance(data, list):
        return None
    norm_rows: List[Dict[str, str]] = []
    try:
        for item in data:
            if not isinstance(item, dict):
                return None
            rec = {
                "gallery_name": str(item.get("gallery_name", "")).strip(),
                "exhibition_title": str(item.get("exhibition_title", "")).strip(),
                "start_date": str(item.get("start_date", "")).strip(),
                "end_date": str(item.get("end_date", "")).strip(),
                "mediums": str(item.get("mediums", "")).strip(),
                "styles": str(item.get("styles", "")).strip(),
            }
            if parse_date(rec["start_date"]) is None or parse_date(rec["end_date"]) is None:
                return None
            norm_rows.append(rec)
    except Exception:
        return None
    return norm_rows


def canonicalize_record(rec: Dict[str, str]) -> Dict[str, str]:
    meds = [t.strip() for t in rec.get("mediums", "").split(";") if t.strip()]
    stys = [t.strip() for t in rec.get("styles", "").split(",") if t.strip()]
    return {
        "gallery_name": rec.get("gallery_name", "").strip(),
        "exhibition_title": rec.get("exhibition_title", "").strip(),
        "start_date": rec.get("start_date", "").strip(),
        "end_date": rec.get("end_date", "").strip(),
        "mediums": "; ".join(meds),
        "styles": ", ".join(stys),
    }


def records_sorted_by_start_date(records: List[Dict[str, str]]) -> bool:
    dates = [parse_date(r.get("start_date", "")) for r in records]
    if any(d is None for d in dates):
        return False
    return all(dates[i] <= dates[i + 1] for i in range(len(dates) - 1))  # type: ignore


def extract_list_lines_from_text(text: str) -> List[Dict[str, str]]:
    lines = text.splitlines()
    pattern = re.compile(
        r"^\s*(?P<gallery>.+?)\s—\s(?P<title>.+?)\s\((?P<start>\d{4}-\d{2}-\d{2})\s+to\s+(?P<end>\d{4}-\d{2}-\d{2})\)\s—\s(?P<mediums>.+?)\s*$"
    )
    matches = []
    for line in lines:
        m = pattern.match(line)
        if m:
            matches.append({
                "gallery_name": m.group("gallery").strip(),
                "exhibition_title": m.group("title").strip(),
                "start_date": m.group("start").strip(),
                "end_date": m.group("end").strip(),
                "mediums_fragment": m.group("mediums").strip(),
            })
    return matches


def list_lines_match_csv(lines: List[Dict[str, str]], csv_records: List[Dict[str, str]]) -> bool:
    if len(lines) > 3:
        return False
    seen = set()
    for ln in lines:
        key = (ln["gallery_name"], ln["exhibition_title"], ln["start_date"], ln["end_date"])
        if key in seen:
            return False
        seen.add(key)
        candidates = [r for r in csv_records if (
            r.get("gallery_name") == ln["gallery_name"] and
            r.get("exhibition_title") == ln["exhibition_title"] and
            r.get("start_date") == ln["start_date"] and
            r.get("end_date") == ln["end_date"]
        )]
        if not candidates:
            return False
        rec = candidates[0]
        csv_mediums_tokens = [t.strip().lower() for t in rec.get("mediums", "").split(";") if t.strip()]
        frag = ln["mediums_fragment"].lower()
        if not any(tok in frag for tok in csv_mediums_tokens):
            return False
    return True


def records_to_set(records: List[Dict[str, str]]) -> set:
    canon = []
    for r in records:
        cr = canonicalize_record(r)
        canon.append((
            cr["gallery_name"],
            cr["exhibition_title"],
            cr["start_date"],
            cr["end_date"],
            cr["mediums"],
            cr["styles"],
        ))
    return set(canon)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_filters_updated": 0.0,
        "config_paths_unchanged": 0.0,
        "csv_exists_and_header": 0.0,
        "json_exists_and_structure": 0.0,
        "csv_sorted_by_start_date": 0.0,
        "json_sorted_by_start_date": 0.0,
        "csv_json_consistency": 0.0,
        "filtering_exact_match_with_inputs": 0.0,
        "mediums_styles_formatting": 0.0,
        "email_candid_word_limit": 0.0,
        "email_candid_list_accuracy": 0.0,
        "email_diplomatic_word_limit": 0.0,
        "email_diplomatic_retains_list": 0.0,
    }

    config_path = workspace / "config" / "scrape_config.yaml"
    csv_path = workspace / "output" / "exhibitions.csv"
    json_path = workspace / "output" / "exhibitions.json"
    input_dir = workspace / "input" / "webpages"
    candid_email_path = workspace / "output" / "email_candid.txt"
    diplomatic_email_path = workspace / "output" / "email_diplomatic.txt"

    cfg_text = read_text_file(config_path)
    filters_ok = False
    paths_ok = False
    if cfg_text is not None:
        inc = get_yaml_inline_list(cfg_text, "include_styles")
        exc = get_yaml_inline_list(cfg_text, "exclude_styles")
        amk = get_yaml_inline_list(cfg_text, "allowed_medium_keywords")
        ds, de = get_yaml_date_range(cfg_text)

        target_inc = {"Abstract", "Mixed Media", "New Media", "Contemporary"}
        target_exc = {"Hyperrealism", "Neoclassical"}
        target_amk = {"oil", "printmaking", "sculpture", "mixed media"}
        target_ds = "2024-11-01"
        target_de = "2025-12-31"

        if (inc is not None and set([s.strip() for s in inc]) == target_inc and
            exc is not None and set([s.strip() for s in exc]) == target_exc and
            amk is not None and set([s.strip() for s in amk]) == target_amk and
            ds == target_ds and de == target_de):
            filters_ok = True
            scores["config_filters_updated"] = 1.0

        input_glob = get_yaml_scalar(cfg_text, "input_glob")
        out_csv = get_yaml_scalar(cfg_text, "csv")
        out_json = get_yaml_scalar(cfg_text, "json")
        if (input_glob == "input/webpages/*.html" and
            out_csv == "output/exhibitions.csv" and
            out_json == "output/exhibitions.json"):
            paths_ok = True

        if filters_ok and paths_ok:
            scores["config_paths_unchanged"] = 1.0

    csv_rows = None
    headers_rows = read_csv_dicts(csv_path)
    if headers_rows is not None:
        headers, rows = headers_rows
        expected_headers = ["gallery_name", "exhibition_title", "start_date", "end_date", "mediums", "styles"]
        if headers == expected_headers:
            csv_rows = parse_csv_records(csv_path)
            if csv_rows is not None:
                scores["csv_exists_and_header"] = 1.0

    json_rows = None
    data = load_json_file(json_path)
    if isinstance(data, list):
        valid = True
        for item in data:
            if not isinstance(item, dict):
                valid = False
                break
            for k in ["gallery_name", "exhibition_title", "start_date", "end_date", "mediums", "styles"]:
                if k not in item:
                    valid = False
                    break
            if not valid:
                break
        if valid:
            json_rows = parse_json_records(json_path)
            if json_rows is not None:
                scores["json_exists_and_structure"] = 1.0

    if csv_rows is not None and records_sorted_by_start_date(csv_rows):
        scores["csv_sorted_by_start_date"] = 1.0
    if json_rows is not None and records_sorted_by_start_date(json_rows):
        scores["json_sorted_by_start_date"] = 1.0

    if csv_rows is not None and json_rows is not None:
        csv_set = records_to_set(csv_rows)
        json_set = records_to_set(json_rows)
        if csv_set == json_set and len(csv_rows) == len(json_rows):
            scores["csv_json_consistency"] = 1.0

    expected = compute_expected_exhibitions(input_dir)
    if csv_rows is not None:
        exp_set = records_to_set(expected)
        got_set = records_to_set(csv_rows)
        if exp_set == got_set and len(expected) == len(csv_rows):
            exp_order = [r["start_date"] for r in expected]
            got_order = [r["start_date"] for r in csv_rows]
            if exp_order == got_order:
                scores["filtering_exact_match_with_inputs"] = 1.0

    fmt_ok = True
    if csv_rows is not None:
        for r in csv_rows:
            meds = r.get("mediums", "")
            stys = r.get("styles", "")
            meds_tokens = [t for t in meds.split(";") if t.strip() != ""]
            stys_tokens = [t for t in stys.split(",") if t.strip() != ""]
            if len(meds_tokens) == 0 or len(stys_tokens) == 0:
                fmt_ok = False
                break
    else:
        fmt_ok = False
    if fmt_ok and json_rows is not None:
        for r in json_rows:
            meds = r.get("mediums", "")
            stys = r.get("styles", "")
            meds_tokens = [t for t in meds.split(";") if t.strip() != ""]
            stys_tokens = [t for t in stys.split(",") if t.strip() != ""]
            if len(meds_tokens) == 0 or len(stys_tokens) == 0:
                fmt_ok = False
                break
    else:
        fmt_ok = False if json_rows is None else fmt_ok
    if fmt_ok:
        scores["mediums_styles_formatting"] = 1.0

    candid_text = read_text_file(candid_email_path)
    diplomatic_text = read_text_file(diplomatic_email_path)

    if candid_text is not None:
        wc = word_count(candid_text)
        if 180 <= wc <= 250:
            scores["email_candid_word_limit"] = 1.0
    if diplomatic_text is not None:
        wc = word_count(diplomatic_text)
        if 120 <= wc <= 180:
            scores["email_diplomatic_word_limit"] = 1.0

    if candid_text is not None and csv_rows is not None:
        lines = extract_list_lines_from_text(candid_text)
        if len(csv_rows) == 0:
            if len(lines) == 0:
                scores["email_candid_list_accuracy"] = 1.0
        else:
            if 1 <= len(lines) <= 3 and list_lines_match_csv(lines, csv_rows):
                scores["email_candid_list_accuracy"] = 1.0

    if diplomatic_text is not None and candid_text is not None:
        cand_lines = extract_list_lines_from_text(candid_text)
        dip_lines = extract_list_lines_from_text(diplomatic_text)
        cand_set = {(l["gallery_name"], l["exhibition_title"], l["start_date"], l["end_date"], l["mediums_fragment"]) for l in cand_lines}
        dip_set = {(l["gallery_name"], l["exhibition_title"], l["start_date"], l["end_date"], l["mediums_fragment"]) for l in dip_lines}
        if len(cand_lines) == len(dip_lines) and cand_set == dip_set:
            scores["email_diplomatic_retains_list"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()