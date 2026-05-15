import json
import sys
import subprocess
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlparse
import re
from typing import Dict, Any, List, Optional, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[Any]:
    try:
        text = _read_text_safe(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _parse_simple_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal, strict parser for the expected simple YAML key: value pairs.
    Supports strings (quoted or unquoted), integers, and booleans.
    Ignores comments (#) and blank lines.
    """
    text = _read_text_safe(path)
    if text is None:
        return None
    config: Dict[str, Any] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            return None
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        if "#" in val:
            val = val.split("#", 1)[0].strip()
        if val.startswith(("'", '"')) and val.endswith(("'", '"')) and len(val) >= 2:
            val = val[1:-1]
        low = val.lower()
        if low in ("true", "false"):
            config[key] = low == "true"
        else:
            try:
                ival = int(val)
                config[key] = ival
            except ValueError:
                config[key] = val
    return config


def _read_keywords_csv(path: Path) -> Optional[List[str]]:
    text = _read_text_safe(path)
    if text is None:
        return None
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return None
    header = [h.strip().lower() for h in lines[0].split(",")]
    if "keyword" not in header:
        return None
    idx = header.index("keyword")
    keywords: List[str] = []
    for row in lines[1:]:
        parts = [p.strip() for p in row.split(",")]
        if idx < len(parts) and parts[idx]:
            keywords.append(parts[idx])
    return keywords


class SEOHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_title = False
        self.current_title = ""
        self.titles: List[str] = []
        self.meta_descriptions: List[str] = []
        self.meta_robots: List[str] = []
        self.canonicals: List[str] = []
        self.h1_count = 0
        self.anchors: List[str] = []

    def handle_starttag(self, tag, attrs):
        tag_lower = tag.lower()
        attrs_dict = {k.lower(): v for (k, v) in attrs}
        if tag_lower == "title":
            if not self.in_title:
                self.in_title = True
                self.current_title = ""
        elif tag_lower == "meta":
            name = attrs_dict.get("name")
            if name is not None and name.lower() == "description":
                content = attrs_dict.get("content", "")
                if content is not None:
                    self.meta_descriptions.append(content)
            if name is not None and name.lower() == "robots":
                content = attrs_dict.get("content", "")
                if content is not None:
                    self.meta_robots.append(content)
        elif tag_lower == "link":
            rel = attrs_dict.get("rel", "")
            href = attrs_dict.get("href", "")
            if rel is not None and "canonical" in rel.lower():
                if href is not None:
                    self.canonicals.append(href)
        elif tag_lower == "h1":
            self.h1_count += 1
        elif tag_lower == "a":
            href = attrs_dict.get("href")
            if href:
                self.anchors.append(href)

    def handle_endtag(self, tag):
        if tag.lower() == "title":
            if self.in_title:
                self.titles.append(self.current_title.strip())
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.current_title += data


def _parse_html_file(path: Path) -> Optional[SEOHTMLParser]:
    text = _read_text_safe(path)
    if text is None:
        return None
    parser = SEOHTMLParser()
    try:
        parser.feed(text)
        parser.close()
        return parser
    except Exception:
        return None


def _normalize_base_url(base_url: str) -> str:
    if not base_url.endswith("/"):
        return base_url + "/"
    return base_url


def _title_has_keyword(title: str, keywords: List[str]) -> bool:
    tl = title.lower()
    for kw in keywords:
        if kw and kw.lower() in tl:
            return True
    return False


def _robots_is_index_follow(val: str) -> bool:
    v = val.strip().lower()
    v = re.sub(r"\s+", "", v)
    return v == "index,follow"


def _href_basename(href: str) -> Optional[str]:
    try:
        parsed = urlparse(href)
        path = parsed.path if parsed.path else href
        name = Path(path).name
        return name if name else None
    except Exception:
        return None


def _find_per_page_entries(obj: Any) -> Optional[List[Dict[str, Any]]]:
    required_keys = {
        "page_path",
        "title_text",
        "title_length",
        "title_has_keyword",
        "has_meta_description",
        "meta_description_length",
        "has_canonical_with_base",
        "h1_count",
        "has_robots_index_follow",
        "internal_links_to_other_pages",
        "pass",
        "issues",
    }
    if isinstance(obj, list):
        if obj and all(isinstance(it, dict) for it in obj):
            if all(required_keys.issubset(set(it.keys())) for it in obj):
                return obj
        for it in obj:
            res = _find_per_page_entries(it)
            if res is not None:
                return res
    elif isinstance(obj, dict):
        for v in obj.values():
            res = _find_per_page_entries(v)
            if res is not None:
                return res
    return None


def _run_user_validator(workspace: Path, site_dir: Path, config_file: Path, tmp_report: Path) -> Tuple[bool, Optional[Any], str]:
    script = workspace / "tools" / "seo_check.py"
    if not script.exists():
        return (False, None, "script_missing")
    try:
        cmd = [sys.executable, str(script), "--site", str(site_dir), "--config", str(config_file), "--report", str(tmp_report)]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        if result.returncode != 0:
            return (False, None, "nonzero_exit")
        data = _load_json_safe(tmp_report)
        if data is None:
            return (False, None, "json_load_failed")
        return (True, data, "")
    except subprocess.TimeoutExpired:
        return (False, None, "timeout")
    except Exception as e:
        return (False, None, f"exception:{e}")


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path or ".")
    scores: Dict[str, float] = {
        "seo_check_script_exists": 0.0,
        "seo_check_runs_on_input_site": 0.0,
        "before_report_exists_and_structure": 0.0,
        "before_report_reflects_issues": 0.0,
        "optimized_site_files_exist": 0.0,
        "optimized_titles_valid": 0.0,
        "optimized_meta_descriptions_valid": 0.0,
        "optimized_canonical_valid": 0.0,
        "optimized_h1_valid": 0.0,
        "optimized_robots_valid": 0.0,
        "optimized_internal_links_valid": 0.0,
        "after_report_exists_and_structure": 0.0,
        "after_report_all_pass": 0.0,
        "status_report_exists": 0.0,
        "status_report_content_quality": 0.0,
    }

    input_site = workspace / "input" / "site"
    config_yaml = workspace / "input" / "config.yaml"
    keywords_csv_path = workspace / "input" / "keywords.csv"
    before_report_path = workspace / "output" / "seo_audit_before.json"
    after_report_path = workspace / "output" / "seo_audit_after.json"
    optimized_dir = workspace / "output" / "site_optimized"
    status_report_md = workspace / "output" / "seo_status_report.md"

    config = _parse_simple_yaml(config_yaml) if config_yaml.exists() else None
    keywords = _read_keywords_csv(keywords_csv_path) if keywords_csv_path.exists() else None

    if (workspace / "tools" / "seo_check.py").exists():
        scores["seo_check_script_exists"] = 1.0

    if input_site.exists() and config_yaml.exists():
        tmp_report = workspace / ".tmp_validation_before.json"
        ok_run, json_obj_run, _ = _run_user_validator(workspace, input_site, config_yaml, tmp_report)
        if ok_run and isinstance(json_obj_run, (dict, list)):
            scores["seo_check_runs_on_input_site"] = 1.0

    before_json = _load_json_safe(before_report_path)
    per_page_list_before: Optional[List[Dict[str, Any]]] = None
    if before_json is not None and isinstance(before_json, dict):
        summary = before_json.get("summary")
        if isinstance(summary, dict):
            if all(k in summary for k in ("pages", "passes", "fails")) and all(isinstance(summary[k], int) for k in ("pages", "passes", "fails")):
                per_page_list_before = _find_per_page_entries(before_json)
                if per_page_list_before is not None and isinstance(per_page_list_before, list):
                    scores["before_report_exists_and_structure"] = 1.0

    if scores["before_report_exists_and_structure"] == 1.0:
        summary = before_json.get("summary", {})
        try:
            cond = (summary.get("pages") == 3 and summary.get("passes") == 0 and summary.get("fails") == 3)
            if per_page_list_before is not None and len(per_page_list_before) == 3:
                per_page_all_fail = all((not bool(item.get("pass"))) and isinstance(item.get("issues"), list) and len(item.get("issues")) >= 1 for item in per_page_list_before)
                cond = cond and per_page_all_fail
            if cond:
                scores["before_report_reflects_issues"] = 1.0
        except Exception:
            scores["before_report_reflects_issues"] = 0.0

    expected_files = ["index.html", "policy-brief.html", "glossary.html"]
    if optimized_dir.exists():
        exist_count = sum(1 for name in expected_files if (optimized_dir / name).exists())
        scores["optimized_site_files_exist"] = exist_count / len(expected_files) if expected_files else 0.0

    if config is not None and keywords is not None and optimized_dir.exists():
        base_url = _normalize_base_url(str(config.get("base_url", "")))
        title_min = config.get("title_len_min")
        title_max = config.get("title_len_max")
        desc_min = config.get("meta_description_len_min")
        desc_max = config.get("meta_description_len_max")
        require_robots = bool(config.get("require_robots_index_follow", False))

        title_passes: List[bool] = []
        desc_passes: List[bool] = []
        canonical_passes: List[bool] = []
        h1_passes: List[bool] = []
        robots_passes: List[bool] = []
        internal_links_passes: List[bool] = []

        for name in expected_files:
            file_path = optimized_dir / name
            parser = _parse_html_file(file_path)
            if parser is None:
                title_passes.append(False)
                desc_passes.append(False)
                canonical_passes.append(False)
                h1_passes.append(False)
                robots_passes.append(False)
                internal_links_passes.append(False)
                continue

            if len(parser.titles) == 1:
                t = parser.titles[0].strip()
                length_ok = isinstance(title_min, int) and isinstance(title_max, int) and (title_min <= len(t) <= title_max)
                has_kw = _title_has_keyword(t, keywords)
                title_passes.append(length_ok and has_kw)
            else:
                title_passes.append(False)

            if len(parser.meta_descriptions) == 1:
                d = parser.meta_descriptions[0]
                length_ok = isinstance(desc_min, int) and isinstance(desc_max, int) and (desc_min <= len(d) <= desc_max)
                desc_passes.append(length_ok)
            else:
                desc_passes.append(False)

            expected_href = f"{base_url}{name}"
            has_expected = any(href == expected_href for href in parser.canonicals)
            canonical_passes.append(has_expected)

            h1_passes.append(parser.h1_count == 1)

            if require_robots:
                ok = any(_robots_is_index_follow(val) for val in parser.meta_robots)
                robots_passes.append(ok)
            else:
                robots_passes.append(True)

            basenames = set()
            for href in parser.anchors:
                base = _href_basename(href)
                if base:
                    basenames.add(base)
            others = set(expected_files) - {name}
            internal_links_passes.append(others.issubset(basenames))

        def _avg(vals: List[bool]) -> float:
            return (sum(1 for v in vals if v) / len(vals)) if vals else 0.0

        scores["optimized_titles_valid"] = _avg(title_passes)
        scores["optimized_meta_descriptions_valid"] = _avg(desc_passes)
        scores["optimized_canonical_valid"] = _avg(canonical_passes)
        scores["optimized_h1_valid"] = _avg(h1_passes)
        scores["optimized_robots_valid"] = _avg(robots_passes)
        scores["optimized_internal_links_valid"] = _avg(internal_links_passes)

    after_json = _load_json_safe(after_report_path)
    per_page_list_after: Optional[List[Dict[str, Any]]] = None
    if after_json is not None and isinstance(after_json, dict):
        summary = after_json.get("summary")
        if isinstance(summary, dict):
            if all(k in summary for k in ("pages", "passes", "fails")) and all(isinstance(summary[k], int) for k in ("pages", "passes", "fails")):
                per_page_list_after = _find_per_page_entries(after_json)
                if per_page_list_after is not None and isinstance(per_page_list_after, list):
                    scores["after_report_exists_and_structure"] = 1.0

    if scores["after_report_exists_and_structure"] == 1.0:
        summary = after_json.get("summary", {})
        cond = (summary.get("pages") == 3 and summary.get("passes") == 3 and summary.get("fails") == 0)
        if per_page_list_after is not None and len(per_page_list_after) == 3:
            per_page_all_pass = all(bool(item.get("pass")) for item in per_page_list_after)
            links_all_two = all(int(item.get("internal_links_to_other_pages", -1)) == 2 for item in per_page_list_after)
            cond = cond and per_page_all_pass and links_all_two
        if cond:
            scores["after_report_all_pass"] = 1.0

    if status_report_md.exists():
        content = _read_text_safe(status_report_md) or ""
        if content.strip():
            scores["status_report_exists"] = 1.0

        conditions_met = 0
        total = 0

        # Context: mentions post-Keynesian
        total += 1
        if re.search(r"post-?keynesian", content, flags=re.IGNORECASE):
            conditions_met += 1

        # before/after mentions
        total += 2
        if re.search(r"\bbefore\b", content, flags=re.IGNORECASE):
            conditions_met += 1
        if re.search(r"\bafter\b", content, flags=re.IGNORECASE):
            conditions_met += 1

        # filenames
        filenames = ["index.html", "policy-brief.html", "glossary.html"]
        total += len(filenames)
        for nm in filenames:
            if nm in content:
                conditions_met += 1

        # metrics terms
        metric_terms = [
            r"title length",
            r"keyword",
            r"meta description",
            r"canonical",
            r"\bH1\b",
            r"robots",
            r"internal link",
        ]
        total += len(metric_terms)
        for term in metric_terms:
            if re.search(term, content, flags=re.IGNORECASE):
                conditions_met += 1

        scores["status_report_content_quality"] = (conditions_met / total) if total > 0 else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()