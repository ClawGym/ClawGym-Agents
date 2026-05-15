import json
import sys
import csv
import re
import os
import subprocess
from pathlib import Path
from html.parser import HTMLParser


def read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def load_json_safe(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def parse_csv_safe(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, []
        header = rows[0]
        data_rows = rows[1:]
        return header, data_rows
    except Exception:
        return None, []


def try_float(s: str):
    try:
        if re.fullmatch(r"[-+]?\d+", s):
            return int(s)
        if re.fullmatch(r"[-+]?\d*\.\d+(?:[eE][-+]?\d+)?", s) or re.fullmatch(r"[-+]?\d+(?:[eE][-+]?\d+)", s):
            return float(s)
    except Exception:
        pass
    return None


def yaml_value_cast(val: str):
    v = val.strip()
    low = v.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    num = try_float(v)
    if num is not None:
        return num
    if (len(v) >= 2) and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
        return v[1:-1]
    return v


def parse_simple_yaml(path: Path):
    text = read_text_safe(path)
    if not text:
        return None
    lines = text.splitlines()
    root = {}
    stack = [(-1, root)]
    for raw in lines:
        if not raw.strip():
            continue
        if raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.rstrip()
        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        key = key.strip()
        value_part = rest.strip()
        while stack and stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1] if stack else root
        if value_part == "":
            new_dict = {}
            parent[key] = new_dict
            stack.append((indent, new_dict))
        else:
            parent[key] = yaml_value_cast(value_part)
    return root


class CatalogHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_title_h1 = False
        self.in_author_span = False
        self.in_call_number = False
        self.in_availability_span = False
        self.in_subjects_ul = False
        self.current_li = False

        self.data = {
            "id": "",
            "title": "",
            "author": "",
            "subjects": [],
            "call_number": "",
            "availability": "",
        }
        self._canonical_href = ""

    def handle_starttag(self, tag, attrs):
        attrs_dict = {k.lower(): (v if v is not None else "") for k, v in attrs}
        if tag.lower() == "link":
            rel = attrs_dict.get("rel", "").lower()
            if rel == "canonical":
                href = attrs_dict.get("href", "")
                self._canonical_href = href
                parts = [p for p in href.strip("/").split("/") if p]
                if parts:
                    self.data["id"] = parts[-1]
        elif tag.lower() == "h1":
            class_attr = attrs_dict.get("class", "")
            if any(c.strip() == "title" for c in class_attr.split()):
                self.in_title_h1 = True
        elif tag.lower() == "span":
            class_attr = attrs_dict.get("class", "")
            if any(c.strip() == "author" for c in class_attr.split()):
                self.in_author_span = True
            if any(c.strip() == "availability" for c in class_attr.split()):
                self.in_availability_span = True
        elif tag.lower() == "ul":
            ul_id = attrs_dict.get("id", "")
            if ul_id == "subjects":
                self.in_subjects_ul = True
        elif tag.lower() == "li":
            if self.in_subjects_ul:
                self.current_li = True
        elif tag.lower() == "div":
            class_attr = attrs_dict.get("class", "")
            if any(c.strip() == "call-number" for c in class_attr.split()):
                self.in_call_number = True

    def handle_endtag(self, tag):
        if tag.lower() == "h1" and self.in_title_h1:
            self.in_title_h1 = False
        elif tag.lower() == "span":
            if self.in_author_span:
                self.in_author_span = False
            if self.in_availability_span:
                self.in_availability_span = False
        elif tag.lower() == "ul" and self.in_subjects_ul:
            self.in_subjects_ul = False
        elif tag.lower() == "li":
            self.current_li = False
        elif tag.lower() == "div" and self.in_call_number:
            self.in_call_number = False

    def handle_data(self, data):
        text = data.strip()
        if not text:
            return
        if self.in_title_h1:
            self.data["title"] += (("" if self.data["title"] == "" else " ") + text)
        elif self.in_author_span:
            self.data["author"] += (("" if self.data["author"] == "" else " ") + text)
        elif self.current_li and self.in_subjects_ul:
            self.data["subjects"].append(text)
        elif self.in_call_number:
            self.data["call_number"] += (("" if self.data["call_number"] == "" else " ") + text)
        elif self.in_availability_span:
            self.data["availability"] += (("" if self.data["availability"] == "" else " ") + text)


def compute_expected_from_html(html_dir: Path):
    if not html_dir.exists():
        return []
    records = []
    for p in sorted(html_dir.glob("*.html")):
        try:
            content = p.read_text(encoding="utf-8")
        except Exception:
            continue
        parser = CatalogHTMLParser()
        try:
            parser.feed(content)
        except Exception:
            continue
        rec = {
            "id": parser.data["id"].strip(),
            "title": parser.data["title"].strip(),
            "author": parser.data["author"].strip(),
            "subjects": [s.strip() for s in parser.data["subjects"] if s.strip()],
            "call_number": parser.data["call_number"].strip(),
            "availability": parser.data["availability"].strip(),
        }
        records.append(rec)
    return records


def normalize_subjects_cell(cell: str):
    parts = [s.strip() for s in cell.split(";")]
    parts = [s for s in parts if s != ""]
    return parts


def floats_equal(a: float, b: float, tol: float = 1e-9) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def run_extract_script(workspace: Path) -> bool:
    script = workspace / "scripts" / "extract_catalog.py"
    if not script.exists():
        return False
    try:
        # If script has a shebang and is executable, try running directly
        shebang = ""
        try:
            with script.open("r", encoding="utf-8") as f:
                shebang = f.readline().strip()
        except Exception:
            shebang = ""
        if os.access(str(script), os.X_OK) and shebang.startswith("#!"):
            proc = subprocess.run(
                [str(script)],
                cwd=str(workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=20,
                check=False,
            )
            return proc.returncode == 0
        # Otherwise, try running with Python
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
            check=False,
        )
        return proc.returncode == 0
    except Exception:
        return False


def parse_fenced_code_blocks(text: str):
    blocks = []
    lines = text.splitlines()
    in_block = False
    block_lines = []
    for line in lines:
        if not in_block:
            if line.strip().startswith("```"):
                in_block = True
                block_lines = []
            else:
                continue
        else:
            if line.strip().startswith("```"):
                blocks.append("\n".join(block_lines).strip())
                in_block = False
                block_lines = []
            else:
                block_lines.append(line)
    return blocks


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "extract_script_present": 0.0,
        "items_csv_header_and_presence": 0.0,
        "items_csv_content_correct": 0.0,
        "field_stats_json_correct": 0.0,
        "extract_script_runs": 0.0,
        "input_config_title_weight_and_index": 0.0,
        "input_config_author_weight_and_index": 0.0,
        "input_config_subjects_weight_and_index_by_coverage_rule": 0.0,
        "input_config_availability_field": 0.0,
        "input_config_alias_topic_subjects": 0.0,
        "output_config_matches_updated_input": 0.0,
        "config_changes_weights_correct": 0.0,
        "config_changes_aliases_added": 0.0,
        "config_changes_availability_summary_correct": 0.0,
        "email_word_count_150_250": 0.0,
        "email_mentions_parsing_and_ranking": 0.0,
        "email_lists_config_changes": 0.0,
        "email_includes_coverage_json_codeblock": 0.0,
        "help_rewritten_word_count_leq_120": 0.0,
        "help_mentions_title_author_subjects": 0.0,
        "help_bulleted_list_constraints": 0.0,
    }

    html_dir = workspace / "input" / "catalog_pages"
    expected_records = compute_expected_from_html(html_dir)
    total_pages = len(expected_records)

    def coverage_from_records(records):
        cov = {"title": 0.0, "author": 0.0, "subjects": 0.0, "call_number": 0.0, "availability": 0.0}
        n = len(records)
        if n == 0:
            return 0, cov
        title_count = sum(1 for r in records if r.get("title", "").strip() != "")
        author_count = sum(1 for r in records if r.get("author", "").strip() != "")
        subjects_count = sum(1 for r in records if len(r.get("subjects", [])) > 0)
        call_number_count = sum(1 for r in records if r.get("call_number", "").strip() != "")
        availability_count = sum(1 for r in records if r.get("availability", "").strip() != "")
        cov["title"] = title_count / n
        cov["author"] = author_count / n
        cov["subjects"] = subjects_count / n
        cov["call_number"] = call_number_count / n
        cov["availability"] = availability_count / n
        return n, cov

    exp_total, exp_cov = coverage_from_records(expected_records)

    if (workspace / "scripts" / "extract_catalog.py").exists():
        scores["extract_script_present"] = 1.0

    items_csv = workspace / "output" / "items.csv"
    header, data_rows = parse_csv_safe(items_csv)
    if header is not None and header == ["id", "title", "author", "subjects", "call_number", "availability"]:
        scores["items_csv_header_and_presence"] = 1.0

    if header is not None and data_rows and total_pages > 0:
        csv_records = {}
        ok = True
        for row in data_rows:
            if len(row) != 6:
                ok = False
                break
            rid, title, author, subjects_cell, callnum, avail = [c.strip() for c in row]
            if rid in csv_records:
                ok = False
                break
            csv_records[rid] = {
                "title": title,
                "author": author,
                "subjects": normalize_subjects_cell(subjects_cell),
                "call_number": callnum,
                "availability": avail,
            }
        if ok:
            exp_by_id = {r["id"]: r for r in expected_records}
            if set(csv_records.keys()) == set(exp_by_id.keys()) and len(csv_records) == len(exp_by_id):
                for rid, exp in exp_by_id.items():
                    got = csv_records.get(rid, {})
                    if got.get("title", "") != exp.get("title", ""):
                        ok = False
                        break
                    if got.get("author", "") != exp.get("author", ""):
                        ok = False
                        break
                    if got.get("call_number", "") != exp.get("call_number", ""):
                        ok = False
                        break
                    if got.get("availability", "") != exp.get("availability", ""):
                        ok = False
                        break
                    exp_subj = [s.strip() for s in exp.get("subjects", [])]
                    if set(map(str.lower, got.get("subjects", []))) != set(map(str.lower, exp_subj)):
                        ok = False
                        break
        if ok:
            scores["items_csv_content_correct"] = 1.0

    field_stats_path = workspace / "output" / "field_stats.json"
    stats_obj = load_json_safe(field_stats_path)
    if stats_obj is not None and total_pages > 0:
        try:
            total_pages_val = stats_obj.get("total_pages")
            coverage_obj = stats_obj.get("coverage", {})
            checks_ok = isinstance(total_pages_val, int) and total_pages_val == exp_total
            required_keys = ["title", "author", "subjects", "call_number", "availability"]
            for k in required_keys:
                if k not in coverage_obj:
                    checks_ok = False
                    break
                v = coverage_obj[k]
                if not isinstance(v, (int, float)):
                    checks_ok = False
                    break
                if not floats_equal(v, exp_cov[k]):
                    checks_ok = False
                    break
            if checks_ok:
                scores["field_stats_json_correct"] = 1.0
        except Exception:
            pass

    if (workspace / "scripts" / "extract_catalog.py").exists():
        if run_extract_script(workspace):
            if (workspace / "output" / "items.csv").exists() and (workspace / "output" / "field_stats.json").exists():
                scores["extract_script_runs"] = 1.0

    input_config_path = workspace / "input" / "indexing_config.yaml"
    output_config_path = workspace / "output" / "indexing_config.yaml"
    input_cfg = parse_simple_yaml(input_config_path) if input_config_path.exists() else None
    output_cfg = parse_simple_yaml(output_config_path) if output_config_path.exists() else None

    subjects_target_weight = None
    if total_pages > 0:
        subj_cov = exp_cov.get("subjects", 0.0)
        subjects_target_weight = 1.5 if subj_cov >= 0.9 else 0.5

    def get_field(cfg, name):
        try:
            return cfg["indexing"]["fields"][name]
        except Exception:
            return None

    if input_cfg:
        title_field = get_field(input_cfg, "title")
        if title_field and isinstance(title_field, dict):
            if floats_equal(title_field.get("weight", None), 3.0) and bool(title_field.get("index", None)) is True:
                scores["input_config_title_weight_and_index"] = 1.0

        author_field = get_field(input_cfg, "author")
        if author_field and isinstance(author_field, dict):
            if floats_equal(author_field.get("weight", None), 1.0) and bool(author_field.get("index", None)) is True:
                scores["input_config_author_weight_and_index"] = 1.0

        subjects_field = get_field(input_cfg, "subjects")
        if subjects_field and isinstance(subjects_field, dict) and subjects_target_weight is not None:
            if floats_equal(subjects_field.get("weight", None), subjects_target_weight) and bool(subjects_field.get("index", None)) is True:
                scores["input_config_subjects_weight_and_index_by_coverage_rule"] = 1.0

        availability_field = get_field(input_cfg, "availability")
        if availability_field and isinstance(availability_field, dict):
            if bool(availability_field.get("index", None)) is False and floats_equal(availability_field.get("weight", None), 0.0):
                scores["input_config_availability_field"] = 1.0

        try:
            aliases = input_cfg["indexing"]["aliases"]
            if isinstance(aliases, dict) and aliases.get("topic") == "subjects":
                scores["input_config_alias_topic_subjects"] = 1.0
        except Exception:
            pass

    if input_cfg and output_cfg:
        try:
            if input_cfg == output_cfg:
                scores["output_config_matches_updated_input"] = 1.0
        except Exception:
            pass

    changes_path = workspace / "output" / "config_changes.json"
    changes = load_json_safe(changes_path)
    if changes is not None:
        weights_ok = False
        try:
            weights = changes.get("weights", {})
            keys = set(weights.keys())
            expected_keys = {"title", "author", "subjects"}
            if keys == expected_keys:
                before_after_ok = True
                baseline_before = {"title": 2.0, "author": 0.8, "subjects": 0.5}
                target_after = {"title": 3.0, "author": 1.0}
                if subjects_target_weight is not None:
                    target_after["subjects"] = subjects_target_weight
                for k in expected_keys:
                    w = weights.get(k, {})
                    b = w.get("before", None)
                    a = w.get("after", None)
                    if (not floats_equal(b, baseline_before[k])) or (k in target_after and not floats_equal(a, target_after[k])):
                        before_after_ok = False
                        break
                if before_after_ok:
                    weights_ok = True
        except Exception:
            weights_ok = False
        if weights_ok:
            scores["config_changes_weights_correct"] = 1.0

        try:
            aliases_added = changes.get("aliases_added", [])
            if isinstance(aliases_added, list) and "topic" in aliases_added:
                scores["config_changes_aliases_added"] = 1.0
        except Exception:
            pass

        try:
            avail = changes.get("availability_field", {})
            present_before = avail.get("present_before", None)
            final = avail.get("final", {})
            if present_before is False and isinstance(final, dict):
                if bool(final.get("index", None)) is False and floats_equal(final.get("weight", None), 0.0):
                    scores["config_changes_availability_summary_correct"] = 1.0
        except Exception:
            pass

    email_path = workspace / "output" / "email_to_product_team.md"
    email_text = read_text_safe(email_path)
    if email_text:
        words = [w for w in re.findall(r"\S+", email_text)]
        if 150 <= len(words) <= 250:
            scores["email_word_count_150_250"] = 1.0
        lower = email_text.lower()
        if any(k in lower for k in ["parse", "parsed", "parsing", "extract", "extracted", "scrap", "scraped"]) and ("search" in lower) and ("rank" in lower):
            scores["email_mentions_parsing_and_ranking"] = 1.0
        config_ok = True
        if not (re.search(r"\b3\.0\b", email_text) and re.search(r"\b1\.0\b", email_text)):
            config_ok = False
        if subjects_target_weight is not None:
            subj_str = f"{subjects_target_weight:.1f}"
            if not re.search(rf"\b{subj_str}\b", email_text):
                config_ok = False
        if not ("availability" in lower and ("not index" in lower or "non-index" in lower or "index: false" in lower or "not indexed" in lower)):
            config_ok = False
        if not (("alias" in lower and "topic" in lower and "subject" in lower) or ("topic→subjects" in email_text) or ("topic -> subjects" in email_text)):
            config_ok = False
        if config_ok:
            scores["email_lists_config_changes"] = 1.0

        stats_obj = load_json_safe(field_stats_path)
        if stats_obj is not None and "coverage" in stats_obj:
            coverage_dict = stats_obj["coverage"]
            blocks = parse_fenced_code_blocks(email_text)
            found = False
            for block in blocks:
                try:
                    parsed = json.loads(block)
                    if parsed == coverage_dict:
                        found = True
                        break
                except Exception:
                    continue
            if found:
                scores["email_includes_coverage_json_codeblock"] = 1.0

    help_path = workspace / "output" / "search_help_message_rewritten.txt"
    help_text = read_text_safe(help_path)
    if help_text:
        words = [w for w in re.findall(r"\S+", help_text)]
        if len(words) <= 120:
            scores["help_rewritten_word_count_leq_120"] = 1.0
        lower = help_text.lower()
        if ("title" in lower) and ("author" in lower) and ("subject" in lower or "subjects" in lower):
            scores["help_mentions_title_author_subjects"] = 1.0
        bullet_lines = [ln for ln in help_text.splitlines() if ln.strip().startswith(("-", "*", "•"))]
        if len(bullet_lines) <= 3:
            scores["help_bulleted_list_constraints"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()