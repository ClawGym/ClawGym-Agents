import json
import csv
import sys
import re
from pathlib import Path
from statistics import mean


def _safe_load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _safe_load_csv_rows(path: Path):
    try:
        rows = []
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                try:
                    rows.append({
                        "film_title": r["film_title"].strip(),
                        "creator_type": r["creator_type"].strip(),
                        "creator_handle": r["creator_handle"].strip(),
                        "sentiment": float(r["sentiment"]),
                        "credibility_score": float(r["credibility_score"]),
                        "review_date": r["review_date"].strip(),
                        "notes": r["notes"].strip(),
                    })
                except Exception:
                    return None
        return rows
    except Exception:
        return None


def _round2(x: float) -> float:
    return round(x, 2)


def _round3(x: float) -> float:
    return round(x, 3)


def _float_eq(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol


def _is_heading(line: str, title: str) -> bool:
    s = line.strip()
    # Allow optional leading '#' and spaces before title
    if s == title:
        return True
    if s.startswith("#"):
        s2 = s.lstrip("#").strip()
        return s2 == title
    return False


def _extract_sections(md_text: str, titles):
    lines = md_text.splitlines()
    sec_map = {t: [] for t in titles}
    current = None
    for i, line in enumerate(lines):
        for t in titles:
            if _is_heading(line, t):
                current = t
                # skip the heading line itself
                break
        else:
            if current is not None:
                sec_map[current].append(line)
    # Trim trailing/leading empty lines from sections
    for t in titles:
        # normalize to content without the title heading
        # But ensure we stop at next heading among titles
        cleaned = []
        for ln in sec_map[t]:
            # Stop if a line contains another title heading
            if any(_is_heading(ln, other) for other in titles):
                break
            cleaned.append(ln)
        # Strip leading/trailing blank lines
        while cleaned and cleaned[0].strip() == "":
            cleaned = cleaned[1:]
        while cleaned and cleaned[-1].strip() == "":
            cleaned = cleaned[:-1]
        sec_map[t] = cleaned
    return sec_map


def _extract_bullets(section_lines):
    items = []
    for ln in section_lines:
        s = ln.strip()
        if not s:
            continue
        # Remove common bullet markers
        s = re.sub(r"^\s*[-*\u2022]\s*", "", s)
        items.append(s.strip())
    return items


def _compute_expected_summary(reviews):
    by_type = {}
    for r in reviews:
        t = r["creator_type"]
        by_type.setdefault(t, {"count": 0, "sentiments": [], "credibilities": []})
        by_type[t]["count"] += 1
        by_type[t]["sentiments"].append(r["sentiment"])
        by_type[t]["credibilities"].append(r["credibility_score"])
    summary = {}
    for t, agg in by_type.items():
        avg_s = _round3(mean(agg["sentiments"])) if agg["sentiments"] else None
        avg_c = _round3(mean(agg["credibilities"])) if agg["credibilities"] else None
        summary[t] = {
            "count": agg["count"],
            "avg_sentiment": avg_s,
            "avg_credibility": avg_c,
        }
    return {"by_creator_type": summary}


def _compute_expected_filtered(reviews, allowed_types, min_cred):
    result = []
    for r in reviews:
        if r["creator_type"] in allowed_types and r["credibility_score"] >= min_cred:
            obj = {
                "film_title": r["film_title"],
                "creator_type": r["creator_type"],
                "creator_handle": r["creator_handle"],
                "sentiment": float(r["sentiment"]),
                "credibility_score": float(r["credibility_score"]),
                "review_date": r["review_date"],
                "notes": r["notes"],
            }
            result.append(obj)
    return result


def _compute_expected_comparisons(reviews, allowed_types):
    by_film_type = {}
    for r in reviews:
        if r["creator_type"] not in allowed_types:
            continue
        f = r["film_title"]
        t = r["creator_type"]
        by_film_type.setdefault(f, {}).setdefault(t, {"sentiments": [], "credibilities": []})
        by_film_type[f][t]["sentiments"].append(r["sentiment"])
        by_film_type[f][t]["credibilities"].append(r["credibility_score"])
    results = {}
    for f, ft in by_film_type.items():
        crit_sents = ft.get("Critic", {}).get("sentiments", [])
        yt_sents = ft.get("YouTuber", {}).get("sentiments", [])
        crit_creds = ft.get("Critic", {}).get("credibilities", [])
        yt_creds = ft.get("YouTuber", {}).get("credibilities", [])
        crit_avg_s = _round2(mean(crit_sents)) if crit_sents else None
        yt_avg_s = _round2(mean(yt_sents)) if yt_sents else None
        crit_avg_c = _round2(mean(crit_creds)) if crit_creds else None
        yt_avg_c = _round2(mean(yt_creds)) if yt_creds else None
        gap = None
        if yt_avg_s is not None and crit_avg_s is not None:
            gap = _round2(yt_avg_s - crit_avg_s)
        results[f] = {
            "avg_sentiment": {"Critic": crit_avg_s, "YouTuber": yt_avg_s},
            "avg_credibility": {"Critic": crit_avg_c, "YouTuber": yt_avg_c},
            "sentiment_gap": gap,
        }
    return results


def _normalize_item_for_set(item):
    return (
        item.get("film_title"),
        item.get("creator_type"),
        item.get("creator_handle"),
        float(item.get("sentiment")),
        float(item.get("credibility_score")),
        item.get("review_date"),
        item.get("notes"),
    )


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_min_credibility_set": 0.0,
        "config_agenda_topics_present": 0.0,
        "config_sentiment_gap_threshold_present": 0.0,
        "summary_json_preserved": 0.0,
        "filtered_reviews_exists_and_structure": 0.0,
        "filtered_reviews_filter_logic": 0.0,
        "comparisons_by_film_exists_and_structure": 0.0,
        "comparisons_by_film_values": 0.0,
        "meeting_notes_sections_present": 0.0,
        "meeting_notes_agenda_items": 0.0,
        "meeting_notes_key_comparisons_values_and_divergence_flags": 0.0,
        "meeting_notes_action_items": 0.0,
        "meeting_notes_appendix_lowest_youtuber_reviews": 0.0,
    }

    # Load config
    config_path = workspace / "config" / "settings.json"
    config = _safe_load_json(config_path)
    if isinstance(config, dict):
        # Check min_credibility
        min_cred = config.get("min_credibility")
        if isinstance(min_cred, (int, float)) and _float_eq(float(min_cred), 0.6):
            scores["config_min_credibility_set"] = 1.0
        # Check agenda_topics
        agenda_expected = [
            "Festival press roundtable prep",
            "Divergence between critics and YouTubers",
            "Credibility thresholds and disclosure",
        ]
        agenda = config.get("agenda_topics")
        if isinstance(agenda, list) and agenda == agenda_expected:
            scores["config_agenda_topics_present"] = 1.0
        # Check sentiment_gap_threshold
        sgt = config.get("sentiment_gap_threshold")
        if isinstance(sgt, (int, float)) and _float_eq(float(sgt), 0.5):
            scores["config_sentiment_gap_threshold_present"] = 1.0
    else:
        # Config missing or invalid: other checks depending on output_dir default to "output"
        config = {"output_dir": "output", "allowed_creator_types": ["Critic", "YouTuber"], "min_credibility": 0.6, "sentiment_gap_threshold": 0.5, "agenda_topics": []}

    # Baseline inputs
    input_csv_path = workspace / config.get("input_csv", "input/reviews.csv")
    base_reviews = _safe_load_csv_rows(input_csv_path)
    # If base reviews missing or invalid, many downstream checks will fail gracefully
    # Compute expected summaries and comparisons when possible
    expected_summary = None
    expected_filtered = None
    expected_comparisons = None
    if isinstance(base_reviews, list):
        expected_summary = _compute_expected_summary(base_reviews)
        allowed_types = config.get("allowed_creator_types", ["Critic", "YouTuber"])
        min_cred_eval = config.get("min_credibility", 0.6)
        try:
            min_cred_eval = float(min_cred_eval)
        except Exception:
            min_cred_eval = 0.6
        expected_filtered = _compute_expected_filtered(base_reviews, allowed_types, min_cred_eval)
        expected_comparisons = _compute_expected_comparisons(base_reviews, allowed_types)

    # Paths for outputs
    out_dir = config.get("output_dir", "output")
    out_path = workspace / out_dir

    # Check summary.json preserved
    summary_path = out_path / "summary.json"
    summary = _safe_load_json(summary_path)
    if isinstance(summary, dict) and isinstance(expected_summary, dict):
        try:
            byct = summary.get("by_creator_type", {})
            ok = True
            for ctype, vals in expected_summary["by_creator_type"].items():
                sv = byct.get(ctype)
                if not isinstance(sv, dict):
                    ok = False
                    break
                if sv.get("count") != vals["count"]:
                    ok = False
                    break
                # allow tolerance for floats
                if not _float_eq(float(sv.get("avg_sentiment")), float(vals["avg_sentiment"]), 1e-3):
                    ok = False
                    break
                if not _float_eq(float(sv.get("avg_credibility")), float(vals["avg_credibility"]), 1e-3):
                    ok = False
                    break
            if ok:
                scores["summary_json_preserved"] = 1.0
        except Exception:
            pass

    # Check filtered_reviews.json
    filtered_path = out_path / "filtered_reviews.json"
    filtered = _safe_load_json(filtered_path)
    required_fields = ["film_title", "creator_type", "creator_handle", "sentiment", "credibility_score", "review_date", "notes"]
    if isinstance(filtered, list) and filtered:
        # Structure: each item must have exactly the required fields
        struct_ok = True
        for itm in filtered:
            if not isinstance(itm, dict):
                struct_ok = False
                break
            keys = set(itm.keys())
            if keys != set(required_fields):
                struct_ok = False
                break
            # type checks
            try:
                float(itm["sentiment"])
                float(itm["credibility_score"])
            except Exception:
                struct_ok = False
                break
        if struct_ok:
            scores["filtered_reviews_exists_and_structure"] = 1.0

    # Check filtered logic content
    if isinstance(filtered, list) and isinstance(expected_filtered, list):
        try:
            # Compare as sets of tuples for order-insensitive equality
            exp_set = set(_normalize_item_for_set(i) for i in expected_filtered)
            got_set = set(_normalize_item_for_set(i) for i in filtered)
            if exp_set == got_set:
                scores["filtered_reviews_filter_logic"] = 1.0
        except Exception:
            pass

    # Check comparisons_by_film.json
    comparisons_path = out_path / "comparisons_by_film.json"
    comparisons = _safe_load_json(comparisons_path)
    if isinstance(comparisons, list) and comparisons:
        struct_ok = True
        for itm in comparisons:
            if not isinstance(itm, dict):
                struct_ok = False
                break
            if set(itm.keys()) != {"film_title", "avg_sentiment", "avg_credibility", "sentiment_gap"}:
                struct_ok = False
                break
            for kk in ["avg_sentiment", "avg_credibility"]:
                sub = itm.get(kk, {})
                if not isinstance(sub, dict) or set(sub.keys()) != {"Critic", "YouTuber"}:
                    struct_ok = False
                    break
            if not struct_ok:
                break
        if struct_ok:
            scores["comparisons_by_film_exists_and_structure"] = 1.0

    # Validate comparison values
    if isinstance(comparisons, list) and isinstance(expected_comparisons, dict):
        try:
            by_film = {i["film_title"]: i for i in comparisons if isinstance(i, dict) and "film_title" in i}
            ok = True
            for film, exp_vals in expected_comparisons.items():
                got = by_film.get(film)
                if not got:
                    ok = False
                    break
                # Check numbers with strict 2-dec rounding equality
                for who in ["Critic", "YouTuber"]:
                    gv = got["avg_sentiment"].get(who)
                    ev = exp_vals["avg_sentiment"].get(who)
                    if gv is None or ev is None or not _float_eq(float(gv), float(ev), 1e-9):
                        ok = False
                        break
                if not ok:
                    break
                for who in ["Critic", "YouTuber"]:
                    gv = got["avg_credibility"].get(who)
                    ev = exp_vals["avg_credibility"].get(who)
                    if gv is None or ev is None or not _float_eq(float(gv), float(ev), 1e-9):
                        ok = False
                        break
                if not ok:
                    break
                if got.get("sentiment_gap") is None or not _float_eq(float(got["sentiment_gap"]), float(exp_vals["sentiment_gap"]), 1e-9):
                    ok = False
                    break
            if ok:
                scores["comparisons_by_film_values"] = 1.0
        except Exception:
            pass

    # Meeting notes checks
    notes_path = out_path / "meeting_notes.md"
    notes_text = _safe_read_text(notes_path)
    if notes_text:
        titles = ["Agenda", "Key Comparisons", "Action Items", "Appendix"]
        sections = _extract_sections(notes_text, titles)
        # Sections present if all non-empty lists or at least keys found
        if all(t in sections for t in titles) and all(isinstance(sections[t], list) for t in titles):
            scores["meeting_notes_sections_present"] = 1.0

        # Agenda items
        agenda_lines = sections.get("Agenda", [])
        agenda_items = _extract_bullets(agenda_lines)
        expected_agenda = [
            "Festival press roundtable prep",
            "Divergence between critics and YouTubers",
            "Credibility thresholds and disclosure",
        ]
        if agenda_items == expected_agenda:
            scores["meeting_notes_agenda_items"] = 1.0

        # Key Comparisons: verify values and divergence markers
        kc_lines = sections.get("Key Comparisons", [])
        if isinstance(expected_comparisons, dict) and kc_lines:
            kc_ok = True
            # Build blocks by film titles
            films = list(expected_comparisons.keys())
            # Map film to block text (list of lines)
            film_blocks = {}
            i = 0
            n = len(kc_lines)
            # Identify indices of film lines
            indices = []
            for idx, ln in enumerate(kc_lines):
                for f in films:
                    if f in ln:
                        indices.append((idx, f))
                        break
            # Build blocks between indices
            for pos, (start_idx, film) in enumerate(indices):
                end_idx = indices[pos + 1][0] if pos + 1 < len(indices) else n
                block = kc_lines[start_idx:end_idx]
                film_blocks[film] = block
            # Validate each film block
            for film, exp in expected_comparisons.items():
                block = film_blocks.get(film, [])
                block_text = "\n".join(block)
                # Must contain numeric values (formatted to 2 decimals)
                nums = [
                    f"{exp['avg_sentiment']['Critic']:.2f}",
                    f"{exp['avg_sentiment']['YouTuber']:.2f}",
                    f"{exp['avg_credibility']['Critic']:.2f}",
                    f"{exp['avg_credibility']['YouTuber']:.2f}",
                ]
                for num in nums:
                    if num not in block_text:
                        kc_ok = False
                        break
                if not kc_ok:
                    break
                # Divergence tagging: abs gap >= threshold -> include "DIVERGENCE"
                sgt = float(config.get("sentiment_gap_threshold", 0.5))
                has_div = "DIVERGENCE" in block_text
                if abs(float(exp["sentiment_gap"])) >= sgt:
                    if not has_div:
                        kc_ok = False
                        break
                else:
                    # Should not have divergence note for this film
                    if has_div:
                        kc_ok = False
                        break
            if kc_ok:
                scores["meeting_notes_key_comparisons_values_and_divergence_flags"] = 1.0

        # Action Items
        ai_lines = sections.get("Action Items", [])
        ai_bullets = _extract_bullets(ai_lines)
        if isinstance(expected_comparisons, dict):
            required_bullets = []
            sgt = float(config.get("sentiment_gap_threshold", 0.5))
            for film, vals in expected_comparisons.items():
                gap = float(vals["sentiment_gap"])
                if gap >= sgt:
                    required_bullets.append(f"Prepare talking point on divergence for {film}.")
                # yt credibility < critic credibility
                if float(vals["avg_credibility"]["YouTuber"]) < float(vals["avg_credibility"]["Critic"]):
                    required_bullets.append(f"Request editorial note on vetting sources for {film} YouTube reviews.")
            if all(any(req == b for b in ai_bullets) for req in required_bullets):
                scores["meeting_notes_action_items"] = 1.0

        # Appendix: top 3 lowest-credibility YouTuber reviews
        app_lines = sections.get("Appendix", [])
        app_bullets = _extract_bullets(app_lines)
        if isinstance(base_reviews, list):
            yt_reviews = [r for r in base_reviews if r["creator_type"] == "YouTuber"]
            yt_sorted = sorted(yt_reviews, key=lambda r: (r["credibility_score"], r["review_date"], r["creator_handle"]))
            top3 = yt_sorted[:3]
            reqs_ok = True
            for r in top3:
                ch = r["creator_handle"]
                ft = r["film_title"]
                cs = f"{_round2(r['credibility_score']):.2f}"
                nt = r["notes"]
                # Check any bullet contains all required pieces
                found = False
                for b in app_bullets:
                    if (ch in b) and (ft in b) and (cs in b) and (nt in b):
                        found = True
                        break
                if not found:
                    reqs_ok = False
                    break
            if reqs_ok and len(app_bullets) >= 3:
                scores["meeting_notes_appendix_lowest_youtuber_reviews"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()