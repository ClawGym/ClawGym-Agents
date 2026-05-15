import json
import csv
import re
import sys
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        txt = _safe_read_text(path)
        if txt is None:
            return None
        return json.loads(txt)
    except Exception:
        return None


def _safe_load_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [row for row in reader]
    except Exception:
        return None


def _safe_load_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        lines = []
        with path.open("r", encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                lines.append(json.loads(ln))
        return lines
    except Exception:
        return None


def _parse_policy_html(path: Path) -> Optional[List[Dict[str, Any]]]:
    txt = _safe_read_text(path)
    if txt is None:
        return None
    try:
        items = []
        li_pattern = re.compile(
            r'<li\s+[^>]*data-year="(?P<year>\d{4})"[^>]*>\s*(?P<body>.*?)</li>',
            re.DOTALL | re.IGNORECASE,
        )
        policy_pattern = re.compile(
            r'<span\s+class="policy"\s*>\s*(?P<policy>.*?)\s*</span>',
            re.DOTALL | re.IGNORECASE,
        )
        desc_pattern = re.compile(
            r'<span\s+class="desc"\s*>\s*(?P<desc>.*?)\s*</span>',
            re.DOTALL | re.IGNORECASE,
        )
        for m in li_pattern.finditer(txt):
            year_str = m.group("year")
            body = m.group("body")
            pm = policy_pattern.search(body)
            dm = desc_pattern.search(body)
            if pm and dm:
                policy_text = _strip_html(pm.group("policy"))
                desc_text = _strip_html(dm.group("desc"))
                items.append(
                    {
                        "year": int(year_str),
                        "policy": policy_text,
                        "desc": desc_text,
                    }
                )
        return items
    except Exception:
        return None


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s).strip()


def _slugify(text: str) -> str:
    t = text.lower()
    t = re.sub(r"\s+", "-", t)
    t = re.sub(r"[^a-z0-9\-]", "", t)
    t = re.sub(r"-{2,}", "-", t).strip("-")
    return t


def _compute_top_sectors_2020(emissions_rows: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
    try:
        year_rows = [r for r in emissions_rows if r.get("year") == "2020"]
        if not year_rows:
            return None
        sectors = []
        total = 0.0
        for r in year_rows:
            sector = r.get("sector", "")
            val_str = r.get("emissions_mtco2e", "")
            try:
                val = float(val_str)
            except Exception:
                return None
            sectors.append((sector, val))
            total += val
        sectors_sorted = sorted(sectors, key=lambda x: x[1], reverse=True)
        top3 = sectors_sorted[:3]
        result = []
        for sector, val in top3:
            share = round(val / total * 100.0, 1)
            result.append(
                {
                    "id": f"E-2020-{sector}",
                    "sector": sector,
                    "emissions_mtco2e": val,
                    "share_of_2020_total_percent": share,
                    "source_file": "input/emissions.csv",
                }
            )
        return {"top3": result, "total": total, "top3_raw": top3}
    except Exception:
        return None


def _float_equal(a: Any, b: Any, tol: float = 1e-9) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def _parse_storyboard_csv(path: Path) -> Optional[Tuple[List[Dict[str, str]], List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader]
            header = reader.fieldnames or []
            return rows, header
    except Exception:
        return None


def _word_count(text: str) -> int:
    return len(re.findall(r"\S+", text or ""))


def _extract_scene_headers_from_md(md_text: str) -> List[str]:
    headers = []
    for line in md_text.splitlines():
        m = re.match(r"^\s*S(\d+)\b", line.strip())
        if m:
            headers.append(f"S{m.group(1)}")
    return headers


def _extract_citations_index(md_text: str) -> Optional[List[str]]:
    lines = md_text.splitlines()
    idx = None
    for i, line in enumerate(lines):
        if line.strip().lower() == "citations index":
            idx = i
    if idx is None:
        return None
    entries = []
    for line in lines[idx + 1 :]:
        if not line.strip():
            continue
        m = re.match(r"^\s*([A-Za-z0-9\-]+)\s+—\s+.*$", line.strip())
        if m:
            entries.append(m.group(1))
        else:
            return None
    return entries


def _citations_index_source_check(md_text: str, factbook: Dict[str, Any]) -> bool:
    lines = md_text.splitlines()
    idx = None
    for i, line in enumerate(lines):
        if line.strip().lower() == "citations index":
            idx = i
    if idx is None:
        return False
    sources = {}
    for item in factbook.get("top_sectors_2020", []):
        sources[item.get("id")] = item.get("source_file")
    for item in factbook.get("quotes", []):
        sources[item.get("id")] = item.get("source_file")
    for item in factbook.get("policies", []):
        sources[item.get("id")] = item.get("source_file")
    ok = True
    for line in lines[idx + 1 :]:
        if not line.strip():
            continue
        m = re.match(r"^\s*([A-Za-z0-9\-]+)\s+—\s+(.*)$", line.strip())
        if not m:
            ok = False
            break
        fid = m.group(1)
        text = m.group(2)
        src = sources.get(fid)
        if not src or src not in text:
            ok = False
            break
    return ok


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_exists": 0.0,
        "script_runs": 0.0,
        "factbook_top_sectors_structure": 0.0,
        "factbook_top_sectors_values": 0.0,
        "factbook_quotes_structure": 0.0,
        "factbook_quotes_distinct_themes": 0.0,
        "factbook_policies_structure": 0.0,
        "factbook_policies_values": 0.0,
        "storyboard_structure": 0.0,
        "storyboard_citations_coverage": 0.0,
        "voiceover_structure": 0.0,
        "voiceover_citations_index_match": 0.0,
        "voiceover_citation_lines_source_presence": 0.0,
    }

    script_path = workspace / "scripts" / "build_factbook.py"
    outputs_dir = workspace / "outputs"
    factbook_path = outputs_dir / "factbook.json"
    storyboard_path = outputs_dir / "storyboard.csv"
    voiceover_path = outputs_dir / "voiceover.md"

    if script_path.exists() and script_path.is_file():
        scores["script_exists"] = 1.0

    ran_ok = False
    try:
        if script_path.exists():
            res = subprocess.run(
                [sys.executable, str(script_path)],
                cwd=str(workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60,
            )
            if res.returncode == 0 and factbook_path.exists() and storyboard_path.exists() and voiceover_path.exists():
                ran_ok = True
    except Exception:
        ran_ok = False
    if ran_ok:
        scores["script_runs"] = 1.0

    factbook = _safe_load_json(factbook_path)
    emissions_rows = _safe_load_csv(workspace / "input" / "emissions.csv")
    interviews_rows = _safe_load_jsonl(workspace / "input" / "interviews.jsonl")
    policy_items = _parse_policy_html(workspace / "input" / "policy_timeline.html")

    fact_ids = set()
    if factbook and isinstance(factbook, dict):
        for item in factbook.get("top_sectors_2020", []):
            fid = item.get("id")
            if isinstance(fid, str):
                fact_ids.add(fid)
        for item in factbook.get("quotes", []):
            fid = item.get("id")
            if isinstance(fid, str):
                fact_ids.add(fid)
        for item in factbook.get("policies", []):
            fid = item.get("id")
            if isinstance(fid, str):
                fact_ids.add(fid)

    topo_struct_ok = False
    if factbook and isinstance(factbook, dict):
        ts = factbook.get("top_sectors_2020")
        if isinstance(ts, list) and len(ts) == 3:
            all_ok = True
            for item in ts:
                if not isinstance(item, dict):
                    all_ok = False
                    break
                if set(item.keys()) != {
                    "id",
                    "sector",
                    "emissions_mtco2e",
                    "share_of_2020_total_percent",
                    "source_file",
                }:
                    all_ok = False
                    break
                sid = item.get("id")
                sector = item.get("sector")
                src = item.get("source_file")
                if not (isinstance(sid, str) and isinstance(sector, str) and isinstance(src, str)):
                    all_ok = False
                    break
                if src != "input/emissions.csv":
                    all_ok = False
                    break
                if sid != f"E-2020-{sector}":
                    all_ok = False
                    break
                emis = item.get("emissions_mtco2e")
                share = item.get("share_of_2020_total_percent")
                try:
                    float(emis)
                    float(share)
                except Exception:
                    all_ok = False
                    break
            topo_struct_ok = all_ok
    scores["factbook_top_sectors_structure"] = 1.0 if topo_struct_ok else 0.0

    topo_vals_ok = False
    if topo_struct_ok and emissions_rows is not None and factbook is not None:
        computed = _compute_top_sectors_2020(emissions_rows)
        if computed is not None:
            expected_list = computed["top3"]
            fb_list = factbook.get("top_sectors_2020", [])
            def _val(item: Dict[str, Any]) -> float:
                try:
                    return float(item.get("emissions_mtco2e"))
                except Exception:
                    return -1e9
            order_ok = True
            for i in range(1, len(fb_list)):
                if _val(fb_list[i]) > _val(fb_list[i - 1]):
                    order_ok = False
                    break
            sectors_match = set([i["sector"] for i in fb_list]) == set([i["sector"] for i in expected_list])
            values_match = True
            shares_match = True
            for exp in expected_list:
                match = next((x for x in fb_list if x.get("sector") == exp["sector"]), None)
                if not match:
                    values_match = False
                    shares_match = False
                    break
                if not _float_equal(match.get("emissions_mtco2e"), exp["emissions_mtco2e"]):
                    values_match = False
                if not _float_equal(match.get("share_of_2020_total_percent"), exp["share_of_2020_total_percent"]):
                    shares_match = False
            topo_vals_ok = sectors_match and order_ok and values_match and shares_match
    scores["factbook_top_sectors_values"] = 1.0 if topo_vals_ok else 0.0

    quotes_struct_ok = False
    if factbook and isinstance(factbook, dict):
        quotes = factbook.get("quotes")
        if isinstance(quotes, list) and len(quotes) == 3:
            all_ok = True
            for item in quotes:
                if not isinstance(item, dict):
                    all_ok = False
                    break
                if set(item.keys()) != {"id", "speaker", "role", "quote", "source_file"}:
                    all_ok = False
                    break
                if item.get("source_file") != "input/interviews.jsonl":
                    all_ok = False
                    break
                if not (
                    isinstance(item.get("id"), str)
                    and isinstance(item.get("speaker"), str)
                    and isinstance(item.get("role"), str)
                    and isinstance(item.get("quote"), str)
                ):
                    all_ok = False
                    break
            quotes_struct_ok = all_ok
    scores["factbook_quotes_structure"] = 1.0 if quotes_struct_ok else 0.0

    quotes_theme_ok = False
    if quotes_struct_ok and interviews_rows is not None and factbook is not None:
        quotes = factbook.get("quotes", [])
        id_map = {rec.get("id"): rec for rec in interviews_rows if isinstance(rec, dict)}
        themes = set()
        all_match = True
        for item in quotes:
            rid = item.get("id")
            src = id_map.get(rid)
            if not src:
                all_match = False
                break
            theme = src.get("theme")
            if theme in themes:
                all_match = False
                break
            themes.add(theme)
            if not (
                item.get("speaker") == src.get("speaker")
                and item.get("role") == src.get("role")
                and item.get("quote") == src.get("quote")
            ):
                all_match = False
                break
        quotes_theme_ok = all_match and len(quotes) == 3 and len(themes) == 3
    scores["factbook_quotes_distinct_themes"] = 1.0 if quotes_theme_ok else 0.0

    policies_struct_ok = False
    if factbook and isinstance(factbook, dict):
        policies = factbook.get("policies")
        if isinstance(policies, list) and len(policies) == 2:
            all_ok = True
            for item in policies:
                if not isinstance(item, dict):
                    all_ok = False
                    break
                if set(item.keys()) != {"id", "year", "policy", "desc", "source_file"}:
                    all_ok = False
                    break
                if item.get("source_file") != "input/policy_timeline.html":
                    all_ok = False
                    break
                if not isinstance(item.get("year"), int):
                    all_ok = False
                    break
                pid = item.get("id")
                pol = item.get("policy")
                if not (isinstance(pid, str) and isinstance(pol, str) and isinstance(item.get("desc"), str)):
                    all_ok = False
                    break
                slug = _slugify(pol)
                year = item.get("year")
                if pid != f"P-{year}-{slug}":
                    all_ok = False
                    break
            policies_struct_ok = all_ok
    scores["factbook_policies_structure"] = 1.0 if policies_struct_ok else 0.0

    policies_vals_ok = False
    if policies_struct_ok and policy_items is not None and factbook is not None:
        policies = factbook.get("policies", [])
        html_set = {(p["year"], p["policy"], p["desc"]) for p in policy_items}
        all_match = True
        for item in policies:
            tup = (item.get("year"), item.get("policy"), item.get("desc"))
            if tup not in html_set:
                all_match = False
                break
        policies_vals_ok = all_match
    scores["factbook_policies_values"] = 1.0 if policies_vals_ok else 0.0

    storyboard_rows = None
    storyboard_header = None
    sb_parsed = _parse_storyboard_csv(storyboard_path)
    if sb_parsed is not None:
        storyboard_rows, storyboard_header = sb_parsed

    storyboard_struct_ok = False
    if storyboard_rows is not None and storyboard_header is not None and factbook is not None:
        required_cols = ["scene_id", "visual", "narration", "citations"]
        header_set = set(storyboard_header)
        if header_set == set(required_cols) and len(storyboard_header) == 4:
            if len(storyboard_rows) == 8:
                scene_ids = []
                all_ok = True
                for row in storyboard_rows:
                    sid_str = row.get("scene_id", "")
                    try:
                        sid = int(sid_str)
                    except Exception:
                        all_ok = False
                        break
                    scene_ids.append(sid)
                    if not row.get("visual"):
                        all_ok = False
                        break
                    if _word_count(row.get("narration", "")) > 60:
                        all_ok = False
                        break
                    if not row.get("citations"):
                        all_ok = False
                        break
                if all_ok and set(scene_ids) == set(range(1, 9)):
                    storyboard_struct_ok = True
    scores["storyboard_structure"] = 1.0 if storyboard_struct_ok else 0.0

    storyboard_cov_ok = False
    if storyboard_struct_ok and factbook is not None:
        fb_ids = set()
        for item in factbook.get("top_sectors_2020", []):
            fb_ids.add(item.get("id"))
        for item in factbook.get("quotes", []):
            fb_ids.add(item.get("id"))
        for item in factbook.get("policies", []):
            fb_ids.add(item.get("id"))
        cited = set()
        only_from_factbook = True
        for row in storyboard_rows:
            cits = [c.strip() for c in (row.get("citations", "") or "").split(";") if c.strip()]
            for c in cits:
                if c not in fb_ids:
                    only_from_factbook = False
                cited.add(c)
        storyboard_cov_ok = (cited == fb_ids) and only_from_factbook
    scores["storyboard_citations_coverage"] = 1.0 if storyboard_cov_ok else 0.0

    voiceover_text = _safe_read_text(voiceover_path)
    voiceover_struct_ok = False
    if voiceover_text is not None:
        headers = _extract_scene_headers_from_md(voiceover_text)
        scenes_ok = headers == [f"S{i}" for i in range(1, 9)]
        idx_entries = _extract_citations_index(voiceover_text)
        voiceover_struct_ok = scenes_ok and (idx_entries is not None)
    scores["voiceover_structure"] = 1.0 if voiceover_struct_ok else 0.0

    voiceover_index_match_ok = False
    voiceover_source_presence_ok = False
    if voiceover_text is not None and storyboard_struct_ok:
        idx_entries = _extract_citations_index(voiceover_text)
        if idx_entries is not None:
            idx_set = set(idx_entries)
            cited = set()
            for row in storyboard_rows:
                cits = [c.strip() for c in (row.get("citations", "") or "").split(";") if c.strip()]
                cited.update(cits)
            voiceover_index_match_ok = idx_set == cited
            if factbook is not None:
                voiceover_source_presence_ok = _citations_index_source_check(voiceover_text, factbook)
    scores["voiceover_citations_index_match"] = 1.0 if voiceover_index_match_ok else 0.0
    scores["voiceover_citation_lines_source_presence"] = 1.0 if voiceover_source_presence_ok else 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result))


if __name__ == "__main__":
    main()