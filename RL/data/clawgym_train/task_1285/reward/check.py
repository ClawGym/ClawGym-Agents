import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_lines(text: Optional[str]) -> List[str]:
    if text is None:
        return []
    return text.splitlines()


def _parse_simple_yaml(text: str) -> Dict[str, str]:
    data: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        data[key] = val
    return data


def _load_site_title(workspace: Path) -> Optional[str]:
    cfg_path = workspace / "config.yaml"
    text = _read_text(cfg_path)
    if text is None:
        return None
    data = _parse_simple_yaml(text)
    return data.get("site_title")


def _parse_md_front_matter(md_text: str) -> Tuple[Dict[str, str], str]:
    lines = md_text.splitlines()
    fm: Dict[str, str] = {}
    if len(lines) >= 3 and lines[0].strip() == "---":
        try:
            end_idx = 1
            while end_idx < len(lines) and lines[end_idx].strip() != "---":
                end_idx += 1
            if end_idx < len(lines) and lines[end_idx].strip() == "---":
                fm_text = "\n".join(lines[1:end_idx])
                fm = _parse_simple_yaml(fm_text)
                body = "\n".join(lines[end_idx + 1 :])
                return fm, body
        except Exception:
            pass
    return fm, md_text


def _list_article_md_files(workspace: Path) -> List[Path]:
    art_dir = workspace / "articles"
    if not art_dir.is_dir():
        return []
    return sorted([p for p in art_dir.glob("*.md") if p.is_file()])


def _extract_title_tag(html: str) -> Optional[str]:
    m = re.search(r"<title>\s*(.*?)\s*</title>", html, re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    return re.sub(r"\s+", " ", m.group(1)).strip()


def _contains_h1_with_text(html: str, text: str) -> bool:
    pattern = r"<h1[^>]*>\s*" + re.escape(text) + r"\s*</h1>"
    return re.search(pattern, html, re.IGNORECASE | re.DOTALL) is not None


def _contains_h2_with_text(html: str, text: str) -> bool:
    pattern = r"<h2[^>]*>\s*" + re.escape(text) + r"\s*</h2>"
    return re.search(pattern, html, re.IGNORECASE | re.DOTALL) is not None


def _contains_p_with_text(html: str, text: str) -> bool:
    pattern = r"<p[^>]*>[^<]*" + re.escape(text) + r"[^<]*</p>"
    return re.search(pattern, html, re.IGNORECASE | re.DOTALL) is not None


def _contains_time_for_date(html: str, date_str: str) -> bool:
    pattern = (
        r"<time[^>]*datetime=[\"']" + re.escape(date_str) + r"[\"'][^>]*>.*?"
        + re.escape(date_str)
        + r".*?</time>"
    )
    return re.search(pattern, html, re.IGNORECASE | re.DOTALL) is not None


def _site_title_visible_outside_title(html: str, site_title: str) -> bool:
    stripped = re.sub(r"<title>.*?</title>", "", html, flags=re.IGNORECASE | re.DOTALL)
    return site_title in stripped


def _parse_index_anchors(html: str) -> List[Tuple[str, str, int]]:
    anchors: List[Tuple[str, str, int]] = []
    for m in re.finditer(r'<a\s+[^>]*href\s*=\s*["\'](.*?)["\'][^>]*>(.*?)</a>', html, re.IGNORECASE | re.DOTALL):
        href = m.group(1).strip()
        text = re.sub(r"\s+", " ", m.group(2)).strip()
        anchors.append((href, text, m.start()))
    return anchors


def _lines_listed_paths(status_text: str, expected_paths: List[str]) -> Dict[str, bool]:
    found: Dict[str, bool] = {p: False for p in expected_paths}
    for raw in status_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        line_norm = line
        if line_norm.startswith(("-", "*", "•")):
            line_norm = line_norm[1:].strip()
        if line_norm.startswith("`") and line_norm.endswith("`") and len(line_norm) >= 2:
            line_norm = line_norm[1:-1]
        line_norm = line_norm.strip().strip(".")
        for p in expected_paths:
            if line_norm == p:
                found[p] = True
    return found


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "build_script_present": 0.0,
        "serve_script_present_and_configured": 0.0,
        "public_article_files_exist": 0.0,
        "article_title_tags": 0.0,
        "article_site_title_visible": 0.0,
        "article_time_elements": 0.0,
        "article_body_markdown_conversion": 0.0,
        "index_exists": 0.0,
        "index_links_and_order": 0.0,
        "readme_updated": 0.0,
        "deployment_updated": 0.0,
        "status_summary_completeness": 0.0,
        "newsletter_final_quality": 0.0,
    }

    build_script = workspace / "tools" / "build_site.py"
    if build_script.is_file():
        scores["build_script_present"] = 1.0

    site_title = _load_site_title(workspace)
    article_files = _list_article_md_files(workspace)
    expected_articles: List[Dict[str, str]] = []
    for p in article_files:
        text = _read_text(p)
        if text is None:
            continue
        fm, body = _parse_md_front_matter(text)
        title = fm.get("title", "").strip('"').strip("'")
        date = fm.get("date", "").strip()
        expected_articles.append(
            {
                "basename": p.with_suffix(".html").name,
                "title": title,
                "date": date,
                "md_body": body,
                "source_path": str(p),
            }
        )

    if expected_articles:
        public_dir = workspace / "public"
        exist_count = 0
        title_tag_ok = 0
        site_title_visible_ok = 0
        time_ok = 0
        body_conv_ok = 0

        for art in expected_articles:
            out_path = public_dir / art["basename"]
            html = _read_text(out_path)
            if html is not None:
                exist_count += 1
                tt = _extract_title_tag(html or "")
                if site_title and art["title"] and tt == f"{art['title']} | {site_title}":
                    title_tag_ok += 1
                if site_title and _site_title_visible_outside_title(html, site_title):
                    site_title_visible_ok += 1
                if art["date"] and _contains_time_for_date(html, art["date"]):
                    time_ok += 1
                body = art["md_body"]
                first_h1_text = None
                first_h2_text = None
                first_p_text = None
                for line in body.splitlines():
                    if not line.strip():
                        continue
                    if line.startswith("# "):
                        if first_h1_text is None:
                            first_h1_text = line[2:].strip()
                        continue
                    if line.startswith("## "):
                        if first_h2_text is None:
                            first_h2_text = line[3:].strip()
                        continue
                    if first_p_text is None:
                        first_p_text = line.strip()
                h1_ok = True if first_h1_text is None else _contains_h1_with_text(html, first_h1_text)
                h2_ok = True if first_h2_text is None else _contains_h2_with_text(html, first_h2_text)
                p_ok = True if first_p_text is None else _contains_p_with_text(html, first_p_text[:60])
                if h1_ok and h2_ok and p_ok:
                    body_conv_ok += 1

        n = len(expected_articles)
        if n > 0:
            scores["public_article_files_exist"] = exist_count / n
            scores["article_title_tags"] = title_tag_ok / n
            scores["article_site_title_visible"] = site_title_visible_ok / n
            scores["article_time_elements"] = time_ok / n
            scores["article_body_markdown_conversion"] = body_conv_ok / n

    index_path = workspace / "public" / "index.html"
    index_html = _read_text(index_path)
    if index_html is not None:
        scores["index_exists"] = 1.0
        anchors = _parse_index_anchors(index_html)
        expected_by_date = []
        for art in expected_articles:
            try:
                y, m, d = [int(x) for x in art["date"].split("-")]
                expected_by_date.append((art, (y, m, d)))
            except Exception:
                expected_by_date.append((art, (0, 0, 0)))
        expected_order = [art["basename"] for art, _ in sorted(expected_by_date, key=lambda t: t[1], reverse=True)]
        hrefs_in_order = [h for (h, t, pos) in anchors]
        present_order = [h for h in hrefs_in_order if h in expected_order]
        order_ok = present_order == expected_order if expected_order else False
        link_and_meta_ok_count = 0
        for art in expected_articles:
            idx = None
            anchor_text = ""
            anchor_pos = -1
            for (h, t, pos) in anchors:
                if h == art["basename"]:
                    idx = h
                    anchor_text = t
                    anchor_pos = pos
                    break
            if idx is None:
                continue
            title_in_text = art["title"] in anchor_text or art["title"] in index_html[max(0, anchor_pos - 120) : anchor_pos + 240]
            date_near = art["date"] in index_html[max(0, anchor_pos - 120) : anchor_pos + 240]
            link_and_meta_ok_count += 1 if (title_in_text and date_near) else 0

        if expected_articles:
            links_ok = (link_and_meta_ok_count == len(expected_articles)) and order_ok
            scores["index_links_and_order"] = 1.0 if links_ok else 0.0

    serve_script = workspace / "scripts" / "serve_local.sh"
    ss_text = _read_text(serve_script)
    if ss_text is not None:
        has_http_server = ("http.server" in ss_text) or ("SimpleHTTPServer" in ss_text)
        has_python = "python" in ss_text
        has_port_8000 = "8000" in ss_text
        serves_public = ("cd public" in ss_text) or ("--directory public" in ss_text) or (" -d public" in ss_text) or (" --directory=public" in ss_text)
        if has_http_server and has_python and has_port_8000 and serves_public:
            scores["serve_script_present_and_configured"] = 1.0

    readme_text = _read_text(workspace / "README.md")
    if readme_text is not None:
        mentions_build = "tools/build_site.py" in readme_text or "python tools/build_site.py" in readme_text
        mentions_serve = "scripts/serve_local.sh" in readme_text
        mentions_public = "public/" in readme_text or "`public/`" in readme_text
        mentions_python = re.search(r"Python\s*3", readme_text, re.IGNORECASE) is not None
        no_node = ("npm" not in readme_text.lower()) and ("dist/" not in readme_text.lower()) and ("node" not in readme_text.lower())
        if mentions_build and mentions_serve and mentions_public and mentions_python and no_node:
            scores["readme_updated"] = 1.0

    deployment_text = _read_text(workspace / "DEPLOYMENT.md")
    if deployment_text is not None:
        mentions_public = ("public/" in deployment_text) or ("`public/`" in deployment_text)
        mentions_build = ("tools/build_site.py" in deployment_text) or ("python tools/build_site.py" in deployment_text) or ("build" in deployment_text.lower())
        no_node = ("npm" not in deployment_text.lower()) and ("dist/" not in deployment_text.lower()) and ("node" not in deployment_text.lower())
        mentions_verify_local = ("local" in deployment_text.lower()) or ("verify" in deployment_text.lower()) or ("http.server" in deployment_text.lower()) or ("localhost" in deployment_text.lower())
        if mentions_public and mentions_build and no_node and mentions_verify_local:
            scores["deployment_updated"] = 1.0

    status_path = workspace / "out" / "STATUS.md"
    status_text = _read_text(status_path)
    if status_text is not None:
        expected_public_files = ["public/index.html"] + [f"public/{art['basename']}" for art in expected_articles]
        listed = _lines_listed_paths(status_text, expected_public_files)
        listed_all = all(listed.get(p, False) for p in expected_public_files) if expected_public_files else False
        has_assumptions = ("assumption" in status_text.lower())
        has_summary_cues = any(word in status_text.lower() for word in ["configured", "pipeline", "build", "static", "site"])
        if listed_all and has_assumptions and has_summary_cues:
            scores["status_summary_completeness"] = 1.0

    newsletter_final = workspace / "out" / "newsletter_final.txt"
    nf_text = _read_text(newsletter_final)
    if nf_text is not None:
        words = re.findall(r"\b\w[\w’']*\b", nf_text)
        under_limit = len(words) <= 120
        warm_tokens = ["excited", "thrilled", "stoked", "pumped", "happy", "glad", "warm", "cheer", "celebrate", "love", "can't wait", "cant wait", "grateful", "thanks", "!"]
        warm = any(tok in nf_text.lower() for tok in warm_tokens)
        mentions_local = ("local" in nf_text.lower())
        mentions_recaps = ("recap" in nf_text.lower())
        mentions_liveish = any(tok in nf_text.lower() for tok in ["live", "available", "up now", "ready"])
        cta = False
        if re.search(r"check\s+out", nf_text, re.IGNORECASE):
            cta = True
        elif (("read" in nf_text.lower()) or ("see" in nf_text.lower())) and any(tok in nf_text.lower() for tok in ["latest", "new", "fresh"]) and any(tok in nf_text.lower() for tok in ["post", "posts", "recap", "recaps"]):
            cta = True
        if under_limit and warm and mentions_local and mentions_recaps and mentions_liveish and cta:
            scores["newsletter_final_quality"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1].strip():
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()