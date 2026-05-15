import json
import csv
from pathlib import Path
from html.parser import HTMLParser


def _read_text_safe(path: Path):
    try:
        return path.read_text(encoding="utf-8"), None
    except Exception as e:
        return None, str(e)


def _load_json_safe(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text), None
    except Exception as e:
        return None, str(e)


def _parse_simple_yaml(path: Path):
    content, err = _read_text_safe(path)
    if err or content is None:
        return None, err or "failed to read yaml"
    data = {}
    try:
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            if " #" in val:
                val = val.split(" #", 1)[0].strip()
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            elif val.startswith("'") and val.endswith("'"):
                val = val[1:-1]
            else:
                try:
                    if "." in val:
                        val = float(val)
                        if int(val) == val:
                            val = int(val)
                    else:
                        val = int(val)
                except Exception:
                    low = val.lower()
                    if low == "true":
                        val = True
                    elif low == "false":
                        val = False
                    elif low in ("null", "none", "~"):
                        val = None
                    else:
                        val = val
            data[key] = val
        return data, None
    except Exception as e:
        return None, str(e)


class ReadingListParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.books = []
        self._in_book = False
        self._current = None
        self._current_field = None

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "li":
            cls = attrs_dict.get("class", "")
            if isinstance(cls, str) and "book" in cls.split():
                self._in_book = True
                self._current = {
                    "title": "",
                    "author": "",
                    "region": attrs_dict.get("data-region", "") or "",
                    "year": attrs_dict.get("data-year", ""),
                    "rating": attrs_dict.get("data-rating", ""),
                }
        if self._in_book and tag == "span":
            cls = attrs_dict.get("class", "")
            if cls == "title":
                self._current_field = "title"
            elif cls == "author":
                self._current_field = "author"

    def handle_endtag(self, tag):
        if tag == "li" and self._in_book:
            if self._current is not None:
                try:
                    self._current["year"] = int(self._current.get("year", ""))
                except Exception:
                    self._current["year"] = self._current.get("year", "")
                try:
                    self._current["rating"] = float(self._current.get("rating", ""))
                except Exception:
                    self._current["rating"] = self._current.get("rating", "")
                for k in ("title", "author", "region"):
                    if isinstance(self._current.get(k), str):
                        self._current[k] = self._current[k].strip()
                self.books.append(self._current)
            self._in_book = False
            self._current = None
            self._current_field = None
        elif self._in_book and tag == "span":
            self._current_field = None

    def handle_data(self, data):
        if self._in_book and self._current_field in ("title", "author"):
            existing = self._current.get(self._current_field, "")
            self._current[self._current_field] = (existing + data).strip()


def _parse_reading_list_html(path: Path):
    text, err = _read_text_safe(path)
    if err or text is None:
        return None, err or "failed to read html"
    try:
        parser = ReadingListParser()
        parser.feed(text)
        books = []
        for b in parser.books:
            title = b.get("title", "").strip()
            author = b.get("author", "").strip()
            region = b.get("region", "").strip()
            year = b.get("year")
            rating = b.get("rating")
            books.append({
                "title": title,
                "author": author,
                "region": region,
                "year": int(year) if isinstance(year, int) else year,
                "rating": float(rating) if isinstance(rating, float) or isinstance(rating, int) else rating,
            })
        return books, None
    except Exception as e:
        return None, str(e)


def _canonical_record(rec):
    try:
        title = rec.get("title", "").strip()
        author = rec.get("author", "").strip()
        region = rec.get("region", "").strip()
        year = rec.get("year")
        rating = rec.get("rating")
        year_int = int(year)
        rating_f = float(rating)
        return (title, author, region, year_int, round(rating_f, 3))
    except Exception:
        return None


def _compute_aggregates(books, decimals=2):
    counts_by_region = {}
    ratings = []
    ratings_by_region = {}
    for b in books:
        region = b["region"]
        counts_by_region[region] = counts_by_region.get(region, 0) + 1
        r = float(b["rating"])
        ratings.append(r)
        ratings_by_region.setdefault(region, []).append(r)
    total_titles = len(books)
    avg_overall = round(sum(ratings) / total_titles, int(decimals)) if total_titles > 0 else 0.0
    avg_by_region = {region: round(sum(vals) / len(vals), int(decimals)) for region, vals in ratings_by_region.items()}
    return {
        "total_titles": total_titles,
        "counts_by_region": counts_by_region,
        "average_rating_overall": avg_overall,
        "average_rating_by_region": avg_by_region,
    }


def _load_csv_with_headers(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            headers = reader.fieldnames
            return headers, rows, None
    except Exception as e:
        return None, None, str(e)


def _select_and_rank(books, target_region, top_k):
    selected = [b for b in books if b.get("region") == target_region]
    selected_sorted = sorted(selected, key=lambda b: (-float(b["rating"]), -int(b["year"]), b["title"]))
    return selected_sorted[:top_k]


def _contains_any(text, substrs):
    t = text.lower()
    return any(s.lower() in t for s in substrs)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "environment_artifacts": 0.0,
        "extracted_json_structure": 0.0,
        "extracted_json_matches_source": 0.0,
        "aggregates_json_correct": 0.0,
        "topk_csv_correct": 0.0,
        "validation_report_passes": 0.0,
        "email_draft_content": 0.0,
        "email_rewrite_content": 0.0,
    }

    dockerfile = workspace / "Dockerfile"
    requirements = workspace / "requirements.txt"
    scripts_dir = workspace / "scripts"
    has_docker = dockerfile.exists()
    has_venv_artifacts = requirements.exists() and scripts_dir.exists() and any(p.suffix == ".sh" for p in scripts_dir.glob("*.sh"))
    if has_docker or has_venv_artifacts:
        scores["environment_artifacts"] = 1.0

    config_path = workspace / "input" / "config.yaml"
    config, config_err = _parse_simple_yaml(config_path)
    target_region = None
    top_k = None
    avg_round_decimals = 2
    if config and isinstance(config, dict):
        target_region = config.get("target_region")
        top_k = config.get("top_k")
        avg_round_decimals = config.get("avg_round_decimals", 2)
        try:
            if top_k is not None:
                top_k = int(top_k)
        except Exception:
            top_k = None
        try:
            avg_round_decimals = int(avg_round_decimals)
        except Exception:
            avg_round_decimals = 2

    html_path = workspace / "input" / "reading_list.html"
    expected_books, html_err = _parse_reading_list_html(html_path)

    extracted_path = workspace / "output" / "extracted.json"
    extracted_data, extracted_err = _load_json_safe(extracted_path)
    structure_ok = False
    matches_source = False
    if extracted_data is not None and isinstance(extracted_data, list):
        required_keys = {"title", "author", "region", "year", "rating"}
        objs_ok = True
        for obj in extracted_data:
            if not isinstance(obj, dict):
                objs_ok = False
                break
            keys = set(obj.keys())
            if keys != required_keys:
                objs_ok = False
                break
            if not isinstance(obj["title"], str) or not isinstance(obj["author"], str) or not isinstance(obj["region"], str):
                objs_ok = False
                break
            if not isinstance(obj["year"], int):
                objs_ok = False
                break
            if not (isinstance(obj["rating"], float) or isinstance(obj["rating"], int)):
                objs_ok = False
                break
        if objs_ok:
            structure_ok = True
        if expected_books is not None:
            def canon_list(lst):
                out = []
                for rec in lst:
                    c = _canonical_record(rec)
                    if c is None:
                        return None
                    out.append(c)
                return out
            exp_canon = canon_list(expected_books)
            got_canon = canon_list(extracted_data)
            if exp_canon is not None and got_canon is not None:
                from collections import Counter
                if Counter(exp_canon) == Counter(got_canon):
                    matches_source = True
    scores["extracted_json_structure"] = 1.0 if structure_ok else 0.0
    scores["extracted_json_matches_source"] = 1.0 if matches_source else 0.0

    aggregates_path = workspace / "output" / "aggregates.json"
    aggregates_data, aggregates_err = _load_json_safe(aggregates_path)
    aggregates_ok = False
    if aggregates_data is not None and isinstance(aggregates_data, dict) and isinstance(extracted_data, list):
        required_agg_keys = {"total_titles", "counts_by_region", "average_rating_overall", "average_rating_by_region"}
        if set(aggregates_data.keys()) == required_agg_keys:
            try:
                expected_from_extracted = _compute_aggregates(extracted_data, decimals=avg_round_decimals)
                if (
                    isinstance(aggregates_data.get("total_titles"), int)
                    and isinstance(aggregates_data.get("counts_by_region"), dict)
                    and isinstance(aggregates_data.get("average_rating_overall"), (int, float))
                    and isinstance(aggregates_data.get("average_rating_by_region"), dict)
                ):
                    same = True
                    if aggregates_data["total_titles"] != expected_from_extracted["total_titles"]:
                        same = False
                    if aggregates_data["counts_by_region"] != expected_from_extracted["counts_by_region"]:
                        same = False
                    def _f(v): return round(float(v), avg_round_decimals)
                    if _f(aggregates_data["average_rating_overall"]) != expected_from_extracted["average_rating_overall"]:
                        same = False
                    got_avgs = {k: _f(v) for k, v in aggregates_data["average_rating_by_region"].items()}
                    if got_avgs != expected_from_extracted["average_rating_by_region"]:
                        same = False
                    if same:
                        aggregates_ok = True
            except Exception:
                aggregates_ok = False
    scores["aggregates_json_correct"] = 1.0 if aggregates_ok else 0.0

    csv_ok = False
    if top_k is not None:
        top_csv_path = workspace / "output" / f"ne_top{top_k}.csv"
        headers, rows, csv_err = _load_csv_with_headers(top_csv_path)
        if headers is not None and rows is not None and isinstance(extracted_data, list) and target_region is not None:
            headers_ok = headers == ["title", "author", "year", "rating"]
            count_ok = len(rows) == int(top_k)
            try:
                parsed_rows = []
                for r in rows:
                    title = r.get("title", "").strip()
                    author = r.get("author", "").strip()
                    year = int(r.get("year"))
                    rating = float(r.get("rating"))
                    parsed_rows.append({"title": title, "author": author, "year": year, "rating": rating})
                index = {}
                for b in extracted_data:
                    key = (b["title"].strip(), b["author"].strip(), int(b["year"]), float(b["rating"]))
                    index.setdefault(key, b["region"].strip())
                all_region_ok = True
                for r in parsed_rows:
                    key = (r["title"], r["author"], r["year"], float(r["rating"]))
                    reg = index.get(key)
                    if reg != target_region:
                        all_region_ok = False
                        break
                expected_top = _select_and_rank(extracted_data, target_region, int(top_k))
                expected_seq = [(e["title"], e["author"], int(e["year"]), float(e["rating"])) for e in expected_top]
                got_seq = [(r["title"], r["author"], r["year"], float(r["rating"])) for r in parsed_rows]
                order_ok = got_seq == expected_seq
                if headers_ok and count_ok and all_region_ok and order_ok:
                    csv_ok = True
            except Exception:
                csv_ok = False
    scores["topk_csv_correct"] = 1.0 if csv_ok else 0.0

    validation_ok = False
    report_path = workspace / "output" / "validation_report.txt"
    report_text, report_err = _read_text_safe(report_path)
    if report_text is not None:
        checks = ["total_titles", "counts_by_region", "average_rating_overall", "average_rating_by_region"]
        has_all = True
        for chk in checks:
            found = False
            for line in report_text.splitlines():
                if chk in line and "PASS" in line.upper():
                    found = True
                    break
            if not found:
                has_all = False
                break
        overall_pass = any(("overall" in line.lower()) and ("pass" in line.lower()) for line in report_text.splitlines())
        if has_all and overall_pass:
            validation_ok = True
    scores["validation_report_passes"] = 1.0 if validation_ok else 0.0

    email_draft_ok = False
    email_draft_path = workspace / "output" / "email_draft.txt"
    draft_text, draft_err = _read_text_safe(email_draft_path)
    if draft_text is not None and isinstance(extracted_data, list) and target_region is not None and top_k is not None:
        has_command = _contains_any(draft_text, ["pip ", "python ", "docker ", "bash ", "sh ", "./scripts", "scripts/"])
        agg_vals = None
        if aggregates_data and isinstance(aggregates_data, dict):
            agg_vals = aggregates_data
        elif isinstance(extracted_data, list):
            agg_vals = _compute_aggregates(extracted_data, decimals=avg_round_decimals)
        total_titles = None
        avg_overall = None
        if agg_vals:
            total_titles = agg_vals.get("total_titles")
            avg_overall = agg_vals.get("average_rating_overall")
        has_total_titles = (str(total_titles) in draft_text) if total_titles is not None else False
        has_avg_overall = False
        if avg_overall is not None:
            avg_str = f"{float(avg_overall):.{avg_round_decimals}f}"
            if avg_str in draft_text:
                has_avg_overall = True
        expected_top = _select_and_rank(extracted_data, target_region, int(top_k)) if (isinstance(extracted_data, list) and target_region is not None and top_k is not None) else []
        titles_ok = all(t["title"] in draft_text for t in expected_top)
        has_topk_value = str(int(top_k)) in draft_text
        if has_command and has_total_titles and has_avg_overall and titles_ok and has_topk_value:
            email_draft_ok = True
    scores["email_draft_content"] = 1.0 if email_draft_ok else 0.0

    email_rewrite_ok = False
    email_rewrite_path = workspace / "output" / "email_rewrite.txt"
    rewrite_text, rewrite_err = _read_text_safe(email_rewrite_path)
    if rewrite_text is not None and draft_text is not None and target_region is not None and top_k is not None:
        shorter = len(rewrite_text) < len(draft_text)
        has_us = _contains_any(rewrite_text, ["U.S", "US", "U.S.", "United States"])
        has_ne = _contains_any(rewrite_text, ["North East", "North East England"])
        expected_top = _select_and_rank(extracted_data if isinstance(extracted_data, list) else [], target_region, int(top_k)) if (isinstance(extracted_data, list) and target_region is not None and top_k is not None) else []
        includes_one_title = any(t["title"] in rewrite_text for t in expected_top) if expected_top else False
        includes_topk = str(int(top_k)) in rewrite_text
        different = rewrite_text != draft_text
        if shorter and has_us and has_ne and includes_one_title and includes_topk and different:
            email_rewrite_ok = True
    scores["email_rewrite_content"] = 1.0 if email_rewrite_ok else 0.0

    return scores


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Grader for reading list pipeline")
    parser.add_argument("workspace", nargs="?", default=".", help="Path to workspace")
    args = parser.parse_args()
    result = grade([], args.workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()