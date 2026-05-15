import json
import csv
import re
import sys
from pathlib import Path


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_json(path: Path):
    try:
        return json.loads(_read_text(path))
    except Exception:
        return None


def _parse_config_yaml(path: Path):
    text = _read_text(path)
    if not text:
        return None
    report_id = None
    year_range = None
    notes = None

    m = re.search(r'^\s*report_id\s*:\s*(.+?)\s*$', text, re.M)
    if m:
        val = m.group(1).strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        report_id = val

    m = re.search(r'^\s*year_range\s*:\s*(.+?)\s*$', text, re.M)
    if m:
        val = m.group(1).strip()
        if val.lower() == "null":
            year_range = None
        else:
            m2 = re.search(r'\[\s*(\d{4})\s*,\s*(\d{4})\s*\]', val)
            if m2:
                year_range = [int(m2.group(1)), int(m2.group(2))]

    m = re.search(r'^\s*notes\s*:\s*(.+?)\s*$', text, re.M)
    if m:
        val = m.group(1).strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        notes = val

    return {"report_id": report_id, "year_range": year_range, "notes": notes}


def _parse_html_profile(path: Path):
    html = _read_text(path)
    if not html:
        return None
    full_name = None
    birth_date = None
    playing_style = None
    ch_rank = None
    ch_year = None

    m = re.search(r'Full name:\s*(.*?)<', html, re.I | re.S)
    if m:
        full_name = re.sub(r'\s+', ' ', m.group(1).strip())

    m = re.search(r'Born:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})', html, re.I)
    if m:
        birth_date = m.group(1)

    m = re.search(r'Playing style:\s*(.*?)<', html, re.I | re.S)
    if m:
        playing_style = re.sub(r'\s+', ' ', m.group(1).strip())

    m = re.search(r'Career-high singles ranking:\s*No\.\s*([0-9]+)\s*\(\s*([0-9]{4})\s*\)', html, re.I)
    if m:
        try:
            ch_rank = int(m.group(1))
            ch_year = int(m.group(2))
        except Exception:
            ch_rank, ch_year = None, None

    return {
        "full_name": full_name,
        "birth_date": birth_date,
        "playing_style": playing_style,
        "career_high_rank": {"rank": ch_rank, "year": ch_year},
    }


def _read_matches_csv(path: Path):
    rows = []
    try:
        with path.open("r", encoding="utf-8") as f:
            rdr = csv.DictReader(f)
            for r in rdr:
                try:
                    year = int(str(r.get("year", "")).strip())
                    result = str(r.get("result", "")).strip()
                    is_final_str = str(r.get("is_final", "")).strip()
                    is_final = True if is_final_str.lower() == "true" else False
                    opponent = str(r.get("opponent", "")).strip()
                    rows.append({
                        "year": year,
                        "result": result,
                        "is_final": is_final,
                        "opponent": opponent
                    })
                except Exception:
                    return None
        return rows
    except Exception:
        return None


def _compute_stats(rows, year_range):
    if rows is None or year_range is None or len(year_range) != 2:
        return None
    start, end = year_range
    filtered = [r for r in rows if isinstance(r.get("year"), int) and start <= r["year"] <= end]
    matches = len(filtered)
    wins = sum(1 for r in filtered if r.get("result") == "Win")
    losses = sum(1 for r in filtered if r.get("result") == "Loss")
    finals = sum(1 for r in filtered if r.get("is_final") is True)
    titles = sum(1 for r in filtered if r.get("is_final") is True and r.get("result") == "Win")
    opp_stats = {}
    for r in filtered:
        opp = r.get("opponent")
        if not opp:
            continue
        if opp not in opp_stats:
            opp_stats[opp] = {"opponent": opp, "matches": 0, "wins": 0, "losses": 0}
        opp_stats[opp]["matches"] += 1
        if r.get("result") == "Win":
            opp_stats[opp]["wins"] += 1
        elif r.get("result") == "Loss":
            opp_stats[opp]["losses"] += 1
    opp_list = []
    for v in opp_stats.values():
        m = v["matches"]
        wr = round(v["wins"] / m, 2) if m > 0 else 0.0
        opp_list.append({
            "opponent": v["opponent"],
            "matches": v["matches"],
            "wins": v["wins"],
            "losses": v["losses"],
            "win_rate": round(wr, 2)
        })
    opp_list.sort(key=lambda x: (-x["matches"], x["opponent"]))
    opp_list = opp_list[:5]
    return {
        "totals": {
            "matches": matches,
            "wins": wins,
            "losses": losses,
            "finals": finals,
            "titles": titles
        },
        "top_opponents": opp_list
    }


def _safe_load_summary(path: Path):
    data = _load_json(path)
    if not isinstance(data, dict):
        return None
    return data


def _read_csv_with_header(path: Path):
    try:
        text = _read_text(path)
        if not text:
            return None, None
        lines = [ln for ln in text.splitlines() if ln is not None]
        if not lines:
            return None, None
        header = lines[0].strip()
        rows = []
        for ln in lines[1:]:
            if not ln.strip():
                continue
            rows.append([c.strip() for c in ln.split(",")])
        return header, rows
    except Exception:
        return None, None


def _extract_marked_section(full_text: str, start_marker: str, end_marker: str):
    start_idx = full_text.find(start_marker)
    end_idx = full_text.find(end_marker)
    if start_idx == -1 or end_idx == -1 or end_idx < start_idx:
        return None
    pre = full_text[:start_idx]
    inner = full_text[start_idx + len(start_marker):end_idx]
    post = full_text[end_idx + len(end_marker):]
    return pre, inner, post


def _contains_line_with_profile(inner: str, full_name: str, birth_date: str, playing_style: str) -> bool:
    for line in inner.splitlines():
        l = line.strip()
        if not l:
            continue
        if (full_name in l) and (birth_date in l) and (playing_style in l):
            return True
    return False


def _find_totals_line(inner: str):
    for line in inner.splitlines():
        l = line.strip()
        if not l or l.startswith("-") or l.startswith("*"):
            continue
        if re.search(r'\bwins?\b', l, re.I) and re.search(r'\blosses?\b', l, re.I) and re.search(r'\bfinals?\b', l, re.I) and re.search(r'\btitles?\b', l, re.I):
            return l
    return None


def _extract_integers_from_line(line: str):
    return [int(x) for x in re.findall(r'\b(\d+)\b', line)]


def _parse_bullet_wl(line: str):
    m = re.search(r'(\d+)\s*[–-]\s*(\d+)', line)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_report_id": 0.0,
        "config_year_range": 0.0,
        "config_notes_unchanged": 0.0,
        "summary_present": 0.0,
        "summary_basic_from_config": 0.0,
        "summary_profile_from_html": 0.0,
        "summary_career_high_and_agree": 0.0,
        "summary_totals_correct_from_matches": 0.0,
        "summary_top_opponents_correct": 0.0,
        "summary_source_files_list": 0.0,
        "csv_rivalries_matches_summary": 0.0,
        "newsletter_outside_unchanged": 0.0,
        "newsletter_mentions_report_and_profile": 0.0,
        "newsletter_totals_paragraph_consistent": 0.0,
        "newsletter_career_high_agreement": 0.0,
        "newsletter_top_opponents_bullets": 0.0,
    }

    cfg_path = workspace / "input" / "config" / "report_config.yaml"
    html_path = workspace / "input" / "articles" / "stan_smith_profile.html"
    rankings_path = workspace / "input" / "data" / "rankings.json"
    matches_path = workspace / "input" / "data" / "matches.csv"
    summary_path = workspace / "output" / "stan_smith_summary.json"
    rivals_csv_path = workspace / "output" / "stan_smith_rivalries.csv"
    newsletter_path = workspace / "newsletter" / "issue_2024-06.md"

    cfg = _parse_config_yaml(cfg_path)
    if cfg is not None:
        has_correct_report = cfg.get("report_id") == "ss-spotlight-1971-73"
        has_correct_range = cfg.get("year_range") == [1971, 1973]
        if has_correct_report:
            scores["config_report_id"] = 1.0
        if has_correct_range:
            scores["config_year_range"] = 1.0
        # Only award notes unchanged if the required config updates are present
        if has_correct_report and has_correct_range:
            if cfg.get("notes") == "Set year_range to [1971, 1973] and update report_id before running.":
                scores["config_notes_unchanged"] = 1.0

    profile = _parse_html_profile(html_path)
    rankings = _load_json(rankings_path)
    html_ch_rank = None
    html_ch_year = None
    if profile is not None and profile.get("career_high_rank"):
        html_ch_rank = profile["career_high_rank"].get("rank")
        html_ch_year = profile["career_high_rank"].get("year")

    json_ch_rank = None
    json_ch_year = None
    if isinstance(rankings, dict):
        ch = rankings.get("career_high")
        if isinstance(ch, dict):
            json_ch_rank = ch.get("rank")
            json_ch_year = ch.get("year")

    rows = _read_matches_csv(matches_path)
    stats = None
    if cfg is not None and rows is not None and isinstance(cfg.get("year_range"), list) and len(cfg.get("year_range")) == 2:
        stats = _compute_stats(rows, cfg["year_range"])

    summary = _safe_load_summary(summary_path)
    if summary is not None:
        scores["summary_present"] = 1.0
        try:
            if cfg is not None and summary.get("report_id") == cfg.get("report_id") and summary.get("year_range") == cfg.get("year_range"):
                scores["summary_basic_from_config"] = 1.0
        except Exception:
            pass

        try:
            prof = summary.get("profile")
            if profile is not None and isinstance(prof, dict):
                if (prof.get("full_name") == profile.get("full_name") and
                    prof.get("birth_date") == profile.get("birth_date") and
                    prof.get("playing_style") == profile.get("playing_style")):
                    scores["summary_profile_from_html"] = 1.0
        except Exception:
            pass

        try:
            ch = summary.get("career_high_rank")
            if isinstance(ch, dict) and html_ch_rank is not None and html_ch_year is not None and json_ch_rank is not None and json_ch_year is not None:
                rank_ok = (ch.get("rank") == html_ch_rank == json_ch_rank)
                year_ok = (ch.get("year") == html_ch_year == json_ch_year)
                agree_expected = (html_ch_rank == json_ch_rank and html_ch_year == json_ch_year)
                agree_ok = (ch.get("sources_agree") == agree_expected)
                if rank_ok and year_ok and agree_ok:
                    scores["summary_career_high_and_agree"] = 1.0
        except Exception:
            pass

        try:
            if stats is not None and isinstance(summary.get("totals"), dict):
                t = summary["totals"]
                if (t.get("matches") == stats["totals"]["matches"] and
                    t.get("wins") == stats["totals"]["wins"] and
                    t.get("losses") == stats["totals"]["losses"] and
                    t.get("finals") == stats["totals"]["finals"] and
                    t.get("titles") == stats["totals"]["titles"]):
                    scores["summary_totals_correct_from_matches"] = 1.0
        except Exception:
            pass

        try:
            if stats is not None and isinstance(summary.get("top_opponents"), list):
                top_summ = summary["top_opponents"]
                top_exp = stats["top_opponents"]
                ok = True
                if len(top_summ) != len(top_exp):
                    ok = False
                else:
                    for a, b in zip(top_summ, top_exp):
                        if not (isinstance(a, dict) and isinstance(b, dict)):
                            ok = False
                            break
                        if not (a.get("opponent") == b.get("opponent") and
                                a.get("matches") == b.get("matches") and
                                a.get("wins") == b.get("wins") and
                                a.get("losses") == b.get("losses")):
                            ok = False
                            break
                        try:
                            if round(float(a.get("win_rate")), 2) != round(float(b.get("win_rate")), 2):
                                ok = False
                                break
                        except Exception:
                            ok = False
                            break
                if ok:
                    scores["summary_top_opponents_correct"] = 1.0
        except Exception:
            pass

        try:
            sf = summary.get("source_files")
            expected_sf = [
                "input/articles/stan_smith_profile.html",
                "input/data/matches.csv",
                "input/data/rankings.json",
                "input/config/report_config.yaml",
            ]
            if sf == expected_sf:
                scores["summary_source_files_list"] = 1.0
        except Exception:
            pass

    header, rows_csv = _read_csv_with_header(rivals_csv_path)
    if header == "opponent,matches,wins,losses,win_rate" and isinstance(rows_csv, list):
        if summary is not None and isinstance(summary.get("top_opponents"), list):
            top = summary["top_opponents"]
            ok = True
            if len(rows_csv) != len(top):
                ok = False
            else:
                for i, row in enumerate(rows_csv):
                    if len(row) != 5:
                        ok = False
                        break
                    opp, m, w, l, wr = row
                    try:
                        m_i = int(m)
                        w_i = int(w)
                        l_i = int(l)
                        wr_f = float(wr)
                    except Exception:
                        ok = False
                        break
                    t = top[i]
                    if not (opp == t.get("opponent") and m_i == t.get("matches") and w_i == t.get("wins") and l_i == t.get("losses") and round(wr_f, 2) == round(float(t.get("win_rate")), 2)):
                        ok = False
                        break
            if ok:
                scores["csv_rivalries_matches_summary"] = 1.0

    newsletter_text = _read_text(newsletter_path)
    if newsletter_text:
        start_marker = "<!-- SPOTLIGHT:START -->"
        end_marker = "<!-- SPOTLIGHT:END -->"
        extracted = _extract_marked_section(newsletter_text, start_marker, end_marker)
        if extracted:
            pre, inner, post = extracted
            expected_pre = "# Stan Tennis Fan Club Newsletter — June 2024\n\nWelcome to the June issue! This month we spotlight one of our all-time favorites.\n\n## Stan Smith Spotlight\n"
            expected_post = "\n\n## Upcoming Events\n- Local meetup on the 15th.\n- Friendly match and trivia night on the 22nd.\n\nThanks for reading!\n"
            # Only award 'outside unchanged' if summary is present (indicates the task was worked) and the outside matches exactly
            if summary is not None and pre == expected_pre and post == expected_post:
                scores["newsletter_outside_unchanged"] = 1.0

            rep_ok = False
            prof_ok = False
            if cfg is not None and isinstance(cfg.get("report_id"), str):
                if cfg["report_id"] in inner:
                    rep_ok = True
            if profile is not None:
                if _contains_line_with_profile(inner, profile.get("full_name", ""), profile.get("birth_date", ""), profile.get("playing_style", "")):
                    prof_ok = True
            if rep_ok and prof_ok:
                scores["newsletter_mentions_report_and_profile"] = 1.0

            totals_line = _find_totals_line(inner)
            totals_consistent = False
            if totals_line and summary is not None and isinstance(summary.get("totals"), dict):
                nums = _extract_integers_from_line(totals_line)
                t = summary["totals"]
                needed_values = [t.get("wins"), t.get("losses"), t.get("finals"), t.get("titles")]
                if all(isinstance(x, int) for x in needed_values):
                    needed = set(needed_values)
                    present = set()
                    for n in nums:
                        if n in needed:
                            present.add(n)
                    if present == needed:
                        totals_consistent = True
            if totals_consistent:
                scores["newsletter_totals_paragraph_consistent"] = 1.0

            ch_ok = False
            if summary is not None and isinstance(summary.get("career_high_rank"), dict):
                ch = summary["career_high_rank"]
                rank = ch.get("rank")
                year = ch.get("year")
                agree = ch.get("sources_agree")
                for line in inner.splitlines():
                    l = line.strip()
                    if not l:
                        continue
                    if re.search(r'career[- ]?high', l, re.I):
                        has_rank = (str(rank) in l) if rank is not None else False
                        has_year = (str(year) in l) if year is not None else False
                        if agree is True:
                            if has_rank and has_year and re.search(r'\bagree\b', l, re.I) and not re.search(r'\bdisagree\b', l, re.I):
                                ch_ok = True
                                break
                        elif agree is False:
                            if has_rank and has_year and re.search(r'\bdisagree\b', l, re.I):
                                ch_ok = True
                                break
            if ch_ok:
                scores["newsletter_career_high_agreement"] = 1.0

            bullets_ok = False
            if summary is not None and isinstance(summary.get("top_opponents"), list):
                top = summary["top_opponents"]
                bullet_lines = [ln.strip() for ln in inner.splitlines() if ln.strip().startswith("-") or ln.strip().startswith("*")]
                if len(bullet_lines) >= len(top):
                    order_ok = True
                    idx = 0
                    for opp in top:
                        name = opp.get("opponent", "")
                        wins_val = opp.get("wins")
                        losses_val = opp.get("losses")
                        found = False
                        while idx < len(bullet_lines):
                            line = bullet_lines[idx]
                            idx += 1
                            if name in line:
                                wl = _parse_bullet_wl(line)
                                if wl is None:
                                    found = False
                                else:
                                    found = (wl[0] == wins_val and wl[1] == losses_val)
                                break
                        if not found:
                            order_ok = False
                            break
                    if order_ok:
                        bullets_ok = True
            if bullets_ok:
                scores["newsletter_top_opponents_bullets"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()