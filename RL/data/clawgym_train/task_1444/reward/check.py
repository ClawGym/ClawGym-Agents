import json
import csv
import sys
import re
from html.parser import HTMLParser
from pathlib import Path
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


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows
    except Exception:
        return None


def _strip_currency_to_int(s: str) -> Optional[int]:
    if s is None:
        return None
    try:
        ns = s.strip()
        ns = re.sub(r"[^0-9\-]", "", ns)
        if ns == "" or ns == "-":
            return None
        return int(ns)
    except Exception:
        return None


class PluginHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.plugins: List[Dict[str, Any]] = []
        self._in_plugin = False
        self._current: Dict[str, Any] = {}
        self._stack: List[str] = []
        self._capture_name = False
        self._capture_price = False
        self._current_list: Optional[str] = None  # "compatibility" or "tags"
        self._capture_li = False

    def handle_starttag(self, tag, attrs):
        attrs_dict = {k: v for k, v in attrs}
        self._stack.append(tag)
        if tag == "div":
            cls = attrs_dict.get("class", "")
            if "plugin-card" in cls.split():
                self._in_plugin = True
                self._current = {
                    "id": attrs_dict.get("data-plugin-id"),
                    "name": "",
                    "price_html": None,
                    "compatible_apps": [],
                    "categories_html": [],
                }
        if not self._in_plugin:
            return
        if tag == "h2" and "name" in (attrs_dict.get("class", "").split()):
            self._capture_name = True
        if tag == "span" and "price" in (attrs_dict.get("class", "").split()):
            self._capture_price = True
        if tag == "ul":
            cls = attrs_dict.get("class", "")
            if "compatibility" in cls.split():
                self._current_list = "compatibility"
            elif "tags" in cls.split():
                self._current_list = "tags"
        if tag == "li" and self._current_list in ("compatibility", "tags"):
            self._capture_li = True

    def handle_endtag(self, tag):
        if not self._stack:
            return
        while self._stack and self._stack[-1] != tag:
            self._stack.pop()
        if self._stack and self._stack[-1] == tag:
            self._stack.pop()
        if not self._in_plugin:
            return
        if tag == "h2":
            self._capture_name = False
        if tag == "span":
            self._capture_price = False
        if tag == "li":
            self._capture_li = False
        if tag == "ul":
            self._current_list = None
        if tag == "div":
            # End of plugin card
            if self._current.get("id"):
                # normalize whitespace
                self._current["name"] = self._current["name"].strip()
                self.plugins.append(self._current)
            self._current = {}
            self._in_plugin = False
            self._capture_name = False
            self._capture_price = False
            self._current_list = None
            self._capture_li = False

    def handle_data(self, data):
        if not self._in_plugin:
            return
        if self._capture_name:
            self._current["name"] += data
        elif self._capture_price:
            # may get called multiple times; accumulate then parse later
            existing = self._current.get("_price_raw", "")
            self._current["_price_raw"] = (existing + data)
            parsed = _strip_currency_to_int(self._current.get("_price_raw", ""))
            self._current["price_html"] = parsed
        elif self._capture_li and self._current_list:
            text = data.strip()
            if text:
                if self._current_list == "compatibility":
                    self._current["compatible_apps"].append(text)
                elif self._current_list == "tags":
                    self._current["categories_html"].append(text)


def _parse_html_plugins(text: str) -> Optional[Dict[str, Dict[str, Any]]]:
    try:
        parser = PluginHTMLParser()
        parser.feed(text)
        result: Dict[str, Dict[str, Any]] = {}
        for p in parser.plugins:
            pid = p.get("id")
            if not pid:
                continue
            result[pid] = {
                "id": pid,
                "name_html": p.get("name") if p.get("name") != "" else None,
                "price_html": p.get("price_html"),
                "compatible_apps": p.get("compatible_apps", []),
                "categories_html": p.get("categories_html", []),
            }
        return result
    except Exception:
        return None


def _parse_csv_plugins(rows: List[Dict[str, str]]) -> Optional[Dict[str, Dict[str, Any]]]:
    try:
        result: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            pid = (r.get("id") or "").strip()
            if not pid:
                return None
            name = (r.get("name") or "").strip()
            dp = r.get("declared_price")
            price_csv = None
            try:
                price_csv = int(str(dp).strip())
            except Exception:
                return None
            cats = (r.get("categories") or "").split(";")
            cats_clean = [c.strip() for c in cats if c.strip() != ""]
            result[pid] = {
                "id": pid,
                "name_csv": name if name != "" else None,
                "price_csv": price_csv,
                "categories_csv": cats_clean,
            }
        return result
    except Exception:
        return None


def _compute_union_ids(html_map: Dict[str, Any], csv_map: Dict[str, Any]) -> List[str]:
    s = set()
    s.update(html_map.keys())
    s.update(csv_map.keys())
    return sorted(s)


def _normalize_name(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    return s.strip()


def _name_consistent(html_name: Optional[str], csv_name: Optional[str]) -> bool:
    if html_name is None or csv_name is None:
        return False
    return html_name.strip().lower() == csv_name.strip().lower()


def _price_consistent(html_price: Optional[int], csv_price: Optional[int]) -> bool:
    if html_price is None or csv_price is None:
        return False
    return int(html_price) == int(csv_price)


def _categories_overlap(ch: Optional[List[str]], cc: Optional[List[str]]) -> List[str]:
    if not ch or not cc:
        return []
    cc_set = set([c for c in cc])
    overlap = [c for c in ch if c in cc_set]
    return overlap


def _expected_catalog(html_map: Dict[str, Any], csv_map: Dict[str, Any]) -> List[Dict[str, Any]]:
    ids = _compute_union_ids(html_map, csv_map)
    catalog: List[Dict[str, Any]] = []
    for pid in ids:
        h = html_map.get(pid, {})
        c = csv_map.get(pid, {})
        name_html = h.get("name_html")
        name_csv = c.get("name_csv")
        price_html = h.get("price_html")
        price_csv = c.get("price_csv")
        categories_html = h.get("categories_html", None if not h else [])
        categories_csv = c.get("categories_csv", None if not c else [])
        compatible_apps = h.get("compatible_apps", None if not h else [])
        cat_overlap = _categories_overlap(categories_html or [], categories_csv or [])
        obj = {
            "id": pid,
            "name_html": name_html if name_html is not None else None,
            "name_csv": name_csv if name_csv is not None else None,
            "price_html": price_html if price_html is not None else None,
            "price_csv": price_csv if price_csv is not None else None,
            "categories_html": categories_html if categories_html is not None else [],
            "categories_csv": categories_csv if categories_csv is not None else [],
            "compatible_apps": compatible_apps if compatible_apps is not None else [],
            "name_consistent": _name_consistent(name_html, name_csv),
            "price_consistent": _price_consistent(price_html, price_csv),
            "categories_overlap": cat_overlap,
        }
        catalog.append(obj)
    return catalog


def _validate_catalog_structure(catalog: Any) -> bool:
    if not isinstance(catalog, list):
        return False
    required_keys = {
        "id",
        "name_html",
        "name_csv",
        "price_html",
        "price_csv",
        "categories_html",
        "categories_csv",
        "compatible_apps",
        "name_consistent",
        "price_consistent",
        "categories_overlap",
    }
    for item in catalog:
        if not isinstance(item, dict):
            return False
        keys = set(item.keys())
        if keys != required_keys:
            return False
        # type checks
        if not isinstance(item["id"], str):
            return False
        if item["name_html"] is not None and not isinstance(item["name_html"], str):
            return False
        if item["name_csv"] is not None and not isinstance(item["name_csv"], str):
            return False
        if item["price_html"] is not None and not isinstance(item["price_html"], int):
            return False
        if item["price_csv"] is not None and not isinstance(item["price_csv"], int):
            return False
        if not isinstance(item["categories_html"], list):
            return False
        if not isinstance(item["categories_csv"], list):
            return False
        if not isinstance(item["compatible_apps"], list):
            return False
        if not isinstance(item["name_consistent"], bool):
            return False
        if not isinstance(item["price_consistent"], bool):
            return False
        if not isinstance(item["categories_overlap"], list):
            return False
        # ensure list entries are strings
        for k in ("categories_html", "categories_csv", "compatible_apps", "categories_overlap"):
            for v in item[k]:
                if not isinstance(v, str):
                    return False
    return True


def _catalog_ids_sorted(catalog: List[Dict[str, Any]]) -> Tuple[bool, List[str]]:
    ids = [item["id"] for item in catalog]
    return ids == sorted(ids), ids


def _load_discrepancies_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            # Validate header columns
            if reader.fieldnames != ["id", "issue_type", "html_value", "csv_value"]:
                return None
            return rows
    except Exception:
        return None


def _compute_expected_discrepancies(expected_catalog: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for item in expected_catalog:
        pid = item["id"]
        if not item["name_consistent"]:
            rows.append({
                "id": pid,
                "issue_type": "name_mismatch",
                "html_value": "" if item["name_html"] is None else item["name_html"],
                "csv_value": "" if item["name_csv"] is None else item["name_csv"],
            })
        if not item["price_consistent"]:
            rows.append({
                "id": pid,
                "issue_type": "price_mismatch",
                "html_value": "" if item["price_html"] is None else str(item["price_html"]),
                "csv_value": "" if item["price_csv"] is None else str(item["price_csv"]),
            })
    return rows


def _compare_discrepancies(expected: List[Dict[str, str]], actual: List[Dict[str, str]]) -> bool:
    # Compare as unordered sets of tuples
    def norm_row(r: Dict[str, str]) -> Tuple[str, str, str, str]:
        return (
            (r.get("id") or "").strip(),
            (r.get("issue_type") or "").strip(),
            (r.get("html_value") or "").strip(),
            (r.get("csv_value") or "").strip(),
        )
    exp_set = set(norm_row(r) for r in expected)
    act_set = set(norm_row(r) for r in actual)
    return exp_set == act_set


def _word_count(text: str) -> int:
    # Count by whitespace splitting to keep it deterministic with instructions
    return len(text.strip().split())


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "catalog_json_structure": 0.0,
        "catalog_union_ids_sorted": 0.0,
        "catalog_values_correct": 0.0,
        "discrepancies_csv_content": 0.0,
        "email_rewrite_structure": 0.0,
        "email_rewrite_plugins_sentence": 0.0,
        "email_rewrite_cleanliness": 0.0,
    }

    # Load inputs
    html_path = workspace / "input" / "plugins.html"
    csv_path = workspace / "input" / "plugins.csv"
    email_path = workspace / "input" / "draft_email.txt"

    html_text = _read_text(html_path)
    csv_rows = _load_csv_dicts(csv_path)
    email_text = _read_text(email_path)

    if html_text is None or csv_rows is None:
        # Cannot compute expected outputs; all dependent checks remain 0.0
        return scores

    html_map = _parse_html_plugins(html_text) or {}
    csv_map = _parse_csv_plugins(csv_rows) or {}
    if not html_map or not csv_map:
        # Parsing failed or maps empty; keep zeros
        return scores

    expected_catalog = _expected_catalog(html_map, csv_map)

    # Validate outputs/catalog.json
    catalog_path = workspace / "outputs" / "catalog.json"
    catalog_json = _load_json(catalog_path)
    if catalog_json is not None and _validate_catalog_structure(catalog_json):
        scores["catalog_json_structure"] = 1.0
        # Check union ids and sorting
        ok_sorted, ids_in_catalog = _catalog_ids_sorted(catalog_json)
        expected_ids = [item["id"] for item in expected_catalog]
        if ok_sorted and ids_in_catalog == expected_ids:
            scores["catalog_union_ids_sorted"] = 1.0
        # Check values correctness against expected
        try:
            # Map expected by id
            exp_by_id = {item["id"]: item for item in expected_catalog}
            all_ok = True
            for obj in catalog_json:
                pid = obj["id"]
                exp = exp_by_id.get(pid)
                if exp is None:
                    all_ok = False
                    break
                # Compare fields exactly
                fields = [
                    "name_html",
                    "name_csv",
                    "price_html",
                    "price_csv",
                    "categories_html",
                    "categories_csv",
                    "compatible_apps",
                    "name_consistent",
                    "price_consistent",
                    "categories_overlap",
                ]
                for f in fields:
                    if obj.get(f) != exp.get(f):
                        all_ok = False
                        break
                if not all_ok:
                    break
            if all_ok:
                scores["catalog_values_correct"] = 1.0
        except Exception:
            pass

    # Validate outputs/discrepancies.csv
    discrepancies_path = workspace / "outputs" / "discrepancies.csv"
    discrepancies_rows = _load_discrepancies_csv(discrepancies_path)
    if discrepancies_rows is not None:
        # Compare with expected rows computed from expected_catalog
        expected_discrepancies = _compute_expected_discrepancies(expected_catalog)
        if _compare_discrepancies(expected_discrepancies, discrepancies_rows):
            scores["discrepancies_csv_content"] = 1.0

    # Validate outputs/email_rewrite.txt
    email_out_path = workspace / "outputs" / "email_rewrite.txt"
    email_out_text = _read_text(email_out_path)
    if email_out_text is not None and email_text is not None:
        # Extract original CTA line
        original_cta = None
        for line in email_text.splitlines():
            if line.strip().startswith("CTA:"):
                original_cta = line.rstrip("\n")
                break
        # Structure: body as a single paragraph and CTA on its own line unchanged
        lines = email_out_text.splitlines()
        # Remove trailing empty lines for evaluation
        trimmed_lines = [ln for ln in lines if ln is not None]
        # Find CTA line indices
        cta_indices = [i for i, ln in enumerate(trimmed_lines) if ln.strip().startswith("CTA:")]
        structure_ok = False
        body_line = ""
        if original_cta is not None and cta_indices:
            # Choose first CTA index as the CTA line; require it equals exactly original
            cta_idx = cta_indices[0]
            if trimmed_lines[cta_idx] == original_cta and cta_idx >= 1:
                # Body is lines before CTA. Require single non-empty line paragraph (no blank lines)
                body_candidate_lines = [ln for ln in trimmed_lines[:cta_idx] if ln.strip() != ""]
                if len(body_candidate_lines) == 1:
                    body_line = body_candidate_lines[0]
                    # Ensure no 'Subject:' present anywhere
                    if "Subject:" not in body_line and "Subject:" not in email_out_text:
                        # Ensure CTA is the last non-empty line
                        after_cta_nonempty = any(ln.strip() != "" for ln in trimmed_lines[cta_idx + 1:])
                        if not after_cta_nonempty:
                            structure_ok = True
        if structure_ok:
            scores["email_rewrite_structure"] = 1.0

        # Validate sentence with plugin names
        # Build expected plugin sentence from expected_catalog using name_html and sorted by id
        expected_names = [item["name_html"] for item in expected_catalog]
        # Ensure names exist (if None, skip)
        expected_names = [n for n in expected_names if n is not None]
        expected_sentence_start = "Current marketplace plugins: "
        expected_sentence = expected_sentence_start + "; ".join(expected_names)
        contains_sentence = False
        if body_line:
            if expected_sentence in body_line:
                contains_sentence = True
        if contains_sentence:
            scores["email_rewrite_plugins_sentence"] = 1.0

        # Cleanliness checks: no exclamation marks, no double spaces, <= 120 words
        cleanliness_ok = False
        if body_line:
            if "!" not in body_line and "  " not in body_line:
                if _word_count(body_line) <= 120:
                    cleanliness_ok = True
        if cleanliness_ok:
            scores["email_rewrite_cleanliness"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()