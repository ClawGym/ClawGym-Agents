import json
import csv
import re
import sys
from pathlib import Path
from html.parser import HTMLParser


def read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_safe(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_csv_dicts_safe(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return rows, reader.fieldnames
    except Exception:
        return None, None


class UsedPricesHTMLParser(HTMLParser):
    def __init__(self, target_table_id: str):
        super().__init__()
        self.target_table_id = target_table_id
        self.in_target_table = False
        self.current_tag_stack = []
        self.rows = []
        self.current_row = []
        self.capture_text = False

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        self.current_tag_stack.append(tag)
        if tag == "table" and attrs_dict.get("id") == self.target_table_id:
            self.in_target_table = True
        if self.in_target_table and tag in ("td", "th"):
            self.capture_text = True

    def handle_endtag(self, tag):
        if not self.current_tag_stack:
            return
        if self.in_target_table and tag == "tr":
            # finalize row if it has tds (exclude header with th only)
            if self.current_row:
                self.rows.append(self.current_row)
            self.current_row = []
        if self.in_target_table and tag in ("td", "th"):
            self.capture_text = False
        popped = self.current_tag_stack.pop()
        if popped == "table" and self.in_target_table:
            self.in_target_table = False

    def handle_data(self, data):
        if self.in_target_table and self.capture_text:
            text = data.strip()
            if text != "":
                self.current_row.append(text)


def parse_used_prices_from_html(html_text: str) -> dict:
    parser = UsedPricesHTMLParser("used-prices")
    parser.feed(html_text)
    # Expect rows from both header and body; we only want data rows with two cells and where second is a price
    records = {}
    for row in parser.rows:
        # Rows may come with header or data; for data we expect two cells and a $ in second cell
        if len(row) >= 2 and any(ch.isdigit() for ch in row[1]):
            title = row[0].strip()
            price_str = row[1].strip()
            # Remove currency symbol and commas
            price_num_str = re.sub(r"[^0-9.\-]", "", price_str)
            try:
                price = float(price_num_str)
            except Exception:
                continue
            records[title] = price
    return records


def compute_expected_metrics(workspace: Path):
    # Replicate the logic from tools/summarize_album_data.py deterministically without modifying files
    input_json = workspace / "input" / "library.json"
    input_costs = workspace / "input" / "pressing_costs.csv"

    library = load_json_safe(input_json)
    if library is None or not isinstance(library, list):
        return None

    costs_rows, header = load_csv_dicts_safe(input_costs)
    if costs_rows is None:
        return None
    costs = {}
    try:
        for row in costs_rows:
            fmt = (row.get("format") or "").strip()
            unit = (row.get("unit_cost_usd") or "").strip()
            costs[fmt] = float(unit)
    except Exception:
        return None

    physical_formats = {"Vinyl", "CD"}

    total = len(library)
    physical_count = sum(1 for item in library if item.get("format") in physical_formats)
    digital_count = sum(1 for item in library if item.get("format") == "Digital")

    years = [item.get("year") for item in library if isinstance(item.get("year"), int)]
    avg_year = round(sum(years) / len(years), 1) if years else None

    bitrates = [item.get("bitrate_kbps") for item in library if isinstance(item.get("bitrate_kbps"), (int, float))]
    avg_bitrate = round(sum(bitrates) / len(bitrates), 1) if bitrates else None

    replacement_cost = 0.0
    try:
        for item in library:
            fmt = item.get("format")
            if fmt not in costs:
                return None
            replacement_cost += costs[fmt]
    except Exception:
        return None

    physical_share_percent = round((physical_count / total) * 100.0, 2) if total else 0.0

    metrics = {
        "total_count": total,
        "physical_count": physical_count,
        "digital_count": digital_count,
        "physical_share_percent": physical_share_percent,
        "avg_year": avg_year,
        "avg_bitrate_digital_kbps": avg_bitrate,
        "est_replacement_cost_usd": round(replacement_cost, 2),
    }
    return metrics


def extract_section_lines(md_text: str, title: str) -> list:
    # Find a markdown header line matching the given title (case-insensitive)
    lines = md_text.splitlines()
    start_idx = None
    header_pattern = re.compile(rf"^\s{0,3}#{1,6}\s*{re.escape(title)}\s*$", re.IGNORECASE)
    plain_pattern = re.compile(rf"^\s*{re.escape(title)}\s*$", re.IGNORECASE)
    for i, line in enumerate(lines):
        if header_pattern.match(line) or plain_pattern.match(line):
            start_idx = i
            break
    if start_idx is None:
        return []
    # Section lines after header until next markdown header or EOF
    section = []
    for j in range(start_idx + 1, len(lines)):
        if re.match(r"^\s{0,3}#{1,6}\s+\S+", lines[j]):
            break
        section.append(lines[j])
    return section


def extract_bullets(section_lines: list) -> list:
    bullets = []
    for line in section_lines:
        if re.match(r"^\s*[-*]\s+", line):
            bullets.append(line.strip())
    return bullets


def find_line_with_label(bullets: list, label_substring: str) -> str:
    for line in bullets:
        if label_substring.lower() in line.lower():
            return line
    return ""


def extract_first_number(line: str):
    # Extract first number possibly with commas or $ and percent; returns (float_value, raw_number_string)
    # We capture sequences of digits with optional decimal part
    # We avoid years in parentheses by just taking first numeric-looking token
    # Remove currency symbols for parsing but keep raw for string match
    m = re.search(r"[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?|[-+]?\d+(?:\.\d+)?", line)
    if not m:
        return None, None
    raw = m.group(0)
    cleaned = re.sub(r"[,\$]", "", raw)
    try:
        return float(cleaned), raw
    except Exception:
        return None, raw


def contains_percent(line: str) -> bool:
    return "%" in line


def mentions_usd(line: str) -> bool:
    return ("usd" in line.lower()) or ("$" in line)


def extract_quotes_from_notes(notes_text: str) -> list:
    quotes = []
    for line in notes_text.splitlines():
        line = line.strip()
        if line.startswith("- "):
            # find content between first " and last "
            if '"' in line:
                parts = line.split('"')
                if len(parts) >= 3:
                    quote = parts[1]
                    if quote:
                        quotes.append(quote)
    return quotes


def count_verbatim_quotes_with_attribution(article_text: str, quotes: list) -> int:
    count = 0
    text_lower = article_text.lower()
    for q in quotes:
        pattern = f"\"{re.escape(q)}\""
        if re.search(pattern, article_text):
            # find window around match to check for 'personal notes'
            for m in re.finditer(pattern, article_text):
                start = max(0, m.start() - 100)
                end = min(len(article_text), m.end() + 100)
                window = article_text[start:end].lower()
                if "personal notes" in window:
                    count += 1
                    break
    return count


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "metrics_json_exists": 0.0,
        "metrics_json_content_correct": 0.0,
        "used_prices_csv_exists": 0.0,
        "used_prices_csv_header_and_numeric": 0.0,
        "used_prices_csv_matches_html": 0.0,
        "article_exists": 0.0,
        "article_word_count_600_900": 0.0,
        "article_stance_clear": 0.0,
        "article_includes_two_verbatim_quotes_with_attribution": 0.0,
        "article_has_data_points_section": 0.0,
        "data_point_physical_share_matches": 0.0,
        "data_point_total_albums_matches": 0.0,
        "data_point_estimated_replacement_cost_matches": 0.0,
        "data_point_median_used_kind_of_blue_matches": 0.0,
        "data_point_median_used_random_access_memories_matches": 0.0,
        "article_has_methodology_and_sources_section": 0.0,
        "methodology_sources_mentions_all_required_files": 0.0,
    }

    # Paths
    metrics_path = workspace / "outputs" / "data" / "metrics.json"
    used_prices_csv_path = workspace / "outputs" / "data" / "used_prices.csv"
    html_snapshot_path = workspace / "input" / "discogs_snapshot.html"
    article_path = workspace / "outputs" / "article" / "physical-albums-op-ed.md"
    notes_path = workspace / "input" / "notes.md"

    # Expected metrics computed from inputs
    expected_metrics = compute_expected_metrics(workspace)

    # 1) metrics.json checks
    metrics = load_json_safe(metrics_path)
    if metrics is not None and isinstance(metrics, dict):
        scores["metrics_json_exists"] = 1.0

        if expected_metrics is not None:
            # Compare values for relevant keys
            keys_to_check = [
                "total_count",
                "physical_count",
                "digital_count",
                "physical_share_percent",
                "avg_year",
                "avg_bitrate_digital_kbps",
                "est_replacement_cost_usd",
            ]
            ok = True
            for k in keys_to_check:
                if k not in metrics or metrics.get(k) != expected_metrics.get(k):
                    ok = False
                    break
            scores["metrics_json_content_correct"] = 1.0 if ok else 0.0
        else:
            scores["metrics_json_content_correct"] = 0.0
    else:
        scores["metrics_json_exists"] = 0.0
        scores["metrics_json_content_correct"] = 0.0

    # 2) used_prices.csv checks
    used_rows, used_header = load_csv_dicts_safe(used_prices_csv_path)
    if used_rows is not None and isinstance(used_rows, list):
        scores["used_prices_csv_exists"] = 1.0
        # Header and numeric
        header_ok = used_header == ["title", "median_price_usd"]
        numeric_ok = True
        for row in used_rows:
            title = (row.get("title") or "").strip()
            price_str = (row.get("median_price_usd") or "").strip()
            if not title:
                numeric_ok = False
                break
            if not re.match(r"^\s*-?\d+(?:\.\d+)?\s*$", price_str):
                numeric_ok = False
                break
            try:
                float(price_str)
            except Exception:
                numeric_ok = False
                break
        scores["used_prices_csv_header_and_numeric"] = 1.0 if (header_ok and numeric_ok) else 0.0

        # Compare to HTML snapshot
        html_text = read_text_safe(html_snapshot_path)
        if html_text is not None:
            parsed_html = parse_used_prices_from_html(html_text)
            # Build csv dict
            csv_prices = {}
            try:
                for r in used_rows:
                    csv_prices[(r.get("title") or "").strip()] = float((r.get("median_price_usd") or "").strip())
            except Exception:
                csv_prices = {}
            matches_html = False
            if parsed_html and csv_prices:
                # Exact title sets equal and per-title float equal
                if set(parsed_html.keys()) == set(csv_prices.keys()):
                    matches_html = all(abs(parsed_html[t] - csv_prices[t]) == 0.0 for t in parsed_html.keys())
            scores["used_prices_csv_matches_html"] = 1.0 if matches_html else 0.0
        else:
            scores["used_prices_csv_matches_html"] = 0.0
    else:
        scores["used_prices_csv_exists"] = 0.0
        scores["used_prices_csv_header_and_numeric"] = 0.0
        scores["used_prices_csv_matches_html"] = 0.0

    # 3) Article checks
    article_text = read_text_safe(article_path)
    if article_text is not None:
        scores["article_exists"] = 1.0

        # Word count
        words = re.findall(r"\b\w+\b", article_text)
        wc = len(words)
        if 600 <= wc <= 900:
            scores["article_word_count_600_900"] = 1.0

        # Stance clarity: contains digital/digitization + diminish + physical album(s)
        lower = article_text.lower()
        has_digit = ("digitization" in lower) or ("digital" in lower)
        has_diminish = ("diminish" in lower)
        has_physical_albums = ("physical album" in lower) or ("physical albums" in lower)
        if has_digit and has_diminish and has_physical_albums:
            scores["article_stance_clear"] = 1.0

        # Quotes from personal notes
        notes_text = read_text_safe(notes_path) or ""
        quotes = extract_quotes_from_notes(notes_text)
        if quotes:
            count_q = count_verbatim_quotes_with_attribution(article_text, quotes)
            if count_q >= 2:
                scores["article_includes_two_verbatim_quotes_with_attribution"] = 1.0

        # Data points section
        data_section_lines = extract_section_lines(article_text, "Data points")
        bullets = extract_bullets(data_section_lines)
        if data_section_lines and bullets:
            scores["article_has_data_points_section"] = 1.0

        # If we have the necessary data files parsed, check bullet contents
        # Use metrics for three values; use used_prices.csv for two values
        if expected_metrics is not None and used_rows is not None:
            # Build CSV price map
            csv_price_map = {}
            try:
                for r in used_rows:
                    title = (r.get("title") or "").strip()
                    price = float((r.get("median_price_usd") or "").strip())
                    csv_price_map[title] = price
            except Exception:
                csv_price_map = {}

            # Physical share line
            line = find_line_with_label(bullets, "Physical share")
            if line:
                # Require percent sign and exact string of metric value present
                expected_percent = expected_metrics.get("physical_share_percent")
                val_float, raw = extract_first_number(line)
                exact_str_present = f"{expected_percent}" in line
                if contains_percent(line) and val_float is not None and expected_percent is not None and abs(val_float - expected_percent) == 0.0 and exact_str_present:
                    scores["data_point_physical_share_matches"] = 1.0

            # Total albums
            line = find_line_with_label(bullets, "Total albums")
            if line:
                expected_total = expected_metrics.get("total_count")
                val_float, raw = extract_first_number(line)
                exact_str_present = f"{expected_total}" in line if expected_total is not None else False
                if val_float is not None and expected_total is not None and abs(val_float - float(expected_total)) == 0.0 and exact_str_present:
                    scores["data_point_total_albums_matches"] = 1.0

            # Estimated replacement cost
            line = find_line_with_label(bullets, "Estimated replacement cost")
            if line:
                expected_cost = expected_metrics.get("est_replacement_cost_usd")
                val_float, raw = extract_first_number(line)
                if val_float is not None and expected_cost is not None and abs(val_float - expected_cost) == 0.0 and mentions_usd(line):
                    scores["data_point_estimated_replacement_cost_matches"] = 1.0

            # Median used price for Kind of Blue
            line = ""
            for b in bullets:
                if "kind of blue" in b.lower():
                    line = b
                    break
            if line and "median" in line.lower():
                expected_kob = csv_price_map.get("Kind of Blue")
                val_float, raw = extract_first_number(line)
                if (expected_kob is not None) and (val_float is not None) and abs(val_float - expected_kob) == 0.0 and mentions_usd(line):
                    scores["data_point_median_used_kind_of_blue_matches"] = 1.0

            # Median used price for Random Access Memories
            line = ""
            for b in bullets:
                if "random access memories" in b.lower():
                    line = b
                    break
            if line and "median" in line.lower():
                expected_ram = csv_price_map.get("Random Access Memories")
                val_float, raw = extract_first_number(line)
                if (expected_ram is not None) and (val_float is not None) and abs(val_float - expected_ram) == 0.0 and mentions_usd(line):
                    scores["data_point_median_used_random_access_memories_matches"] = 1.0

        # Methodology & sources section
        meth_section_lines = extract_section_lines(article_text, "Methodology & sources")
        if meth_section_lines:
            scores["article_has_methodology_and_sources_section"] = 1.0
            meth_text = "\n".join(meth_section_lines)
            has_lib = "input/library.json" in meth_text
            has_costs = "input/pressing_costs.csv" in meth_text
            has_script = "tools/summarize_album_data.py" in meth_text
            has_html = "input/discogs_snapshot.html" in meth_text
            if has_lib and has_costs and has_script and has_html:
                scores["methodology_sources_mentions_all_required_files"] = 1.0
    else:
        # Article missing; all article-related checks remain 0.0
        pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()