import json
import re
import sys
import csv
from pathlib import Path
from html.parser import HTMLParser


def _read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_palette_csv(p: Path):
    try:
        with p.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            hexes = []
            for row in reader:
                hx = row.get("hex", "") if row else ""
                if isinstance(hx, str) and hx.strip().startswith("#"):
                    hexes.append(hx.strip().upper())
            return hexes
    except Exception:
        return None


def _parse_brief_md(p: Path):
    text = _read_text(p)
    if text is None:
        return None
    title = None
    required_text = None
    aspect_ratio = None
    max_colors = None
    include_motifs = []
    for line in text.splitlines():
        line_stripped = line.strip()
        if line_stripped.startswith("Title:"):
            title = line_stripped.split("Title:", 1)[1].strip()
        elif line_stripped.startswith("Required Text:"):
            required_text = line_stripped.split("Required Text:", 1)[1].strip()
        elif line_stripped.startswith("- AspectRatio:"):
            aspect_ratio = line_stripped.split("AspectRatio:", 1)[1].strip()
        elif line_stripped.startswith("- MaxColors:"):
            try:
                max_colors = int(line_stripped.split("MaxColors:", 1)[1].strip())
            except Exception:
                max_colors = None
        elif line_stripped.startswith("- IncludeMotifs:"):
            motifs_str = line_stripped.split("IncludeMotifs:", 1)[1].strip()
            motifs = [m.strip() for m in motifs_str.split(",") if m.strip()]
            include_motifs = motifs
    if not title and "#" in text:
        m = re.search(r"#\s*Creative Brief:\s*(.+)", text)
        if m:
            title = m.group(1).strip()
    return {
        "title": title,
        "required_text": required_text,
        "aspect_ratio": aspect_ratio,
        "max_colors": max_colors,
        "include_motifs": include_motifs,
    }


class _MoodboardParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hexes = []
        self.tags = []
        self._in_tags_ul = False
        self._in_li = False

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag.lower() == "div":
            cls = attrs_dict.get("class", "")
            if isinstance(cls, str) and "swatch" in cls.split():
                hx = attrs_dict.get("data-hex")
                if hx and hx.strip().startswith("#"):
                    self.hexes.append(hx.strip().upper())
        if tag.lower() == "ul":
            if attrs_dict.get("id", "") == "tags":
                self._in_tags_ul = True
        if self._in_tags_ul and tag.lower() == "li":
            self._in_li = True

    def handle_endtag(self, tag):
        if tag.lower() == "ul" and self._in_tags_ul:
            self._in_tags_ul = False
        if tag.lower() == "li" and self._in_li:
            self._in_li = False

    def handle_data(self, data):
        if self._in_tags_ul and self._in_li:
            text = (data or "").strip()
            if text:
                self.tags.append(text)


def _parse_moodboard_html(p: Path):
    text = _read_text(p)
    if text is None:
        return None
    parser = _MoodboardParser()
    try:
        parser.feed(text)
    except Exception:
        return None
    def _dedup(seq):
        seen = set()
        out = []
        for x in seq:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out
    return {
        "hexes": _dedup(parser.hexes),
        "tags": _dedup(parser.tags),
    }


def _normalize_hex(h: str) -> str:
    if not isinstance(h, str):
        return None
    h = h.strip()
    if not h:
        return None
    if h.startswith("#"):
        h = h.upper()
        if re.fullmatch(r"#[0-9A-F]{3}", h):
            return "#" + "".join(ch * 2 for ch in h[1:])
        if re.fullmatch(r"#[0-9A-F]{6}", h):
            return h
        return None
    return None


def _rgb_to_hex(s: str) -> str:
    m = re.fullmatch(r"rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)", s.strip(), flags=re.IGNORECASE)
    if not m:
        return None
    r, g, b = [int(m.group(i)) for i in range(1, 4)]
    if any(not (0 <= v <= 255) for v in (r, g, b)):
        return None
    return "#{:02X}{:02X}{:02X}".format(r, g, b)


_COLOR_NAME_MAP = {
    "white": "#FFFFFF",
    "black": "#000000",
    "gray": "#808080",
    "grey": "#808080",
    "magenta": "#FF00FF",
    "cyan": "#00FFFF",
    "yellow": "#FFFF00",
    "lime": "#00FF00",
    "red": "#FF0000",
    "green": "#008000",
    "blue": "#0000FF",
}


def _extract_colors_from_svg_text(svg_text: str):
    if svg_text is None:
        return None
    colors = set()
    for hx in re.findall(r"#[0-9a-fA-F]{3,6}", svg_text):
        norm = _normalize_hex(hx)
        if norm:
            colors.add(norm)
    for rgb in re.findall(r"rgb\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*\)", svg_text, flags=re.IGNORECASE):
        hx = _rgb_to_hex(rgb)
        if hx:
            colors.add(hx)
    for attr, val in re.findall(r'(fill|stroke)\s*=\s*["\']([^"\']+)["\']', svg_text, flags=re.IGNORECASE):
        v = val.strip().lower()
        if v in _COLOR_NAME_MAP:
            colors.add(_COLOR_NAME_MAP[v].upper())
        else:
            pass
    for style in re.findall(r'style\s*=\s*["\']([^"\']+)["\']', svg_text, flags=re.IGNORECASE):
        for prop, val in re.findall(r'(fill|stroke)\s*:\s*([^;]+)', style, flags=re.IGNORECASE):
            v = val.strip()
            hx = None
            if v.lower() in _COLOR_NAME_MAP:
                hx = _COLOR_NAME_MAP[v.lower()].upper()
            elif v.startswith("#"):
                hx = _normalize_hex(v)
            else:
                rgb_hex = _rgb_to_hex(v)
                if rgb_hex:
                    hx = rgb_hex
            if hx:
                colors.add(hx)
    return colors


def _parse_svg_dimensions(svg_text: str):
    if svg_text is None:
        return None
    width = None
    height = None
    vw = None
    vh = None
    mw = re.search(r'width\s*=\s*["\']\s*(\d+)\s*(?:px)?\s*["\']', svg_text)
    mh = re.search(r'height\s*=\s*["\']\s*(\d+)\s*(?:px)?\s*["\']', svg_text)
    if mw:
        try:
            width = int(mw.group(1))
        except Exception:
            width = None
    if mh:
        try:
            height = int(mh.group(1))
        except Exception:
            height = None
    mvb = re.search(r'viewBox\s*=\s*["\']\s*0\s+0\s+(\d+)\s+(\d+)\s*["\']', svg_text)
    if mvb:
        try:
            vw = int(mvb.group(1))
            vh = int(mvb.group(2))
        except Exception:
            vw = None
            vh = None
    return {
        "width": width,
        "height": height,
        "viewbox_width": vw,
        "viewbox_height": vh,
    }


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "extracted_json_matches_inputs": 0.0,
        "manifest_structure_and_filenames": 0.0,
        "posters_exist_and_named_exactly": 0.0,
        "dimensions_1080x1350_manifest_and_svg": 0.0,
        "svg_contains_required_text": 0.0,
        "manifest_contains_required_text_true": 0.0,
        "colors_within_allowed": 0.0,
        "max_colors_per_poster": 0.0,
        "manifest_used_colors_match_svg": 0.0,
        "manifest_used_tags_valid": 0.0,
        "validate_script_exists_and_references": 0.0,
        "tests_file_exists_and_references": 0.0,
        "generate_script_exists_and_references": 0.0,
    }

    brief_info = _parse_brief_md(workspace / "input" / "brief.md")
    palette_hexes = _parse_palette_csv(workspace / "input" / "palette.csv")
    moodboard_info = _parse_moodboard_html(workspace / "input" / "moodboard.html")

    expected = {}
    if brief_info and palette_hexes is not None and moodboard_info:
        expected["title"] = brief_info.get("title")
        expected["required_text"] = brief_info.get("required_text")
        expected["aspect_ratio"] = brief_info.get("aspect_ratio")
        expected["max_colors"] = brief_info.get("max_colors")
        expected["include_motifs"] = brief_info.get("include_motifs") or []
        expected["palette_hexes"] = [h.upper() for h in palette_hexes]
        expected["moodboard_hexes"] = [h.upper() for h in moodboard_info.get("hexes", [])]
        expected["tags"] = moodboard_info.get("tags", [])
    else:
        expected = None

    extracted_path = workspace / "output" / "extracted.json"
    extracted = _load_json(extracted_path)
    extracted_ok = False
    if expected and isinstance(extracted, dict):
        required_keys = [
            "title",
            "required_text",
            "aspect_ratio",
            "max_colors",
            "include_motifs",
            "palette_hexes",
            "moodboard_hexes",
            "tags",
        ]
        if all(k in extracted for k in required_keys):
            try:
                conds = []
                conds.append(extracted.get("title") == expected["title"])
                conds.append(extracted.get("required_text") == expected["required_text"])
                conds.append(str(extracted.get("aspect_ratio")) == str(expected["aspect_ratio"]))
                conds.append(int(extracted.get("max_colors")) == int(expected["max_colors"]))
                inc_motifs = extracted.get("include_motifs") or []
                conds.append(set([m.strip().lower() for m in inc_motifs]) == set([m.strip().lower() for m in expected["include_motifs"]]))
                pal_hexes = [str(h).upper() for h in (extracted.get("palette_hexes") or [])]
                mood_hexes = [str(h).upper() for h in (extracted.get("moodboard_hexes") or [])]
                conds.append(set(pal_hexes) == set(expected["palette_hexes"]))
                conds.append(set(mood_hexes) == set([h.upper() for h in expected["moodboard_hexes"]]))
                tags_list = extracted.get("tags") or []
                conds.append(set(tags_list) == set(expected["tags"]))
                extracted_ok = all(conds)
            except Exception:
                extracted_ok = False
    scores["extracted_json_matches_inputs"] = 1.0 if extracted_ok else 0.0

    manifest_path = workspace / "output" / "manifest.json"
    manifest = _load_json(manifest_path)
    expected_filenames = ["poster_01.svg", "poster_02.svg", "poster_03.svg"]

    manifest_structure_ok = False
    manifest_entries_by_name = {}
    if isinstance(manifest, list) and len(manifest) == 3:
        has_required_fields = True
        names = []
        for entry in manifest:
            if not isinstance(entry, dict):
                has_required_fields = False
                break
            for key in ["filename", "width", "height", "used_colors", "used_tags", "contains_required_text"]:
                if key not in entry:
                    has_required_fields = False
                    break
            if not has_required_fields:
                break
            names.append(entry.get("filename"))
            manifest_entries_by_name[entry.get("filename")] = entry
        if has_required_fields and sorted(names) == sorted(expected_filenames):
            manifest_structure_ok = True
    scores["manifest_structure_and_filenames"] = 1.0 if manifest_structure_ok else 0.0

    posters_dir = workspace / "output" / "posters"
    posters_exist_ok = False
    if posters_dir.exists() and posters_dir.is_dir():
        files = sorted([p.name for p in posters_dir.glob("*.svg")])
        posters_exist_ok = (sorted(files) == sorted(expected_filenames) and len(files) == 3)
    scores["posters_exist_and_named_exactly"] = 1.0 if posters_exist_ok else 0.0

    dims_ok = False
    req_text_ok = False
    manifest_req_text_ok = False
    colors_allowed_ok = False
    max_colors_ok = False
    manifest_used_colors_ok = False
    used_tags_ok = False

    allowed_union = set()
    if expected:
        allowed_union = set([h.upper() for h in expected.get("palette_hexes", [])] + [h.upper() for h in expected.get("moodboard_hexes", [])])
    required_text = expected.get("required_text") if expected else None
    max_colors = expected.get("max_colors") if expected else None
    tags_set = set(expected.get("tags") if expected else [])

    if posters_exist_ok and manifest_structure_ok and expected:
        all_dims = True
        all_req_text_present = True
        all_manifest_req_text_true = True
        all_color_within = True
        all_max_colors = True
        all_manifest_colors_match = True
        all_used_tags_valid = True

        for fname in expected_filenames:
            svg_path = posters_dir / fname
            svg_text = _read_text(svg_path)
            if not svg_text:
                all_dims = False
                all_req_text_present = False
                all_manifest_req_text_true = False
                all_color_within = False
                all_max_colors = False
                all_manifest_colors_match = False
                all_used_tags_valid = False
                continue

            d = _parse_svg_dimensions(svg_text)
            w_attr = d.get("width")
            h_attr = d.get("height")
            vw = d.get("viewbox_width")
            vh = d.get("viewbox_height")
            svg_dim_match = False
            if w_attr is not None and h_attr is not None:
                svg_dim_match = (w_attr == 1080 and h_attr == 1350)
            if (w_attr is None or h_attr is None) and (vw is not None and vh is not None):
                svg_dim_match = (vw == 1080 and vh == 1350)
            if (w_attr is not None and h_attr is not None) and (vw is not None and vh is not None):
                svg_dim_match = (w_attr == 1080 and h_attr == 1350 and vw == 1080 and vh == 1350)
            m_entry = manifest_entries_by_name.get(fname, {})
            m_w = m_entry.get("width")
            m_h = m_entry.get("height")
            manifest_dim_match = (m_w == 1080 and m_h == 1350)
            all_dims = all_dims and svg_dim_match and manifest_dim_match

            contains = (required_text in svg_text) if isinstance(required_text, str) else False
            all_req_text_present = all_req_text_present and contains
            m_contains = bool(m_entry.get("contains_required_text"))
            all_manifest_req_text_true = all_manifest_req_text_true and m_contains

            used_colors_svg = _extract_colors_from_svg_text(svg_text)
            if used_colors_svg is None:
                all_color_within = False
                all_max_colors = False
                all_manifest_colors_match = False
            else:
                used_colors_svg = set([c.upper() for c in used_colors_svg])
                invalid = [c for c in used_colors_svg if c not in allowed_union]
                all_color_within = all_color_within and (len(invalid) == 0)
                if isinstance(max_colors, int):
                    all_max_colors = all_max_colors and (len(used_colors_svg) <= max_colors)
                else:
                    all_max_colors = False
                m_used_colors = m_entry.get("used_colors")
                if isinstance(m_used_colors, list):
                    m_used_norm = set()
                    for c in m_used_colors:
                        if isinstance(c, str) and c.strip():
                            c_norm = None
                            if c.strip().startswith("#"):
                                c_norm = _normalize_hex(c.strip())
                            else:
                                c_norm_hex = _rgb_to_hex(c.strip())
                                if c_norm_hex:
                                    c_norm = c_norm_hex
                                else:
                                    cname_hex = _COLOR_NAME_MAP.get(c.strip().lower())
                                    c_norm = cname_hex
                            if c_norm:
                                m_used_norm.add(c_norm.upper())
                            else:
                                m_used_norm.add(c.strip().upper())
                    all_manifest_colors_match = all_manifest_colors_match and (m_used_norm == used_colors_svg)
                else:
                    all_manifest_colors_match = False

            u_tags = m_entry.get("used_tags")
            if isinstance(u_tags, list) and len(u_tags) >= 1:
                all_used_tags_valid = all_used_tags_valid and set(u_tags).issubset(tags_set)
            else:
                all_used_tags_valid = False

        dims_ok = all_dims
        req_text_ok = all_req_text_present
        manifest_req_text_ok = all_manifest_req_text_true
        colors_allowed_ok = all_color_within
        max_colors_ok = all_max_colors
        manifest_used_colors_ok = all_manifest_colors_match
        used_tags_ok = all_used_tags_valid

    scores["dimensions_1080x1350_manifest_and_svg"] = 1.0 if dims_ok else 0.0
    scores["svg_contains_required_text"] = 1.0 if req_text_ok else 0.0
    scores["manifest_contains_required_text_true"] = 1.0 if manifest_req_text_ok else 0.0
    scores["colors_within_allowed"] = 1.0 if colors_allowed_ok else 0.0
    scores["max_colors_per_poster"] = 1.0 if max_colors_ok else 0.0
    scores["manifest_used_colors_match_svg"] = 1.0 if manifest_used_colors_ok else 0.0
    scores["manifest_used_tags_valid"] = 1.0 if used_tags_ok else 0.0

    validate_py = workspace / "validate.py"
    validate_ok = False
    vt = _read_text(validate_py) if validate_py.exists() else None
    if vt:
        refs_ok = ("output/posters" in vt) and ("output/manifest.json" in vt) and ("reports/validation.json" in vt)
        validate_ok = refs_ok
    scores["validate_script_exists_and_references"] = 1.0 if validate_ok else 0.0

    tests_py = workspace / "tests" / "test_outputs.py"
    tests_ok = False
    tt = _read_text(tests_py) if tests_py.exists() else None
    if tt:
        refs = all([
            "output/extracted.json" in tt,
            "output/manifest.json" in tt,
            "poster_01.svg" in tt,
            "output/posters" in tt,
        ])
        tests_ok = refs
    scores["tests_file_exists_and_references"] = 1.0 if tests_ok else 0.0

    generate_py = workspace / "generate.py"
    gen_ok = False
    gt = _read_text(generate_py) if generate_py.exists() else None
    if gt:
        refs = ("input/" in gt) and ("output/" in gt)
        deterministic_hint = ("random.seed" in gt) or ("Determin" in gt) or ("assumption" in gt.lower())
        gen_ok = refs and deterministic_hint
    scores["generate_script_exists_and_references"] = 1.0 if gen_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()