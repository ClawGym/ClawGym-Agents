import sys
import json
import re
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def parse_scalar(value: str) -> Any:
    v = value.strip()
    if len(v) >= 2 and ((v[0] == v[-1]) and v[0] in ("'", '"')):
        v = v[1:-1]
    try:
        iv = int(v)
        return iv
    except Exception:
        return v


def parse_simple_yaml_map(yaml_text: str) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    current_list_key: Optional[str] = None
    in_list = False
    for raw_line in yaml_text.splitlines():
        line = raw_line.rstrip("\n")
        striped = line.strip()
        if not striped or striped.startswith("#"):
            continue
        if in_list and striped.startswith("- "):
            item = striped[2:].strip()
            item = parse_scalar(item)
            assert current_list_key is not None
            data[current_list_key].append(item)
            continue
        in_list = False
        current_list_key = None
        if ":" in line:
            key, rest = line.split(":", 1)
            key = key.strip()
            val = rest.strip()
            if val == "":
                data[key] = []
                current_list_key = key
                in_list = True
            else:
                data[key] = parse_scalar(val)
        else:
            continue
    return data


def extract_front_matter(md_text: str) -> Tuple[Optional[Dict[str, Any]], str]:
    lines = md_text.splitlines()
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines) or lines[i].strip() != "---":
        return None, md_text
    start = i
    end = None
    for j in range(start + 1, len(lines)):
        if lines[j].strip() == "---":
            end = j
            break
    if end is None:
        return None, md_text
    yaml_text = "\n".join(lines[start + 1:end])
    body = "\n".join(lines[end + 1:])
    data = parse_simple_yaml_map(yaml_text)
    return data, body


def slugify(title: str) -> str:
    s = title.lower()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9\-]", "", s)
    s = re.sub(r"-{2,}", "-", s)
    s = s.strip("-")
    return s


def strip_tags(html: str) -> str:
    return re.sub(r"<[^>]*>", " ", html)


def normalize_text(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def find_h1_texts(html: str) -> List[str]:
    texts = []
    for m in re.finditer(r"<h1[^>]*>(.*?)</h1>", html, flags=re.IGNORECASE | re.DOTALL):
        inner = m.group(1)
        inner = strip_tags(inner)
        texts.append(inner.strip())
    return texts


def parse_env_file(text: str) -> Dict[str, str]:
    env: Dict[str, str] = {}
    for line in text.splitlines():
        striped = line.strip()
        if not striped or striped.startswith("#"):
            continue
        if "=" not in striped:
            continue
        key, val = striped.split("=", 1)
        key = key.strip()
        v = val.strip()
        if len(v) >= 2 and ((v[0] == v[-1]) and v[0] in ("'", '"')):
            v = v[1:-1]
        env[key] = v
    return env


def load_config(workspace: Path) -> Optional[Dict[str, Any]]:
    cfg_path = workspace / "config" / "site.yaml"
    text = read_text(cfg_path)
    if text is None:
        return None
    try:
        cfg = parse_simple_yaml_map(text)
        return cfg
    except Exception:
        return None


def load_legends_from_content(workspace: Path) -> Optional[List[Dict[str, Any]]]:
    content_dir = workspace / "content" / "stories"
    if not content_dir.exists():
        return None
    md_files = sorted(content_dir.glob("*.md"))
    legends: List[Dict[str, Any]] = []
    for p in md_files:
        t = read_text(p)
        if t is None:
            return None
        fm, body = extract_front_matter(t)
        if fm is None:
            return None
        required_keys = ["title", "location", "century", "narrator", "tags"]
        for k in required_keys:
            if k not in fm:
                return None
        title = str(fm["title"])
        location = str(fm["location"])
        narrator = str(fm["narrator"])
        try:
            century = int(fm["century"])
        except Exception:
            return None
        tags_raw = fm["tags"]
        if not isinstance(tags_raw, list):
            return None
        tags = [str(x) for x in tags_raw]
        slug = slugify(title)
        legends.append({
            "slug": slug,
            "title": title,
            "location": location,
            "century": century,
            "narrator": narrator,
            "tags": tags,
            "body": body,
        })
    return legends


def expected_legends_index(legends: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    entries = []
    for item in legends:
        slug = item["slug"]
        tags_sorted = sorted(item["tags"], key=lambda s: (s.lower(), s))
        entries.append({
            "id": slug,
            "title": item["title"],
            "location": item["location"],
            "century": item["century"],
            "narrator": item["narrator"],
            "tags": tags_sorted,
            "path": f"stories/{slug}.html",
        })
    entries_sorted = sorted(entries, key=lambda e: (e["century"], e["title"]))
    return entries_sorted


def legends_json_checks(json_data: Any,
                        expected_entries_sorted: List[Dict[str, Any]],
                        expected_by_slug: Dict[str, Dict[str, Any]]) -> Dict[str, float]:
    scores = {
        "legends_json_exists": 0.0,
        "legends_json_count": 0.0,
        "legends_json_structure_and_fields": 0.0,
        "legends_json_ids_and_paths": 0.0,
        "legends_json_tags_sorted": 0.0,
        "legends_json_sorted_order": 0.0,
    }
    if not isinstance(json_data, list):
        return scores
    scores["legends_json_exists"] = 1.0
    if len(json_data) != len(expected_entries_sorted) or len(expected_entries_sorted) == 0:
        scores["legends_json_count"] = 0.0
    else:
        scores["legends_json_count"] = 1.0

    structure_ok = True
    ids_paths_ok = True
    tags_sorted_ok = True
    order_ok = True

    if json_data:
        try:
            sorted_copy = sorted(json_data, key=lambda e: (e["century"], e["title"]))
            if sorted_copy != json_data:
                order_ok = False
        except Exception:
            order_ok = False

    json_slugs = set()
    for e in json_data:
        if not isinstance(e, dict):
            structure_ok = False
            ids_paths_ok = False
            tags_sorted_ok = False
            break
        required = ["id", "title", "location", "century", "narrator", "tags", "path"]
        for k in required:
            if k not in e:
                structure_ok = False
        if not isinstance(e.get("id"), str):
            structure_ok = False
        if not isinstance(e.get("title"), str):
            structure_ok = False
        if not isinstance(e.get("location"), str):
            structure_ok = False
        if not isinstance(e.get("century"), int):
            structure_ok = False
        if not isinstance(e.get("narrator"), str):
            structure_ok = False
        if not isinstance(e.get("path"), str):
            structure_ok = False
        tags = e.get("tags")
        if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags):
            structure_ok = False
        else:
            sorted_tags = sorted(tags, key=lambda s: (s.lower(), s))
            if tags != sorted_tags:
                tags_sorted_ok = False

        slug = e.get("id")
        json_slugs.add(slug)
        exp = expected_by_slug.get(slug)
        if exp is None:
            ids_paths_ok = False
        else:
            if e.get("title") != exp["title"]:
                ids_paths_ok = False
            if e.get("location") != exp["location"]:
                ids_paths_ok = False
            if e.get("century") != exp["century"]:
                ids_paths_ok = False
            if e.get("narrator") != exp["narrator"]:
                ids_paths_ok = False
            if e.get("path") != exp["path"]:
                ids_paths_ok = False
            exp_tags_sorted = sorted(exp["tags"], key=lambda s: (s.lower(), s))
            if e.get("tags") != exp_tags_sorted:
                ids_paths_ok = False
                tags_sorted_ok = False

    expected_slugs = set(expected_by_slug.keys())
    if json_slugs != expected_slugs:
        ids_paths_ok = False

    scores["legends_json_structure_and_fields"] = 1.0 if structure_ok else 0.0
    scores["legends_json_ids_and_paths"] = 1.0 if ids_paths_ok else 0.0
    scores["legends_json_tags_sorted"] = 1.0 if tags_sorted_ok else 0.0
    scores["legends_json_sorted_order"] = 1.0 if order_ok else 0.0
    return scores


def check_index_html(index_html: str, legends_sorted: List[Dict[str, Any]], site_name: str, footer: str) -> Dict[str, float]:
    scores = {
        "index_html_exists": 1.0,
        "index_lists_legends_in_order": 0.0,
        "index_has_site_name_h1": 0.0,
        "index_has_footer_at_bottom": 0.0,
    }
    h1_texts = find_h1_texts(index_html)
    site_in_h1 = any(site_name in t for t in h1_texts)
    scores["index_has_site_name_h1"] = 1.0 if site_in_h1 else 0.0

    href_positions = []
    ok_order = True
    prev_pos = -1
    for e in legends_sorted:
        href = f'href="stories/{e["id"]}.html"'
        pos = index_html.find(href)
        if pos == -1:
            ok_order = False
            break
        href_positions.append(pos)
        if pos <= prev_pos:
            ok_order = False
            break
        prev_pos = pos
    if ok_order and len(href_positions) == len(legends_sorted) and len(legends_sorted) > 0:
        scores["index_lists_legends_in_order"] = 1.0
    else:
        scores["index_lists_legends_in_order"] = 0.0

    footer_pos = index_html.rfind(footer)
    if footer_pos != -1:
        last_link_pos = max(href_positions) if href_positions else -1
        near_end = footer_pos >= int(len(index_html) * 0.7)
        if footer_pos > last_link_pos and near_end:
            scores["index_has_footer_at_bottom"] = 1.0
    return scores


def check_legend_pages(pages: Dict[str, str], legends: List[Dict[str, Any]]) -> Dict[str, float]:
    keys = [
        "legend_pages_exist",
        "legend_pages_have_title_h1",
        "legend_pages_have_metadata_values",
        "legend_pages_include_body_content",
    ]
    scores = {k: 0.0 for k in keys}
    total = len(legends)
    if total == 0:
        return scores
    exist_count = 0
    h1_count = 0
    meta_count = 0
    body_count = 0

    for item in legends:
        slug = item["slug"]
        html = pages.get(slug)
        if html is None:
            continue
        exist_count += 1
        h1_texts = find_h1_texts(html)
        if any(item["title"] in t for t in h1_texts):
            h1_count += 1
        all_meta_present = True
        if item["location"] not in html:
            all_meta_present = False
        if str(item["century"]) not in html:
            all_meta_present = False
        if item["narrator"] not in html:
            all_meta_present = False
        for tag in item["tags"]:
            if tag not in html:
                all_meta_present = False
                break
        if all_meta_present:
            meta_count += 1
        norm_html = normalize_text(strip_tags(html))
        body_text = item.get("body", "")
        norm_body = normalize_text(body_text)
        words = [w for w in norm_body.split() if len(w) >= 5]
        words_sorted = sorted(set(words), key=lambda w: (-len(w), w))
        keywords = words_sorted[:5]
        present = 0
        for w in keywords:
            if w and w in norm_html:
                present += 1
        if present >= max(1, min(3, len(keywords))):
            body_count += 1

    scores["legend_pages_exist"] = exist_count / total
    scores["legend_pages_have_title_h1"] = h1_count / total
    scores["legend_pages_have_metadata_values"] = meta_count / total
    scores["legend_pages_include_body_content"] = body_count / total
    return scores


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "legends_json_exists": 0.0,
        "legends_json_count": 0.0,
        "legends_json_structure_and_fields": 0.0,
        "legends_json_ids_and_paths": 0.0,
        "legends_json_tags_sorted": 0.0,
        "legends_json_sorted_order": 0.0,
        "index_html_exists": 0.0,
        "index_lists_legends_in_order": 0.0,
        "index_has_site_name_h1": 0.0,
        "index_has_footer_at_bottom": 0.0,
        "legend_pages_exist": 0.0,
        "legend_pages_have_title_h1": 0.0,
        "legend_pages_have_metadata_values": 0.0,
        "legend_pages_include_body_content": 0.0,
        "docker_env_exists": 0.0,
        "docker_env_values_correct": 0.0,
    }

    cfg = load_config(workspace)
    if not cfg:
        return scores

    site_name = cfg.get("site_name")
    site_port = cfg.get("site_port")
    output_dir = cfg.get("output_dir")
    footer = cfg.get("footer")
    if not (isinstance(site_name, str) and isinstance(site_port, int) and isinstance(output_dir, str) and isinstance(footer, str)):
        return scores

    legends = load_legends_from_content(workspace)
    if legends is None:
        expected_entries_sorted: List[Dict[str, Any]] = []
        expected_by_slug: Dict[str, Dict[str, Any]] = {}
    else:
        expected_entries_sorted = expected_legends_index(legends)
        expected_by_slug = {e["id"]: e for e in expected_entries_sorted}

    legends_json_path = workspace / output_dir / "data" / "legends.json"
    json_data = load_json(legends_json_path) if legends_json_path.exists() else None
    if json_data is not None:
        json_scores = legends_json_checks(json_data, expected_entries_sorted, expected_by_slug)
        scores.update(json_scores)

    index_path = workspace / output_dir / "index.html"
    index_text = read_text(index_path)
    if index_text is not None:
        scores["index_html_exists"] = 1.0
        idx_scores = check_index_html(index_text, expected_entries_sorted, site_name, footer)
        if len(expected_entries_sorted) == 0:
            idx_scores["index_lists_legends_in_order"] = 0.0
        scores["index_lists_legends_in_order"] = idx_scores["index_lists_legends_in_order"]
        scores["index_has_site_name_h1"] = idx_scores["index_has_site_name_h1"]
        scores["index_has_footer_at_bottom"] = idx_scores["index_has_footer_at_bottom"]

    pages_html_present: Dict[str, str] = {}
    for e in expected_entries_sorted:
        slug = e["id"]
        p = workspace / output_dir / "stories" / f"{slug}.html"
        t = read_text(p)
        if t is not None:
            pages_html_present[slug] = t
    if expected_entries_sorted and legends is not None:
        legend_page_scores = check_legend_pages(pages_html_present, legends)
        scores.update(legend_page_scores)

    env_path = workspace / "deploy" / ".env"
    env_text = read_text(env_path)
    if env_text is not None:
        scores["docker_env_exists"] = 1.0
        env_map = parse_env_file(env_text)
        correct = 0
        total_needed = 2
        if env_map.get("SITE_PORT") == str(site_port):
            correct += 1
        if env_map.get("OUTPUT_DIR") == output_dir:
            correct += 1
        scores["docker_env_values_correct"] = correct / total_needed

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()