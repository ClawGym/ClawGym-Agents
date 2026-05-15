import json
import csv
import re
import sys
from html.parser import HTMLParser
from pathlib import Path


def safe_read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_load_json(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text)
    except Exception:
        return None


def parse_overall_coverage(html_text: str) -> int | None:
    if not html_text:
        return None
    m = re.search(r"Overall coverage:\s*(\d+)\s*%", html_text, re.IGNORECASE)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


class CoverageTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_files_table = False
        self.in_tbody = False
        self.in_td = False
        self.current_row: list[str] = []
        self.rows: list[list[str]] = []
        self._table_stack = 0  # to ensure we are within the right table
        self._current_data = ""

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            attrs_dict = dict(attrs)
            if attrs_dict.get("id") == "files":
                self.in_files_table = True
                self._table_stack = 1
            elif self.in_files_table:
                self._table_stack += 1
        elif self.in_files_table and tag == "tbody":
            self.in_tbody = True
        elif self.in_files_table and self.in_tbody and tag == "tr":
            self.current_row = []
        elif self.in_files_table and self.in_tbody and tag == "td":
            self.in_td = True
            self._current_data = ""

    def handle_data(self, data):
        if self.in_files_table and self.in_tbody and self.in_td:
            self._current_data += data

    def handle_endtag(self, tag):
        if self.in_files_table and self.in_tbody and tag == "td":
            self.in_td = False
            self.current_row.append(self._current_data.strip())
            self._current_data = ""
        elif self.in_files_table and self.in_tbody and tag == "tr":
            if self.current_row:
                self.rows.append(self.current_row)
            self.current_row = []
        elif self.in_files_table and tag == "tbody":
            self.in_tbody = False
        elif tag == "table" and self.in_files_table:
            self._table_stack -= 1
            if self._table_stack <= 0:
                self.in_files_table = False

    def get_rows(self) -> list[list[str]]:
        return self.rows


def parse_coverage_table(html_text: str) -> list[dict] | None:
    try:
        parser = CoverageTableParser()
        parser.feed(html_text)
        rows = parser.get_rows()
        result = []
        for r in rows:
            if len(r) != 4:
                return None
            file_path, covered, total, pct = r
            pct_num_match = re.match(r"^\s*(\d+)\s*%\s*$", pct)
            if not pct_num_match:
                return None
            try:
                result.append(
                    {
                        "file": file_path.strip(),
                        "lines_covered": int(covered.strip()),
                        "lines_total": int(total.strip()),
                        "coverage_percent": int(pct_num_match.group(1)),
                    }
                )
            except Exception:
                return None
        return result
    except Exception:
        return None


def compute_test_stats(test_results: list[dict]) -> dict | None:
    try:
        total = len(test_results)
        passed = sum(1 for t in test_results if t.get("status") == "passed")
        failed = sum(1 for t in test_results if t.get("status") == "failed")
        # sort by duration_ms descending
        sorted_tests = sorted(
            test_results,
            key=lambda t: (t.get("duration_ms", -1)),
            reverse=True,
        )
        top5 = []
        for t in sorted_tests[:5]:
            # ensure fields present
            top5.append(
                {
                    "name": t.get("name"),
                    "module": t.get("module"),
                    "duration_ms": t.get("duration_ms"),
                    "status": t.get("status"),
                }
            )
        return {"total": total, "passed": passed, "failed": failed, "top5": top5}
    except Exception:
        return None


def safe_read_csv_dicts(path: Path) -> tuple[list[str] | None, list[dict] | None]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = [row for row in reader]
            return header, rows
    except Exception:
        return None, None


def extract_bullets_from_markdown(md_text: str) -> list[str]:
    bullets = []
    for line in md_text.splitlines():
        m = re.match(r"^\s*-\s+(.*\S)\s*$", line)
        if m:
            bullets.append(m.group(1))
    return bullets


def has_emoji(s: str) -> bool:
    # Check common emoji unicode ranges
    for ch in s:
        code = ord(ch)
        if (
            0x1F300 <= code <= 0x1F5FF
            or 0x1F600 <= code <= 0x1F64F
            or 0x1F680 <= code <= 0x1F6FF
            or 0x1F700 <= code <= 0x1F77F
            or 0x1F900 <= code <= 0x1F9FF
            or 0x1FA70 <= code <= 0x1FAFF
            or 0x2600 <= code <= 0x26FF
            or 0x2700 <= code <= 0x27BF
        ):
            return True
    return False


def contains_hedging(s: str) -> bool:
    hedges = [
        "maybe",
        "probably",
        "kinda",
        "might",
        "uh oh",
        "uh-oh",
        "sort of",
        "kind of",
        "heads up",
        "heads-up",
        "super",
        "for now",
        "kinda",
    ]
    low = s.lower()
    return any(h in low for h in hedges)


def find_numeric_tokens(s: str) -> list[str]:
    # capture numbers with optional decimal and optional %; keep exact token
    return re.findall(r"\d+(?:\.\d+)?%?", s)


def parse_targets_yaml(text: str) -> list[str] | None:
    try:
        lines = text.splitlines()
        targets: list[str] = []
        in_targets = False
        base_indent = None
        for line in lines:
            if not in_targets:
                if re.match(r"^\s*targets:\s*$", line):
                    in_targets = True
                    # compute indent level for items if needed
                    # next lines should be items
                continue
            else:
                # stop if empty or new top-level key (starts without dash and not indented more than targets)
                if re.match(r"^\s*$", line):
                    # allow blank lines within? In our simple file, we can continue
                    continue
                m_item = re.match(r"^\s*-\s+(.+?)\s*$", line)
                if m_item:
                    targets.append(m_item.group(1))
                    continue
                else:
                    # If we encounter a non-item line, stop collecting
                    break
        if not in_targets:
            return None
        return targets
    except Exception:
        return None


def load_pipeline_template_with_replacements(template_text: str, min_cov: int, targets: list[str]) -> str:
    targets_inline = "[" + ",".join(targets) + "]"
    replaced = template_text.replace("{{MIN_COVERAGE}}", str(min_cov))
    replaced = replaced.replace("{{TARGETS_INLINE}}", targets_inline)
    return replaced


def read_lines(path: Path) -> list[str] | None:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "ci_summary_counts_correct": 0.0,
        "ci_summary_coverage_correct": 0.0,
        "ci_summary_top5_correct": 0.0,
        "slow_tests_csv_correct": 0.0,
        "coverage_summary_csv_correct": 0.0,
        "notifications_line_count_match": 0.0,
        "notifications_cleaned_constraints": 0.0,
        "pipeline_min_coverage_replaced": 0.0,
        "pipeline_targets_inline_replaced": 0.0,
        "pipeline_content_matches_expected": 0.0,
    }

    # Inputs
    input_dir = workspace / "input"
    test_results_path = input_dir / "test_results.json"
    coverage_html_path = input_dir / "coverage.html"
    notifications_md_path = input_dir / "notifications.md"
    build_matrix_yaml_path = input_dir / "build_matrix.yaml"
    pipeline_template_path = input_dir / "pipeline_template.yml"

    # Outputs
    reports_dir = workspace / "reports"
    out_dir = workspace / "out"
    ci_summary_json_path = reports_dir / "ci_summary.json"
    slow_tests_csv_path = reports_dir / "slow_tests.csv"
    coverage_summary_csv_path = reports_dir / "coverage_summary.csv"
    notifications_cleaned_path = out_dir / "notifications_cleaned.txt"
    pipeline_output_path = workspace / ".ci" / "pipeline.yml"

    # Load inputs
    test_results = safe_load_json(test_results_path)
    coverage_html_text = safe_read_text(coverage_html_path)
    notifications_md_text = safe_read_text(notifications_md_path)
    build_matrix_yaml_text = safe_read_text(build_matrix_yaml_path)
    pipeline_template_text = safe_read_text(pipeline_template_path)

    # Derive expected values from inputs
    test_stats = None
    if isinstance(test_results, list):
        test_stats = compute_test_stats(test_results)

    overall_cov = None
    coverage_table = None
    if coverage_html_text is not None:
        overall_cov = parse_overall_coverage(coverage_html_text)
        coverage_table = parse_coverage_table(coverage_html_text)

    bullets = extract_bullets_from_markdown(notifications_md_text) if notifications_md_text is not None else None
    targets_list = parse_targets_yaml(build_matrix_yaml_text) if build_matrix_yaml_text is not None else None

    # 1) CI summary checks
    ci_summary = safe_load_json(ci_summary_json_path)
    if isinstance(ci_summary, dict) and test_stats is not None and overall_cov is not None:
        # counts
        try:
            if (
                ci_summary.get("total_tests") == test_stats["total"]
                and ci_summary.get("passed") == test_stats["passed"]
                and ci_summary.get("failed") == test_stats["failed"]
            ):
                scores["ci_summary_counts_correct"] = 1.0
        except Exception:
            pass

        # coverage
        try:
            if ci_summary.get("overall_coverage_percent") == overall_cov:
                scores["ci_summary_coverage_correct"] = 1.0
        except Exception:
            pass

        # top 5 slowest
        try:
            top5 = ci_summary.get("top_5_slowest")
            if isinstance(top5, list) and len(top5) == 5:
                match = True
                for i, exp in enumerate(test_stats["top5"]):
                    got = top5[i]
                    if not isinstance(got, dict):
                        match = False
                        break
                    if not (
                        got.get("name") == exp["name"]
                        and got.get("module") == exp["module"]
                        and got.get("duration_ms") == exp["duration_ms"]
                        and got.get("status") == exp["status"]
                    ):
                        match = False
                        break
                if match:
                    scores["ci_summary_top5_correct"] = 1.0
        except Exception:
            pass

    # 2) Slow tests CSV
    header, rows = safe_read_csv_dicts(slow_tests_csv_path)
    if header is not None and rows is not None and test_stats is not None:
        try:
            expected_header = ["name", "module", "duration_ms", "status"]
            if header == expected_header and len(rows) == 5:
                ok = True
                for i, exp in enumerate(test_stats["top5"]):
                    row = rows[i]
                    # All fields present
                    if set(row.keys()) != set(expected_header):
                        ok = False
                        break
                    try:
                        dur = int(row["duration_ms"])
                    except Exception:
                        ok = False
                        break
                    if not (
                        row["name"] == exp["name"]
                        and row["module"] == exp["module"]
                        and dur == exp["duration_ms"]
                        and row["status"] == exp["status"]
                    ):
                        ok = False
                        break
                if ok:
                    scores["slow_tests_csv_correct"] = 1.0
        except Exception:
            pass

    # 3) Coverage summary CSV
    cov_header, cov_rows = safe_read_csv_dicts(coverage_summary_csv_path)
    if cov_header is not None and cov_rows is not None and coverage_table is not None:
        try:
            expected_header = ["file", "lines_covered", "lines_total", "coverage_percent"]
            if cov_header == expected_header and len(cov_rows) == len(coverage_table):
                ok = True
                for i, exp in enumerate(coverage_table):
                    row = cov_rows[i]
                    if set(row.keys()) != set(expected_header):
                        ok = False
                        break
                    try:
                        lc = int(row["lines_covered"])
                        lt = int(row["lines_total"])
                        cp = int(row["coverage_percent"])
                    except Exception:
                        ok = False
                        break
                    if not (
                        row["file"] == exp["file"]
                        and lc == exp["lines_covered"]
                        and lt == exp["lines_total"]
                        and cp == exp["coverage_percent"]
                    ):
                        ok = False
                        break
                if ok:
                    scores["coverage_summary_csv_correct"] = 1.0
        except Exception:
            pass

    # 4) Notifications cleaned
    cleaned_lines = read_lines(notifications_cleaned_path)
    if cleaned_lines is not None and bullets is not None:
        # line count match
        if len(cleaned_lines) == len(bullets):
            scores["notifications_line_count_match"] = 1.0

        # constraints
        try:
            all_ok = True
            for original, cleaned in zip(bullets, cleaned_lines):
                # length <= 120
                if len(cleaned) > 120:
                    all_ok = False
                    break
                # no emoji
                if has_emoji(cleaned):
                    all_ok = False
                    break
                # remove exclamation and question marks (neutral and avoid hedging punctuation)
                if "!" in cleaned or "?" in cleaned:
                    all_ok = False
                    break
                # avoid hedging words
                if contains_hedging(cleaned):
                    all_ok = False
                    break
                # Keep numeric values unchanged (tokens like 81 or 81%)
                tokens = find_numeric_tokens(original)
                for tok in tokens:
                    if tok not in cleaned:
                        all_ok = False
                        break
                if not all_ok:
                    break
            if all_ok and len(cleaned_lines) == len(bullets):
                scores["notifications_cleaned_constraints"] = 1.0
        except Exception:
            pass

    # 5) Pipeline from template
    pipeline_output_text = safe_read_text(pipeline_output_path)
    if (
        pipeline_output_text is not None
        and pipeline_template_text is not None
        and overall_cov is not None
        and targets_list is not None
        and isinstance(targets_list, list)
        and len(targets_list) > 0
    ):
        # Expected content after replacements
        expected_pipeline_text = load_pipeline_template_with_replacements(
            pipeline_template_text, overall_cov, targets_list
        )

        # min coverage replaced
        try:
            if "{{MIN_COVERAGE}}" not in pipeline_output_text and str(overall_cov) in pipeline_output_text:
                scores["pipeline_min_coverage_replaced"] = 1.0
        except Exception:
            pass

        # targets inline replaced
        try:
            expected_inline_no_space = "[" + ",".join(targets_list) + "]"
            expected_inline_with_space = "[" + ", ".join(targets_list) + "]"
            if (
                "{{TARGETS_INLINE}}" not in pipeline_output_text
                and (expected_inline_no_space in pipeline_output_text or expected_inline_with_space in pipeline_output_text)
            ):
                scores["pipeline_targets_inline_replaced"] = 1.0
        except Exception:
            pass

        # full content match
        try:
            if pipeline_output_text == expected_pipeline_text:
                scores["pipeline_content_matches_expected"] = 1.0
        except Exception:
            pass

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()