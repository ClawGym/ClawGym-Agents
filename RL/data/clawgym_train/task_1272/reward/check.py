import json
import sys
import re
from pathlib import Path


def _read_text_utf8(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_utf8(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text)
    except Exception:
        return None


def _file_exists_nonempty(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except Exception:
        return False


def _normalize_ws(s: str) -> str:
    if s is None:
        return ""
    return re.sub(r"\s+", " ", s).strip()


def _extract_first_tag_text(html: str, tag: str) -> str:
    if not html:
        return ""
    # Case-insensitive, dotall to match across lines, non-greedy content
    pattern = rf"<{tag}\b[^>]*>(.*?)</{tag}>"
    m = re.search(pattern, html, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    # Remove any nested tags within for a cleaner text extraction
    inner = m.group(1)
    # Strip tags crudely
    inner_no_tags = re.sub(r"<[^>]+>", "", inner)
    return inner_no_tags.strip()


def _extract_first_href(html: str) -> str:
    if not html:
        return ""
    m = re.search(r'<a\b[^>]*\bhref\s*=\s*["\']([^"\']+)["\']', html, flags=re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else ""


def _is_absolute_http_url(url: str) -> bool:
    return isinstance(url, str) and re.match(r"^https?://", url) is not None


def grade(transcript: list, workspace_path: str) -> dict:
    base = Path(workspace_path if workspace_path else ".")
    raw_dir = base / "workspace" / "raw"
    extracted_dir = base / "workspace" / "extracted"
    html_path = raw_dir / "example_com.html"
    robots_path = raw_dir / "example_com_robots.txt"
    summary_path = extracted_dir / "example_com_summary.json"

    scores = {
        "raw_html_exists_nonempty": 0.0,
        "raw_html_contains_example_domain": 0.0,
        "raw_robots_exists_nonempty": 0.0,
        "summary_json_exists_and_valid_keys": 0.0,
        "summary_domain_is_example_com": 0.0,
        "summary_h1_contains_example_domain": 0.0,
        "summary_first_link_is_absolute_url": 0.0,
        "summary_h1_matches_html": 0.0,
        "summary_p_matches_html": 0.0,
        "summary_first_link_matches_html": 0.0,
    }

    # Check raw HTML file
    if _file_exists_nonempty(html_path):
        scores["raw_html_exists_nonempty"] = 1.0
        html_text = _read_text_utf8(html_path)
        if isinstance(html_text, str) and ("Example Domain" in html_text):
            scores["raw_html_contains_example_domain"] = 1.0
    else:
        html_text = None

    # Check robots.txt
    if _file_exists_nonempty(robots_path):
        # Validate UTF-8 readability
        robots_text = _read_text_utf8(robots_path)
        if isinstance(robots_text, str) and len(robots_text) > 0:
            scores["raw_robots_exists_nonempty"] = 1.0

    # Check summary JSON
    summary = _load_json_utf8(summary_path) if summary_path.exists() else None
    expected_keys = {"domain", "h1", "p", "first_link"}
    if isinstance(summary, dict) and set(summary.keys()) == expected_keys and len(summary) == 4:
        scores["summary_json_exists_and_valid_keys"] = 1.0

        # domain check
        if summary.get("domain") == "example.com":
            scores["summary_domain_is_example_com"] = 1.0

        # h1 contains substring
        h1_val = summary.get("h1")
        if isinstance(h1_val, str) and "Example Domain" in h1_val:
            scores["summary_h1_contains_example_domain"] = 1.0

        # first_link absolute URL check
        first_link_val = summary.get("first_link")
        if _is_absolute_http_url(first_link_val):
            scores["summary_first_link_is_absolute_url"] = 1.0

        # Cross-check extracted fields against the saved HTML (if available)
        if isinstance(html_text, str) and html_text:
            html_h1 = _extract_first_tag_text(html_text, "h1")
            html_p = _extract_first_tag_text(html_text, "p")
            html_a = _extract_first_href(html_text)

            # Normalize whitespace for comparisons
            if _normalize_ws(h1_val) == _normalize_ws(html_h1):
                scores["summary_h1_matches_html"] = 1.0
            if _normalize_ws(summary.get("p")) == _normalize_ws(html_p):
                scores["summary_p_matches_html"] = 1.0
            if isinstance(first_link_val, str) and isinstance(html_a, str) and first_link_val.strip() == html_a.strip():
                scores["summary_first_link_matches_html"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()