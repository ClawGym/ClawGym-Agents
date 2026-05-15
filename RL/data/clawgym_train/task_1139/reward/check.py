import csv
import json
import sys
from html.parser import HTMLParser
from pathlib import Path


def _safe_read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_read_csv(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, None
        header = rows[0]
        data = rows[1:]
        return header, data
    except Exception:
        return None, None


class _RosterHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_roster_table = False
        self.in_tbody = False
        self.in_tr = False
        self.in_td = False
        self.current_row = []
        self.rows = []
        self._table_stack = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "table":
            self._table_stack.append(attrs_dict.get("id") == "roster")
            if attrs_dict.get("id") == "roster":
                self.in_roster_table = True
        if self.in_roster_table:
            if tag == "tbody":
                self.in_tbody = True
            if self.in_tbody and tag == "tr":
                self.in_tr = True
                self.current_row = []
            if self.in_tr and tag == "td":
                self.in_td = True

    def handle_endtag(self, tag):
        if self.in_roster_table:
            if tag == "td":
                self.in_td = False
            if tag == "tr" and self.in_tr:
                self.in_tr = False
                if len(self.current_row) == 4:
                    self.rows.append(self.current_row)
                self.current_row = []
            if tag == "tbody":
                self.in_tbody = False
        if tag == "table":
            if self._table_stack:
                was_roster = self._table_stack.pop()
                if was_roster:
                    self.in_roster_table = False

    def handle_data(self, data):
        if self.in_roster_table and self.in_tbody and self.in_tr and self.in_td:
            text = data.strip()
            if text != "":
                self.current_row.append(text)


def _parse_roster_html(html_text: str):
    try:
        parser = _RosterHTMLParser()
        parser.feed(html_text)
        return parser.rows
    except Exception:
        return None


def _parse_event_info(path: Path):
    text = _safe_read_text(path)
    if text is None:
        return None
    info = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if "：" in line:
            key, val = line.split("：", 1)
        elif ":" in line:
            key, val = line.split(":", 1)
        else:
            continue
        key = key.strip()
        val = val.strip()
        if key in ("赛事名称", "中文名"):
            info["zh_name"] = val
        elif key in ("英文名", "English"):
            info["en_name"] = val
        elif key in ("日期", "Date"):
            info["date"] = val
        elif key in ("地点", "Venue"):
            info["venue"] = val
    return info


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def _load_simple_yaml(path: Path):
    text = _safe_read_text(path)
    if text is None:
        return None
    result = {}
    current_parent = None
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        if line.strip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0:
            if line.strip().endswith(":"):
                key = line.strip()[:-1].strip()
                current_parent = key
                result[key] = {}
            else:
                if ":" not in line:
                    continue
                k, v = line.split(":", 1)
                k = k.strip()
                v = _strip_quotes(v.strip())
                result[k] = v
                current_parent = None
        else:
            if current_parent is None:
                continue
            if ":" not in line:
                continue
            k, v = line.lstrip(" ").split(":", 1)
            k = k.strip()
            v = _strip_quotes(v.strip())
            if not isinstance(result.get(current_parent), dict):
                result[current_parent] = {}
            result[current_parent][k] = v
    return result


def _find_section(lines, header_text):
    indices = [i for i, ln in enumerate(lines) if ln.strip() == header_text]
    if not indices:
        return []
    start = indices[0] + 1
    for i in range(start, len(lines)):
        if lines[i].strip() in ("ENGLISH VERSION", "中文版本"):
            return lines[start:i]
    return lines[start:]


def _find_bullet_lines_with_patterns(section_lines, expected_patterns):
    matches = []
    indices = []
    for patt_name, patt in expected_patterns:
        found_idx = None
        start_search_at = indices[-1] + 1 if indices else 0
        for idx in range(start_search_at, len(section_lines)):
            ln = section_lines[idx]
            if patt in ln:
                found_idx = idx
                break
        if found_idx is None:
            return None, None
        matches.append((patt_name, section_lines[found_idx]))
        indices.append(found_idx)
    return matches, indices


def _compute_expected_highlights_from_csv(csv_rows):
    target_names = ["Su Bingtian", "Shelly-Ann Fraser-Pryce", "Armand Duplantis"]
    selected = []
    for row in csv_rows:
        if len(row) != 4:
            return None
        if row[0] in target_names:
            selected.append(row)
    required_order = ["Su Bingtian", "Shelly-Ann Fraser-Pryce", "Armand Duplantis"]
    names_in_selected = [r[0] for r in selected]
    if any(name not in names_in_selected for name in required_order):
        return None
    filtered = []
    for name in required_order:
        for row in selected:
            if row[0] == name and row not in filtered:
                filtered.append(row)
                break
    if len(filtered) != 3:
        return None
    expected = []
    for name, country, event, pb in filtered:
        slug = name.lower().replace(" ", "-")
        expected.append({
            "name": name,
            "country": country,
            "event": event,
            "personal_best": pb,
            "slug": slug
        })
    return expected


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "athletes_csv_columns_and_order": 0.0,
        "athletes_csv_matches_html_table": 0.0,
        "highlights_json_correct_selection_and_slug": 0.0,
        "signature_config_updated_fields": 0.0,
        "signature_config_untouched_fields": 0.0,
        "signature_output_copy_matches_config": 0.0,
        "email_headers_present": 0.0,
        "email_subjects_valid": 0.0,
        "email_english_paragraph_references_event": 0.0,
        "email_english_bullets_match_csv": 0.0,
        "email_english_cta_present": 0.0,
        "email_chinese_paragraph_includes_event_venue": 0.0,
        "email_chinese_bullets_match_csv": 0.0,
        "email_chinese_closing_present": 0.0,
        "email_signature_matches_config": 0.0,
    }

    roster_html_path = workspace / "input" / "roster.html"
    event_info_path = workspace / "input" / "event_zh.txt"
    athletes_csv_path = workspace / "output" / "athletes.csv"
    highlights_json_path = workspace / "output" / "highlights.json"
    signature_config_path = workspace / "config" / "signature.yaml"
    signature_output_path = workspace / "output" / "signature.yaml"
    email_md_path = workspace / "output" / "pitch_email_en_zh.md"

    roster_html_text = _safe_read_text(roster_html_path)
    expected_rows = None
    if roster_html_text is not None:
        expected_rows = _parse_roster_html(roster_html_text)

    csv_header, csv_rows = _safe_read_csv(athletes_csv_path)

    expected_header = ["name", "country", "event", "personal_best"]
    if csv_header is not None and csv_header == expected_header:
        scores["athletes_csv_columns_and_order"] = 1.0

    if expected_rows is not None and csv_rows is not None:
        if expected_rows == csv_rows:
            scores["athletes_csv_matches_html_table"] = 1.0

    highlights = _safe_load_json(highlights_json_path)
    if csv_rows is not None and highlights is not None and isinstance(highlights, list):
        expected_highlights = _compute_expected_highlights_from_csv(csv_rows)
        if expected_highlights is not None:
            def normalize_obj(o):
                required = {"name", "country", "event", "personal_best", "slug"}
                if not isinstance(o, dict):
                    return None
                if set(o.keys()) != required:
                    return None
                return {k: o[k] for k in ["name", "country", "event", "personal_best", "slug"]}
            normalized_actual = []
            ok = True
            if len(highlights) == 3:
                for o in highlights:
                    no = normalize_obj(o)
                    if no is None:
                        ok = False
                        break
                    normalized_actual.append(no)
                if ok and normalized_actual == expected_highlights:
                    scores["highlights_json_correct_selection_and_slug"] = 1.0

    sig_cfg = _load_simple_yaml(signature_config_path)
    sig_out = _load_simple_yaml(signature_output_path)

    updated_ok = False
    if sig_cfg is not None:
        name_zh = sig_cfg.get("name_zh")
        name_en = sig_cfg.get("name_en")
        contact = sig_cfg.get("contact") if isinstance(sig_cfg.get("contact"), dict) else {}
        wechat = contact.get("wechat")
        placeholders = {
            "name_zh": "<替换为你的中文名>",
            "name_en": "<Replace with your English name>",
            "wechat": "<替换为你的微信ID>",
        }
        if (
            isinstance(name_zh, str) and name_zh and name_zh != placeholders["name_zh"] and
            isinstance(name_en, str) and name_en and name_en != placeholders["name_en"] and
            isinstance(wechat, str) and wechat and wechat != placeholders["wechat"]
        ):
            scores["signature_config_updated_fields"] = 1.0
            updated_ok = True

        role_zh = sig_cfg.get("role_zh")
        role_en = sig_cfg.get("role_en")
        email_val = contact.get("email") if isinstance(contact, dict) else None
        # Only award untouched fields if the config has been updated (prevents awarding on scaffold-only state)
        if updated_ok and (
            role_zh == "体育解说员与故事讲述者" and
            role_en == "Sports Commentator & Storyteller" and
            email_val == "commentator@example.com"
        ):
            scores["signature_config_untouched_fields"] = 1.0

    if sig_cfg is not None and sig_out is not None:
        if sig_cfg == sig_out:
            scores["signature_output_copy_matches_config"] = 1.0

    email_text = _safe_read_text(email_md_path)
    event_info = _parse_event_info(event_info_path)

    if email_text is not None:
        lines = [ln.rstrip("\n") for ln in email_text.splitlines()]
        if any(ln.strip() == "ENGLISH VERSION" for ln in lines) and any(ln.strip() == "中文版本" for ln in lines):
            scores["email_headers_present"] = 1.0

        found_eng_subject = False
        found_zh_subject = False
        if event_info is not None:
            en_name = event_info.get("en_name", "Shanghai Sprint & Field Gala")
            zh_name = event_info.get("zh_name", "上海速度与飞翔精英赛")
            date_str = event_info.get("date", "2026-07-12")
        else:
            en_name = "Shanghai Sprint & Field Gala"
            zh_name = "上海速度与飞翔精英赛"
            date_str = "2026-07-12"
        for ln in lines:
            lns = ln.strip()
            if lns.startswith(en_name) and (date_str in lns) and ("meet preview" in lns.lower()):
                found_eng_subject = True
            if lns.startswith(zh_name) and (date_str in lns) and ("赛前看点" in lns):
                found_zh_subject = True
        if found_eng_subject and found_zh_subject:
            scores["email_subjects_valid"] = 1.0

        eng_section = _find_section(lines, "ENGLISH VERSION")
        zh_section = _find_section(lines, "中文版本")

        if eng_section:
            eng_text_full = "\n".join(eng_section)
            if (en_name in eng_text_full) and (date_str in eng_text_full):
                scores["email_english_paragraph_references_event"] = 1.0
            eng_text = eng_text_full.lower()
            contains_cta = False
            if any(word in eng_text for word in ["interview", "media", "press", "pr"]) and any(
                key in eng_text for key in ["discuss", "coordinate", "schedule", "connect"]
            ):
                contains_cta = True
            if contains_cta:
                scores["email_english_cta_present"] = 1.0

        if csv_rows is not None:
            target_names = ["Su Bingtian", "Shelly-Ann Fraser-Pryce", "Armand Duplantis"]
            row_map = {row[0]: row for row in csv_rows if len(row) == 4}
            expected_ordered = []
            for n in target_names:
                if n in row_map:
                    row = row_map[n]
                    expected_ordered.append((row[0], f"{row[0]} ({row[1]}, {row[2]}, {row[3]})"))
            if len(expected_ordered) == 3:
                if eng_section:
                    eng_matches, eng_indices = _find_bullet_lines_with_patterns(eng_section, expected_ordered)
                    if eng_matches is not None and len(eng_indices) == 3:
                        # Ensure exactly three highlight lines (no duplicates of expected patterns)
                        count_expected_occurrences = sum(
                            sum(1 for _ in [1] if patt in ln) for _, patt in expected_ordered for ln in eng_section
                        )
                        if count_expected_occurrences == 3:
                            scores["email_english_bullets_match_csv"] = 1.0
                if zh_section:
                    zh_matches, zh_indices = _find_bullet_lines_with_patterns(zh_section, expected_ordered)
                    if zh_matches is not None and len(zh_indices) == 3:
                        count_expected_occurrences = sum(
                            sum(1 for _ in [1] if patt in ln) for _, patt in expected_ordered for ln in zh_section
                        )
                        if count_expected_occurrences == 3:
                            scores["email_chinese_bullets_match_csv"] = 1.0

        if zh_section and event_info is not None:
            zh_text = "\n".join(zh_section)
            if (event_info.get("zh_name") or "") in zh_text and (event_info.get("venue") or "") in zh_text:
                scores["email_chinese_paragraph_includes_event_venue"] = 1.0

        if zh_section:
            tail = zh_section[-5:] if len(zh_section) >= 5 else zh_section
            tail_text = "\n".join(tail)
            if any(kw in tail_text for kw in ["感谢", "期待", "敬请", "欢迎", "请与我联系", "请", "合作"]):
                scores["email_chinese_closing_present"] = 1.0

        # Signature in email must match the modified signature; prefer output/signature.yaml if available
        ref_sig = sig_out if sig_out is not None else sig_cfg
        if ref_sig is not None and updated_ok:
            zh_header_idx = None
            for i, ln in enumerate(lines):
                if ln.strip() == "中文版本":
                    zh_header_idx = i
                    break
            idx_after = zh_header_idx if zh_header_idx is not None else 0
            tail_text = "\n".join(lines[idx_after:])
            contact = ref_sig.get("contact") if isinstance(ref_sig.get("contact"), dict) else {}
            required_values = [
                ref_sig.get("name_zh", ""),
                ref_sig.get("name_en", ""),
                ref_sig.get("role_zh", ""),
                ref_sig.get("role_en", ""),
                contact.get("email", ""),
                contact.get("wechat", "")
            ]
            if all(isinstance(v, str) and v and v in tail_text for v in required_values):
                scores["email_signature_matches_config"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()