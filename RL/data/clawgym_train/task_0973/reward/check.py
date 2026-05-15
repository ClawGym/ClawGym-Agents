import json
import csv
import re
import sys
from pathlib import Path
from html.parser import HTMLParser
from typing import List, Dict, Any, Optional, Tuple, Set


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows
    except Exception:
        return None


def _safe_float(x) -> Optional[float]:
    try:
        if x is None:
            return None
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip()
        if s == "" or s.lower() == "na":
            return None
        return float(s)
    except Exception:
        return None


def _safe_int(x) -> Optional[int]:
    try:
        if x is None:
            return None
        if isinstance(x, bool):
            return int(x)
        if isinstance(x, int):
            return x
        if isinstance(x, float) and x.is_integer():
            return int(x)
        s = str(x).strip()
        if s == "" or s.lower() == "na":
            return None
        if "." in s:
            f = float(s)
            if f.is_integer():
                return int(f)
            return None
        return int(s)
    except Exception:
        return None


def _parse_themes_yaml(path: Path) -> Optional[Dict[str, List[str]]]:
    text = _read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    in_themes = False
    themes: Dict[str, List[str]] = {}
    curr_theme: Optional[str] = None
    try:
        for raw_line in lines:
            line = raw_line.rstrip()
            if not in_themes:
                if re.match(r"^\s*themes:\s*$", line):
                    in_themes = True
                continue
            m_theme = re.match(r"^\s{2}([A-Za-z0-9_]+):\s*$", line)
            if m_theme:
                curr_theme = m_theme.group(1)
                themes[curr_theme] = []
                continue
            if curr_theme is not None:
                m_kw = re.match(r'^\s{4}keywords:\s*\[(.*)\]\s*$', line)
                if m_kw:
                    inner = m_kw.group(1).strip()
                    items = []
                    buf = ""
                    in_quote = False
                    quote_char = None
                    for ch in inner:
                        if ch in ("'", '"'):
                            if in_quote and ch == quote_char:
                                in_quote = False
                                quote_char = None
                            elif not in_quote:
                                in_quote = True
                                quote_char = ch
                            else:
                                buf += ch
                        elif ch == "," and not in_quote:
                            item = buf.strip()
                            if (item.startswith('"') and item.endswith('"')) or (item.startswith("'") and item.endswith("'")):
                                item = item[1:-1]
                            if item != "":
                                items.append(item)
                            buf = ""
                        else:
                            buf += ch
                    last = buf.strip()
                    if last:
                        if (last.startswith('"') and last.endswith('"')) or (last.startswith("'") and last.endswith("'")):
                            last = last[1:-1]
                        items.append(last)
                    themes[curr_theme] = [it for it in (i.strip() for i in items) if it != ""]
                    continue
        if not themes:
            return None
        return themes
    except Exception:
        return None


class _FeedbackHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_li = False
        self.in_p_text = False
        self.current_li: Dict[str, Any] = {}
        self.items: List[Dict[str, Any]] = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag.lower() == "li" and ("class" in attrs_dict and "fb" in attrs_dict.get("class", "")):
            self.in_li = True
            self.current_li = {
                "id": attrs_dict.get("id"),
                "rating": attrs_dict.get("data-rating"),
                "text": "",
            }
        elif self.in_li and tag.lower() == "p":
            cls = attrs_dict.get("class", "")
            if "text" in cls or cls == "text":
                self.in_p_text = True
            else:
                self.in_p_text = True

    def handle_endtag(self, tag):
        if tag.lower() == "li" and self.in_li:
            if self.current_li.get("id") and self.current_li.get("text") is not None:
                self.current_li["text"] = self.current_li["text"].strip()
                self.items.append(self.current_li)
            self.in_li = False
            self.current_li = {}
        elif tag.lower() == "p" and self.in_p_text:
            self.in_p_text = False

    def handle_data(self, data):
        if self.in_li and self.in_p_text:
            self.current_li["text"] = (self.current_li.get("text", "") or "") + data


def _parse_web_feedback_html(path: Path) -> Optional[List[Dict[str, Any]]]:
    text = _read_text(path)
    if text is None:
        return None
    try:
        parser = _FeedbackHTMLParser()
        parser.feed(text)
        items = []
        for it in parser.items:
            r = _safe_int(it.get("rating"))
            items.append({
                "li_id": str(it.get("id")) if it.get("id") is not None else "",
                "rating": r,
                "text": it.get("text", "").strip(),
            })
        items = [x for x in items if x["li_id"] and x["text"]]
        return items
    except Exception:
        return None


def _parse_retrospective_md(path: Path) -> Optional[List[Dict[str, Any]]]:
    text = _read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    current_section = None
    items: List[Dict[str, Any]] = []
    try:
        for raw in lines:
            line = raw.rstrip()
            m_sec = re.match(r"^\s*##\s+(.*)\s*$", line)
            if m_sec:
                current_section = m_sec.group(1).strip().lower()
                continue
            m_item = re.match(r"^\s*-\s*\[id:\s*([^\]]+)\]\s*(.*)\s*$", line)
            if m_item:
                rid = m_item.group(1).strip()
                text_item = m_item.group(2).strip()
                items.append({
                    "retroid": rid,
                    "section": current_section or "",
                    "text": text_item,
                })
        return items
    except Exception:
        return None


def _compile_theme_patterns(themes: Dict[str, List[str]]) -> Dict[str, List[re.Pattern]]:
    compiled: Dict[str, List[re.Pattern]] = {}
    for theme, keywords in themes.items():
        pats = []
        for kw in keywords:
            pattern = r"(?i)(?<!\w)" + re.escape(kw) + r"(?!\w)"
            pats.append(re.compile(pattern))
        compiled[theme] = pats
    return compiled


def _detect_themes(text: str, compiled: Dict[str, List[re.Pattern]]) -> List[str]:
    found = []
    for theme, pats in compiled.items():
        for pat in pats:
            if pat.search(text):
                found.append(theme)
                break
    return found


def _compute_expected_mentions(workspace: Path) -> Optional[List[Dict[str, Any]]]:
    feedback_csv = _load_csv(workspace / "input" / "feedback.csv")
    web_feedback = _parse_web_feedback_html(workspace / "input" / "web_feedback.html")
    retro_items = _parse_retrospective_md(workspace / "input" / "retrospective.md")
    themes_map = _parse_themes_yaml(workspace / "input" / "themes.yaml")
    if feedback_csv is None or web_feedback is None or retro_items is None or themes_map is None:
        return None
    compiled = _compile_theme_patterns(themes_map)
    mentions: List[Dict[str, Any]] = []

    for row in feedback_csv:
        attendee_id = str(row.get("attendee_id", "")).strip()
        comment = (row.get("comment") or "").strip()
        rating = _safe_int(row.get("rating"))
        if attendee_id == "" or comment == "" or rating is None:
            continue
        themes = _detect_themes(comment.lower(), compiled)
        if rating <= 2:
            sentiment = "negative"
        elif rating == 3:
            sentiment = "neutral"
        else:
            sentiment = "positive"
        mentions.append({
            "id": f"csv-{attendee_id}",
            "source_file": "feedback.csv",
            "source_id": attendee_id,
            "text": comment,
            "sentiment": sentiment,
            "themes": sorted(themes),
            "rating": rating,
        })

    for it in web_feedback:
        li_id = it["li_id"]
        text = it["text"]
        rating = it["rating"]
        if not li_id or text == "" or rating is None:
            continue
        themes = _detect_themes(text.lower(), compiled)
        if rating <= 2:
            sentiment = "negative"
        elif rating == 3:
            sentiment = "neutral"
        else:
            sentiment = "positive"
        mentions.append({
            "id": f"html-{li_id}",
            "source_file": "web_feedback.html",
            "source_id": li_id,
            "text": text,
            "sentiment": sentiment,
            "themes": sorted(themes),
            "rating": rating,
        })

    for it in retro_items:
        rid = it["retroid"]
        text = it["text"]
        section = (it.get("section") or "").lower()
        themes = _detect_themes(text.lower(), compiled)
        if "what could be improved" in section:
            sentiment = "negative"
        elif "what went well" in section:
            sentiment = "positive"
        else:
            sentiment = "neutral"
        mentions.append({
            "id": f"md-{rid}",
            "source_file": "retrospective.md",
            "source_id": rid,
            "text": text,
            "sentiment": sentiment,
            "themes": sorted(themes),
            "rating": None,
        })

    return mentions


def _group_themes(mentions: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    agg: Dict[str, Dict[str, Any]] = {}
    for m in mentions:
        for theme in m.get("themes", []):
            if theme not in agg:
                agg[theme] = {
                    "theme": theme,
                    "total_mentions": 0,
                    "negative_mentions": 0,
                    "neutral_mentions": 0,
                    "positive_mentions": 0,
                    "ratings": [],
                    "evidence_sources": set(),
                }
            entry = agg[theme]
            entry["total_mentions"] += 1
            sent = m.get("sentiment")
            if sent in ("negative", "neutral", "positive"):
                entry[f"{sent}_mentions"] += 1
            src_file = m.get("source_file")
            if src_file == "feedback.csv":
                entry["evidence_sources"].add("csv")
            elif src_file == "web_feedback.html":
                entry["evidence_sources"].add("html")
            elif src_file == "retrospective.md":
                entry["evidence_sources"].add("md")
            if src_file in ("feedback.csv", "web_feedback.html"):
                r = _safe_float(m.get("rating"))
                if r is not None:
                    entry["ratings"].append(r)
    for theme, entry in agg.items():
        neg = entry["negative_mentions"]
        neu = entry["neutral_mentions"]
        pos = entry["positive_mentions"]
        entry["priority_score"] = 2 * neg + 1 * neu - 1 * pos
        if entry["ratings"]:
            entry["avg_rating"] = sum(entry["ratings"]) / len(entry["ratings"])
        else:
            entry["avg_rating"] = None
        entry["evidence_sources"] = set(entry["evidence_sources"])
    return agg


def _load_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        records = []
        for i, line in enumerate(lines):
            s = line.strip()
            if not s:
                continue
            obj = json.loads(s)
            if not isinstance(obj, dict):
                return None
            records.append(obj)
        return records
    except Exception:
        return None


def _load_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows
    except Exception:
        return None


def _normalize_evidence_sources_field(val: str) -> Set[str]:
    if val is None:
        return set()
    parts = [p.strip().lower() for p in str(val).split("|") if p.strip() != ""]
    return set(parts)


def _find_section(text: str, header: str) -> str:
    lines = text.splitlines()
    content_lines: List[str] = []
    in_section = False
    for i, line in enumerate(lines):
        if header.lower() in line.lower():
            in_section = True
            continue
        if in_section:
            if re.match(r"^\s*#{1,6}\s+", line):
                break
            if any(h in line.lower() for h in ["positive highlights", "top 5 improvement themes", "next iteration actions"]) and header.lower() not in line.lower():
                break
            content_lines.append(line)
    return "\n".join(content_lines).strip()


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "extracted_mentions_file_valid": 0.0,
        "extracted_mentions_coverage": 0.0,
        "extracted_mentions_field_accuracy": 0.0,
        "extracted_mentions_id_uniqueness": 0.0,
        "themes_ranked_file_valid": 0.0,
        "themes_ranked_rowset_and_order": 0.0,
        "themes_ranked_values_accuracy": 0.0,
        "summary_opening_line": 0.0,
        "summary_top_improvement_themes": 0.0,
        "summary_positive_highlights": 0.0,
        "summary_next_iteration_actions": 0.0,
    }

    expected_mentions = _compute_expected_mentions(workspace)
    if expected_mentions is None:
        return scores

    expected_index: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for m in expected_mentions:
        key = (m["source_file"], str(m["source_id"]))
        expected_index[key] = m

    student_mentions_path = workspace / "output" / "extracted_mentions.jsonl"
    student_mentions = _load_jsonl(student_mentions_path)
    if student_mentions is None:
        scores["extracted_mentions_file_valid"] = 0.0
    else:
        scores["extracted_mentions_file_valid"] = 1.0
        student_index: Dict[Tuple[str, str], Dict[str, Any]] = {}
        ids_seen: Set[str] = set()
        ids_nonempty = True
        duplicate_free = True
        basic_fields_ok = True
        for obj in student_mentions:
            if not all(k in obj for k in ["id", "source_file", "source_id", "text", "sentiment", "themes", "rating"]):
                basic_fields_ok = False
                continue
            id_val = obj.get("id")
            if not isinstance(id_val, str) or id_val.strip() == "":
                ids_nonempty = False
            if id_val in ids_seen:
                duplicate_free = False
            ids_seen.add(id_val)
            key = (str(obj.get("source_file")), str(obj.get("source_id")))
            student_index[key] = obj
        scores["extracted_mentions_id_uniqueness"] = 1.0 if (ids_nonempty and duplicate_free and basic_fields_ok) else 0.0

        exp_keys = set(expected_index.keys())
        stu_keys = set(student_index.keys())
        scores["extracted_mentions_coverage"] = 1.0 if exp_keys == stu_keys else 0.0

        field_ok = True
        for key, exp in expected_index.items():
            stu = student_index.get(key)
            if stu is None:
                field_ok = False
                break
            if stu.get("source_file") != exp.get("source_file"):
                field_ok = False
                break
            if str(stu.get("source_id")) != str(exp.get("source_id")):
                field_ok = False
                break
            if (stu.get("text") or "").strip() != (exp.get("text") or "").strip():
                field_ok = False
                break
            if stu.get("sentiment") not in ("negative", "neutral", "positive"):
                field_ok = False
                break
            if stu.get("sentiment") != exp.get("sentiment"):
                field_ok = False
                break
            if exp.get("source_file") in ("feedback.csv", "web_feedback.html"):
                r_stu = _safe_int(stu.get("rating"))
                r_exp = _safe_int(exp.get("rating"))
                if r_stu is None or r_exp is None or r_stu != r_exp:
                    field_ok = False
                    break
            else:
                if stu.get("rating") is not None:
                    field_ok = False
                    break
            stu_themes = stu.get("themes")
            if not isinstance(stu_themes, list):
                field_ok = False
                break
            stu_set = set([str(t) for t in stu_themes])
            exp_set = set(exp.get("themes", []))
            if stu_set != exp_set:
                field_ok = False
                break
        scores["extracted_mentions_field_accuracy"] = 1.0 if field_ok else 0.0

    theme_agg = _group_themes(expected_mentions)
    unique_themes_before_filter = set(theme_agg.keys())
    rows_expected: List[Dict[str, Any]] = []
    for theme, entry in theme_agg.items():
        if entry["total_mentions"] < 2:
            continue
        rows_expected.append({
            "theme": theme,
            "total_mentions": entry["total_mentions"],
            "negative_mentions": entry["negative_mentions"],
            "neutral_mentions": entry["neutral_mentions"],
            "positive_mentions": entry["positive_mentions"],
            "priority_score": entry["priority_score"],
            "avg_rating": entry["avg_rating"],
            "evidence_sources": entry["evidence_sources"],
        })
    rows_expected.sort(key=lambda r: (-r["priority_score"], -r["total_mentions"], r["theme"]))

    student_themes_path = workspace / "output" / "themes_ranked.csv"
    stu_rows = _load_csv_rows(student_themes_path)
    if stu_rows is None:
        scores["themes_ranked_file_valid"] = 0.0
    else:
        header_ok = False
        try:
            with student_themes_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, [])
                header_ok = header == [
                    "theme",
                    "total_mentions",
                    "negative_mentions",
                    "neutral_mentions",
                    "positive_mentions",
                    "priority_score",
                    "avg_rating_from_feedback",
                    "evidence_sources",
                ]
        except Exception:
            header_ok = False
        scores["themes_ranked_file_valid"] = 1.0 if header_ok else 0.0

        order_ok = True
        values_ok = True
        if stu_rows is None:
            order_ok = False
            values_ok = False
        else:
            if len(stu_rows) != len(rows_expected):
                order_ok = False
            for i, exp in enumerate(rows_expected):
                if i >= len(stu_rows):
                    order_ok = False
                    values_ok = False
                    break
                row = stu_rows[i]
                if row.get("theme") != exp["theme"]:
                    order_ok = False
                for col in ["total_mentions", "negative_mentions", "neutral_mentions", "positive_mentions", "priority_score"]:
                    val = _safe_int(row.get(col))
                    if val is None or val != int(exp[col]):
                        values_ok = False
                avg_field = row.get("avg_rating_from_feedback", "")
                exp_avg = exp["avg_rating"]
                if exp_avg is None:
                    if not (avg_field.strip() == "" or avg_field.strip().lower() == "na"):
                        values_ok = False
                else:
                    got_avg = _safe_float(avg_field)
                    if got_avg is None:
                        values_ok = False
                    else:
                        if abs(got_avg - float(exp_avg)) > 1e-6:
                            values_ok = False
                got_sources = _normalize_evidence_sources_field(row.get("evidence_sources", ""))
                exp_sources = set(exp["evidence_sources"])
                if got_sources != exp_sources:
                    values_ok = False
        scores["themes_ranked_rowset_and_order"] = 1.0 if order_ok else 0.0
        scores["themes_ranked_values_accuracy"] = 1.0 if values_ok else 0.0

    summary_path = workspace / "output" / "summary.md"
    summary_text = _read_text(summary_path)
    if summary_text is None:
        return scores
    else:
        expected_N = len(expected_mentions)
        expected_M = len(unique_themes_before_filter)
        opening_pattern = re.compile(
            r"Analyzed\s+{N}\s+mentions\s+across\s+{M}\s+themes\s+from\s+3\s+sources\.?".format(
                N=expected_N, M=expected_M
            )
        )
        scores["summary_opening_line"] = 1.0 if opening_pattern.search(summary_text) else 0.0

        top_improvement = [r for r in rows_expected if r["priority_score"] > 0][:5]
        top_section = _find_section(summary_text, "Top 5 Improvement Themes")
        top_ok = True
        if not top_section and top_improvement:
            top_ok = False
        else:
            prev_pos = -1
            for r in top_improvement:
                theme = r["theme"]
                neg = r["negative_mentions"]
                neu = r["neutral_mentions"]
                pos = r["positive_mentions"]
                prio = r["priority_score"]
                m = re.search(re.escape(theme), top_section)
                if not m:
                    top_ok = False
                    break
                if m.start() <= prev_pos:
                    top_ok = False
                    break
                prev_pos = m.start()
                section_after = top_section[m.start():]
                if not (re.search(r"\b" + str(neg) + r"\b", section_after) and
                        re.search(r"\b" + str(neu) + r"\b", section_after) and
                        re.search(r"\b" + str(pos) + r"\b", section_after) and
                        re.search(r"\b" + str(prio) + r"\b", section_after)):
                    top_ok = False
                    break
                neg_mentions = []
                for mexp in expected_mentions:
                    if theme in mexp.get("themes", []) and mexp.get("sentiment") == "negative":
                        neg_mentions.append((mexp["text"], mexp["source_file"], str(mexp["source_id"])))
                if neg_mentions:
                    found_quote = False
                    for line in top_section.splitlines():
                        if not line.strip().startswith(">"):
                            continue
                        for (txt, src_file, src_id) in neg_mentions:
                            if txt in line and re.search(r"\(" + re.escape(src_file) + r".*" + re.escape(src_id) + r"\)", line):
                                found_quote = True
                                break
                        if found_quote:
                            break
                    if not found_quote:
                        top_ok = False
                        break
                else:
                    top_ok = False
                    break
        scores["summary_top_improvement_themes"] = 1.0 if top_ok else 0.0

        pos_section = _find_section(summary_text, "Positive Highlights")
        pos_ok = True
        all_by_pos = sorted(
            [{**r} for r in _group_themes(expected_mentions).values()],
            key=lambda e: (-e["positive_mentions"], e["theme"])
        )
        top_pos = [r for r in all_by_pos if r["positive_mentions"] > 0][:3]
        if top_pos:
            if not pos_section:
                pos_ok = False
            else:
                for r in top_pos:
                    theme = r["theme"]
                    pos_count = r["positive_mentions"]
                    if re.search(re.escape(theme), pos_section) is None:
                        pos_ok = False
                        break
                    if re.search(r"\b" + str(pos_count) + r"\b", pos_section) is None:
                        pos_ok = False
                        break
        scores["summary_positive_highlights"] = 1.0 if pos_ok else 0.0

        act_section = _find_section(summary_text, "Next Iteration Actions")
        actions_ok = False
        if act_section:
            lines = [ln for ln in act_section.splitlines() if ln.strip().startswith(("-", "*"))]
            top_theme_names = [r["theme"] for r in top_improvement]
            count_ref = 0
            for ln in lines:
                if any(name in ln for name in top_theme_names):
                    count_ref += 1
            actions_ok = count_ref >= 3
        scores["summary_next_iteration_actions"] = 1.0 if actions_ok else 0.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()