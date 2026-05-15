import json
import csv
import math
import re
import sys
from pathlib import Path


def _read_text_safe(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_json_safe(p: Path):
    try:
        return json.loads(_read_text_safe(p))
    except Exception:
        return None


def _load_simple_yaml(p: Path):
    text = _read_text_safe(p)
    if not text:
        return None
    data = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        if val.startswith(("'", '"')) and val.endswith(("'", '"')) and len(val) >= 2:
            val = val[1:-1]
        try:
            if "." in val:
                f = float(val)
                data[key] = f
            else:
                i = int(val)
                data[key] = i
            continue
        except Exception:
            pass
        lower = val.lower()
        if lower in ("true", "false"):
            data[key] = (lower == "true")
        else:
            data[key] = val
    return data


def _parse_scenes(chapters_dir: Path):
    scenes = []
    if not chapters_dir.exists():
        return scenes
    for md_file in sorted(chapters_dir.glob("*.md")):
        text = _read_text_safe(md_file)
        if not text:
            continue
        pattern = re.compile(r"^###\s*Scene\s+(\d+)\s*:\s*(.+)$", re.MULTILINE)
        matches = list(pattern.finditer(text))
        for idx, m in enumerate(matches):
            scene_index = int(m.group(1))
            title = m.group(2).strip()
            start = m.end()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            content = text[start:end].strip()
            scenes.append({
                "chapter_file": md_file.name,
                "scene_index": scene_index,
                "title": title,
                "content": content
            })
    return scenes


def _build_keyword_patterns(keywords: dict):
    patterns = {}
    for kw in keywords.keys():
        if " " in kw:
            words = kw.split()
            pattern = r"(?i)(?<!\w)" + r"\s+".join([re.escape(w) for w in words]) + r"(?!\w)"
        else:
            if "-" in kw:
                pattern = r"(?i)(?<!\w)" + re.escape(kw) + r"(?!\w)"
            else:
                pattern = r"(?i)\b" + re.escape(kw) + r"\b"
        patterns[kw] = re.compile(pattern)
    return patterns


def _count_keyword_hits(text: str, patterns: dict):
    counts = {kw: 0 for kw in patterns.keys()}
    for kw, pat in patterns.items():
        hits = pat.findall(text)
        counts[kw] = len(hits)
    return counts


def _csv_read_dicts(p: Path):
    try:
        with p.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return rows, reader.fieldnames
    except Exception:
        return None, None


def _parse_int(s, default=None):
    try:
        return int(s)
    except Exception:
        try:
            f = float(s)
            if f.is_integer():
                return int(f)
            return default
        except Exception:
            return default


def _parse_float(s, default=None):
    try:
        return float(s)
    except Exception:
        return default


def _compute_expected(workspace: Path):
    keywords_path = workspace / "input" / "keywords.json"
    prefs_path = workspace / "input" / "preferences.yaml"
    chapters_dir = workspace / "input" / "chapters"

    keywords = _load_json_safe(keywords_path) or {}
    prefs = _load_simple_yaml(prefs_path) or {}
    weekly_hours = float(prefs.get("weekly_hours", 0.0))
    max_scenes = int(prefs.get("max_scenes", 0))
    words_per_15 = int(prefs.get("words_per_15min", 250))
    recipient = str(prefs.get("email_recipient_name", "")).strip()
    due_date = str(prefs.get("due_date", "")).strip()

    scenes = _parse_scenes(chapters_dir)
    patterns = _build_keyword_patterns(keywords) if keywords else {}

    metrics = []
    for sc in scenes:
        content = sc["content"]
        word_count = len(content.split())
        hits = _count_keyword_hits(content, patterns) if patterns else {}
        total_hits = sum(hits.values()) if hits else 0
        risk = 0.0
        for k, c in hits.items():
            risk += c * (keywords.get(k, 0))
        blocks = math.ceil(word_count / max(words_per_15, 1))
        est_minutes = int(blocks * 15)
        metrics.append({
            "chapter_file": sc["chapter_file"],
            "scene_index": sc["scene_index"],
            "title": sc["title"],
            "word_count": word_count,
            "keyword_hits": hits,
            "total_keyword_hits": total_hits,
            "risk_score": risk,
            "estimated_time_minutes": est_minutes
        })

    weekly_minutes = weekly_hours * 60.0

    def sort_key(m):
        return (-m["risk_score"], -m["total_keyword_hits"], -m["word_count"], m["chapter_file"], m["scene_index"])

    sorted_metrics = sorted(metrics, key=sort_key)
    selected = []
    used_minutes = 0
    for m in sorted_metrics:
        if len(selected) >= max_scenes:
            break
        if used_minutes + m["estimated_time_minutes"] > weekly_minutes:
            continue
        selected.append(m)
        used_minutes += m["estimated_time_minutes"]

    total_scenes = len(metrics)
    total_words = sum(m["word_count"] for m in metrics)
    avg_risk = round(sum(m["risk_score"] for m in metrics) / total_scenes, 1) if total_scenes > 0 else 0.0
    total_selected_minutes = sum(m["estimated_time_minutes"] for m in selected)

    return {
        "keywords": keywords,
        "prefs": {
            "weekly_hours": weekly_hours,
            "max_scenes": max_scenes,
            "words_per_15min": words_per_15,
            "email_recipient_name": recipient,
            "due_date": due_date
        },
        "metrics": metrics,
        "selected": selected,
        "summary": {
            "total_scenes": total_scenes,
            "total_words": total_words,
            "avg_risk": avg_risk,
            "total_selected_minutes": total_selected_minutes
        }
    }


def _get_top_contributors(m, keywords):
    contribs = []
    hits = m.get("keyword_hits", {})
    for k, w in keywords.items():
        c = hits.get(k, 0)
        if c > 0:
            contribs.append((k, c, c * w))
    contribs.sort(key=lambda x: (-x[2], -x[1], x[0]))
    return contribs


def _verify_scene_metrics(workspace: Path, expected):
    out_path = workspace / "out" / "scene_metrics.csv"
    rows, headers = _csv_read_dicts(out_path)
    if rows is None or headers is None:
        return 0.0, 0.0

    required_cols = ["chapter_file", "scene_index", "title", "word_count", "total_keyword_hits", "risk_score", "estimated_time_minutes"]
    if headers != required_cols:
        return 0.0, 0.0

    exp_map = {}
    for m in expected["metrics"]:
        key = (m["chapter_file"], m["scene_index"])
        exp_map[key] = m

    matched = 0
    seen_keys = set()
    for r in rows:
        cf = r.get("chapter_file", "")
        si = _parse_int(r.get("scene_index", None))
        if cf == "" or si is None:
            continue
        key = (cf, si)
        seen_keys.add(key)
        em = exp_map.get(key)
        if not em:
            continue
        title_ok = (r.get("title", "").strip() == em["title"])
        wc_ok = (_parse_int(r.get("word_count", None)) == em["word_count"])
        tkh_ok = (_parse_int(r.get("total_keyword_hits", None)) == em["total_keyword_hits"])
        rs_val = _parse_float(r.get("risk_score", None))
        rs_ok = (rs_val is not None and abs(rs_val - em["risk_score"]) < 1e-6)
        etm_ok = (_parse_int(r.get("estimated_time_minutes", None)) == em["estimated_time_minutes"])
        if title_ok and wc_ok and tkh_ok and rs_ok and etm_ok:
            matched += 1

    if len(exp_map) == 0:
        fraction = 0.0
    else:
        fraction = matched / len(exp_map)

    return 1.0, fraction


def _verify_priority_scenes(workspace: Path, expected):
    out_path = workspace / "out" / "priority_scenes.csv"
    rows, headers = _csv_read_dicts(out_path)
    if rows is None or headers is None:
        return 0.0, 0.0, 0.0

    required_cols = ["chapter_file", "scene_index", "title", "word_count", "total_keyword_hits", "risk_score", "estimated_time_minutes", "selected_reason"]
    if headers != required_cols:
        return 0.0, 0.0, 0.0

    exp_selected = expected["selected"]
    exp_map = {(m["chapter_file"], m["scene_index"]): m for m in exp_selected}
    seen_keys = set()
    matched_set = 0
    reasons_ok = 0
    for r in rows:
        cf = r.get("chapter_file", "")
        si = _parse_int(r.get("scene_index", None))
        if cf == "" or si is None:
            continue
        key = (cf, si)
        seen_keys.add(key)
        if key not in exp_map:
            continue
        em = exp_map[key]
        title_ok = (r.get("title", "").strip() == em["title"])
        wc_ok = (_parse_int(r.get("word_count", None)) == em["word_count"])
        tkh_ok = (_parse_int(r.get("total_keyword_hits", None)) == em["total_keyword_hits"])
        rs_val = _parse_float(r.get("risk_score", None))
        rs_ok = (rs_val is not None and abs(rs_val - em["risk_score"]) < 1e-6)
        etm_ok = (_parse_int(r.get("estimated_time_minutes", None)) == em["estimated_time_minutes"])
        if title_ok and wc_ok and tkh_ok and rs_ok and etm_ok:
            matched_set += 1
        sr = (r.get("selected_reason", "") or "").lower()
        contribs = _get_top_contributors(em, expected["keywords"])
        expected_pairs = []
        for k, c, _sc in contribs[:2]:
            expected_pairs.append((k.lower(), c))
        if not expected_pairs:
            reasons_ok += 1
        else:
            found_all = True
            for k, c in expected_pairs:
                pattern = re.compile(re.escape(k) + r"\s*x\s*{}".format(c))
                if not pattern.search(sr):
                    found_all = False
                    break
            if found_all:
                reasons_ok += 1

    sel_fraction = (matched_set / max(1, len(exp_selected)))
    reasons_fraction = (reasons_ok / max(1, len(rows)))
    return 1.0, sel_fraction, reasons_fraction


def _verify_summary(workspace: Path, expected):
    out_path = workspace / "out" / "summary.md"
    text = _read_text_safe(out_path)
    if not text:
        return 0.0, 0.0

    stats_needed = [
        str(expected["summary"]["total_scenes"]),
        str(expected["summary"]["total_words"]),
        f"{expected['summary']['avg_risk']:.1f}",
        str(expected["summary"]["total_selected_minutes"])
    ]
    stats_found = 0
    for token in stats_needed:
        if token in text:
            stats_found += 1
    stats_fraction = stats_found / len(stats_needed)

    lines = [ln.strip().lower() for ln in text.splitlines() if ln.strip()]
    rationale_hits = 0
    for m in expected["selected"]:
        title = m["title"].lower()
        contribs = _get_top_contributors(m, expected["keywords"])
        top_keywords = [k.lower() for k, _, _ in contribs[:2]] if contribs else []
        hit = False
        for ln in lines:
            if title in ln:
                kw_ok = any(kw in ln for kw in top_keywords) if top_keywords else True
                digit_ok = any(ch.isdigit() for ch in ln)
                if kw_ok and digit_ok:
                    hit = True
                    break
        if hit:
            rationale_hits += 1
    rationale_fraction = rationale_hits / max(1, len(expected["selected"]))
    return stats_fraction, rationale_fraction


def _verify_email(workspace: Path, expected):
    out_path = workspace / "out" / "email_draft.txt"
    text = _read_text_safe(out_path)
    if not text:
        return 0.0, 0.0, 0.0

    basics_checks = 0
    recipient = expected["prefs"]["email_recipient_name"]
    if recipient and (recipient.lower() in text.lower()):
        basics_checks += 1
    due_date = expected["prefs"]["due_date"]
    if due_date and (due_date in text):
        basics_checks += 1
    paragraphs = [p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    if 2 <= len(paragraphs) <= 4:
        basics_checks += 1
    basics_fraction = basics_checks / 3.0

    scenes_hits = 0
    for m in expected["selected"]:
        title = m["title"]
        cf = m["chapter_file"]
        chap_num_match = re.search(r"ch(\d+)\.md", cf, re.IGNORECASE)
        chap_num = chap_num_match.group(1) if chap_num_match else None
        found = False
        for para in paragraphs:
            ln = para.strip()
            title_ok = (title.lower() in ln.lower())
            chapter_ok = False
            if cf in ln:
                chapter_ok = True
            if chap_num and re.search(r"\bchapter\s+{}\b".format(re.escape(chap_num)), ln, re.IGNORECASE):
                chapter_ok = True
            if chap_num and re.search(r"\bch\s*{}(\.md)?\b".format(re.escape(chap_num)), ln, re.IGNORECASE):
                chapter_ok = True
            if title_ok and chapter_ok:
                found = True
                break
        if found:
            scenes_hits += 1
    scenes_fraction = scenes_hits / max(1, len(expected["selected"]))

    total_minutes = expected["summary"]["total_selected_minutes"]
    time_included_score = 1.0 if str(total_minutes) in text else 0.0

    return basics_fraction, scenes_fraction, time_included_score


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "scene_metrics_file_and_columns": 0.0,
        "scene_metrics_values_correct": 0.0,
        "priority_file_and_columns": 0.0,
        "priority_selection_correct": 0.0,
        "priority_selected_reasons": 0.0,
        "summary_required_stats": 0.0,
        "summary_rationale_quality": 0.0,
        "email_basics": 0.0,
        "email_mentions_scenes": 0.0,
        "email_includes_estimated_time": 0.0,
    }

    expected = _compute_expected(workspace)

    sm_file_cols, sm_values = _verify_scene_metrics(workspace, expected)
    scores["scene_metrics_file_and_columns"] = float(sm_file_cols)
    scores["scene_metrics_values_correct"] = float(sm_values)

    pr_file_cols, pr_sel, pr_reason = _verify_priority_scenes(workspace, expected)
    scores["priority_file_and_columns"] = float(pr_file_cols)
    scores["priority_selection_correct"] = float(pr_sel)
    scores["priority_selected_reasons"] = float(pr_reason)

    sum_stats, sum_rationale = _verify_summary(workspace, expected)
    scores["summary_required_stats"] = float(sum_stats)
    scores["summary_rationale_quality"] = float(sum_rationale)

    e_basic, e_scenes, e_time = _verify_email(workspace, expected)
    scores["email_basics"] = float(e_basic)
    scores["email_mentions_scenes"] = float(e_scenes)
    scores["email_includes_estimated_time"] = float(e_time)

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()