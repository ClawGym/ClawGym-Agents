import csv
import json
import math
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any, Set


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        if not path.exists() or not path.is_file():
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _safe_load_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        if not path.exists() or not path.is_file():
            return None, None
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            return rows, reader.fieldnames
    except Exception:
        return None, None


def _is_nonempty_file(path: Path) -> bool:
    try:
        return path.exists() and path.is_file() and path.stat().st_size > 0
    except Exception:
        return False


def _decade_label(year: int) -> str:
    d = (year // 10) * 10
    return f"{d}s"


def _has_cjk(text: str) -> bool:
    for ch in text:
        code = ord(ch)
        if (
            0x4E00 <= code <= 0x9FFF or  # CJK Unified Ideographs
            0x3400 <= code <= 0x4DBF or  # CJK Unified Ideographs Extension A
            0xF900 <= code <= 0xFAFF or  # CJK Compatibility Ideographs
            0x3000 <= code <= 0x303F or  # CJK Symbols and Punctuation
            0xFF00 <= code <= 0xFFEF     # Halfwidth and Fullwidth Forms
        ):
            return True
    return False


def _parse_int(s: str) -> Optional[int]:
    try:
        if s is None:
            return None
        s = s.strip()
        if s == "":
            return None
        return int(s)
    except Exception:
        return None


def _parse_float(s: str) -> Optional[float]:
    try:
        if s is None:
            return None
        s = s.strip()
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def _compute_policy_summary(policies_rows: List[Dict[str, str]], domain_map: Dict[str, str]) -> Optional[Dict[Tuple[str, str], Dict[str, int]]]:
    # Returns mapping: (decade, category) -> dict with total_policies, national_count, provincial_count
    summary: Dict[Tuple[str, str], Dict[str, int]] = {}
    try:
        for r in policies_rows:
            year = _parse_int(r.get("year", ""))
            domain = (r.get("domain") or "").strip()
            level = (r.get("level") or "").strip()
            if year is None:
                return None
            if domain not in domain_map:
                return None
            category = domain_map[domain]
            decade = _decade_label(year)
            key = (decade, category)
            if key not in summary:
                summary[key] = {"total_policies": 0, "national_count": 0, "provincial_count": 0}
            summary[key]["total_policies"] += 1
            if level == "national":
                summary[key]["national_count"] += 1
            if level == "provincial":
                summary[key]["provincial_count"] += 1
        return summary
    except Exception:
        return None


def _compute_incidents_summary(inc_rows: List[Dict[str, str]]) -> Optional[Dict[Tuple[str, str], Dict[str, Any]]]:
    # Returns mapping: (decade, category) -> dict with total_incidents (int), avg_incidents_per_year (float)
    try:
        grouped_counts: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for r in inc_rows:
            year = _parse_int(r.get("year", ""))
            category = (r.get("category") or "").strip()
            count = _parse_int(r.get("count", ""))
            if year is None or category == "" or count is None:
                return None
            decade = _decade_label(year)
            key = (decade, category)
            if key not in grouped_counts:
                grouped_counts[key] = {"total": 0, "years": set()}
            grouped_counts[key]["total"] += count
            grouped_counts[key]["years"].add(year)
        result: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for key, d in grouped_counts.items():
            total = d["total"]
            years_present = len(d["years"])
            if years_present == 0:
                return None
            avg = round(float(total) / float(years_present), 2)
            result[key] = {"total_incidents": int(total), "avg_incidents_per_year": float(avg)}
        return result
    except Exception:
        return None


def _load_domain_mapping(path: Path) -> Optional[Dict[str, str]]:
    rows, header = _safe_load_csv(path)
    if rows is None or header is None:
        return None
    if "domain" not in header or "category" not in header:
        return None
    mapping: Dict[str, str] = {}
    try:
        for r in rows:
            d = (r.get("domain") or "").strip()
            c = (r.get("category") or "").strip()
            if d == "" or c == "":
                return None
            mapping[d] = c
        return mapping
    except Exception:
        return None


def _load_summary_policy(path: Path) -> Optional[Tuple[Dict[Tuple[str, str], Dict[str, int]], List[str]]]:
    rows, header = _safe_load_csv(path)
    if rows is None or header is None:
        return None
    expected_header = ["decade", "category", "total_policies", "national_count", "provincial_count"]
    parsed: Dict[Tuple[str, str], Dict[str, int]] = {}
    try:
        for r in rows:
            decade = (r.get("decade") or "").strip()
            category = (r.get("category") or "").strip()
            tp = _parse_int(r.get("total_policies", ""))
            nc = _parse_int(r.get("national_count", ""))
            pc = _parse_int(r.get("provincial_count", ""))
            if decade == "" or category == "" or tp is None or nc is None or pc is None:
                return None
            parsed[(decade, category)] = {
                "total_policies": tp,
                "national_count": nc,
                "provincial_count": pc,
            }
    except Exception:
        return None
    return parsed, header


def _load_summary_incidents(path: Path) -> Optional[Tuple[Dict[Tuple[str, str], Dict[str, Any]], List[str]]]:
    rows, header = _safe_load_csv(path)
    if rows is None or header is None:
        return None
    expected_header = ["decade", "category", "total_incidents", "avg_incidents_per_year"]
    parsed: Dict[Tuple[str, str], Dict[str, Any]] = {}
    try:
        for r in rows:
            decade = (r.get("decade") or "").strip()
            category = (r.get("category") or "").strip()
            ti = _parse_int(r.get("total_incidents", ""))
            avg = _parse_float(r.get("avg_incidents_per_year", ""))
            if decade == "" or category == "" or ti is None or avg is None:
                return None
            parsed[(decade, category)] = {
                "total_incidents": ti,
                "avg_incidents_per_year": round(float(avg), 2),
            }
    except Exception:
        return None
    return parsed, header


def _load_joined_summary(path: Path) -> Optional[Tuple[Dict[Tuple[str, str], Dict[str, Any]], List[str]]]:
    rows, header = _safe_load_csv(path)
    if rows is None or header is None:
        return None
    expected_header = [
        "decade",
        "category",
        "total_policies",
        "national_count",
        "provincial_count",
        "total_incidents",
        "avg_incidents_per_year",
    ]
    parsed: Dict[Tuple[str, str], Dict[str, Any]] = {}
    try:
        for r in rows:
            decade = (r.get("decade") or "").strip()
            category = (r.get("category") or "").strip()
            tp = _parse_int(r.get("total_policies", ""))
            nc = _parse_int(r.get("national_count", ""))
            pc = _parse_int(r.get("provincial_count", ""))
            ti = _parse_int(r.get("total_incidents", ""))
            avg = _parse_float(r.get("avg_incidents_per_year", ""))
            if decade == "" or category == "" or tp is None or nc is None or pc is None or ti is None or avg is None:
                return None
            parsed[(decade, category)] = {
                "total_policies": tp,
                "national_count": nc,
                "provincial_count": pc,
                "total_incidents": ti,
                "avg_incidents_per_year": round(float(avg), 2),
            }
    except Exception:
        return None
    return parsed, header


def _extract_numbers_from_text(text: str) -> List[float]:
    # Extract numbers like 12, 12.34
    import re
    nums: List[float] = []
    for m in re.finditer(r'\d+(?:\.\d+)?', text):
        token = m.group(0)
        try:
            if '.' in token:
                nums.append(float(token))
            else:
                nums.append(float(int(token)))
        except Exception:
            continue
    return nums


def _collect_joined_numeric_values(joined: Dict[Tuple[str, str], Dict[str, Any]]) -> Tuple[Set[int], Set[float]]:
    ints: Set[int] = set()
    floats: Set[float] = set()
    for _, vals in joined.items():
        for k in ("total_policies", "national_count", "provincial_count", "total_incidents"):
            v = vals.get(k)
            if isinstance(v, (int, float)):
                try:
                    ints.add(int(v))
                except Exception:
                    pass
        vavg = vals.get("avg_incidents_per_year")
        if isinstance(vavg, (int, float)):
            floats.add(round(float(vavg), 2))
    return ints, floats


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    # Paths
    policies_csv = workspace / "input" / "data" / "policies.csv"
    incidents_csv = workspace / "input" / "data" / "incidents.csv"
    domain_map_csv = workspace / "input" / "data" / "domain_category_map.csv"
    draft_post_md = workspace / "input" / "draft" / "draft_post.md"

    out_policy = workspace / "output" / "policy_summary_by_decade.csv"
    out_incidents = workspace / "output" / "incidents_summary_by_decade.csv"
    out_joined = workspace / "output" / "joined_summary_by_decade.csv"
    out_mismatches = workspace / "output" / "validation" / "mismatches.txt"

    out_rewrite = workspace / "output" / "social" / "改写稿.md"
    out_weibo = workspace / "output" / "social" / "微博线程.md"
    out_status = workspace / "output" / "status" / "小组更新.md"

    scores: Dict[str, float] = {
        "pipeline_outputs_exist_nonempty": 0.0,
        "policy_summary_columns_correct": 0.0,
        "incidents_summary_columns_correct": 0.0,
        "joined_summary_columns_correct": 0.0,
        "policy_summary_values_match_inputs": 0.0,
        "incidents_summary_values_match_inputs": 0.0,
        "joined_summary_values_and_pairs_correct": 0.0,
        "mismatches_file_correct": 0.0,
        "social_rewrite_exists_no_placeholders": 0.0,
        "social_rewrite_bullet_count_ok": 0.0,
        "social_rewrite_two_numbers_from_joined": 0.0,
        "social_rewrite_chinese": 0.0,
        "weibo_exists_reference_and_chinese": 0.0,
        "weibo_bullet_count_ok": 0.0,
        "weibo_two_numbers_from_joined": 0.0,
        "status_exists_paths_and_chinese": 0.0,
        "status_paragraph_count_ok": 0.0,
    }

    # 1) Required four outputs exist and non-empty
    if all(_is_nonempty_file(p) for p in [out_policy, out_incidents, out_joined, out_mismatches]):
        scores["pipeline_outputs_exist_nonempty"] = 1.0

    # Load domain mapping and inputs
    policies_rows, _ = _safe_load_csv(policies_csv)
    incidents_rows, _ = _safe_load_csv(incidents_csv)
    domain_map = _load_domain_mapping(domain_map_csv)

    # Recompute expected summaries if possible
    expected_policy_summary = None
    expected_incidents_summary = None
    if policies_rows is not None and domain_map is not None:
        expected_policy_summary = _compute_policy_summary(policies_rows, domain_map)
    if incidents_rows is not None:
        expected_incidents_summary = _compute_incidents_summary(incidents_rows)

    # Load produced summaries
    policy_loaded = _load_summary_policy(out_policy) if _is_nonempty_file(out_policy) else None
    incidents_loaded = _load_summary_incidents(out_incidents) if _is_nonempty_file(out_incidents) else None
    joined_loaded = _load_joined_summary(out_joined) if _is_nonempty_file(out_joined) else None

    # Columns correctness checks
    if policy_loaded is not None:
        _, header = policy_loaded
        if header == ["decade", "category", "total_policies", "national_count", "provincial_count"]:
            scores["policy_summary_columns_correct"] = 1.0
    if incidents_loaded is not None:
        _, header = incidents_loaded
        if header == ["decade", "category", "total_incidents", "avg_incidents_per_year"]:
            scores["incidents_summary_columns_correct"] = 1.0
    if joined_loaded is not None:
        _, header = joined_loaded
        if header == [
            "decade",
            "category",
            "total_policies",
            "national_count",
            "provincial_count",
            "total_incidents",
            "avg_incidents_per_year",
        ]:
            scores["joined_summary_columns_correct"] = 1.0

    # Values match inputs checks
    if policy_loaded is not None and expected_policy_summary is not None:
        produced_map, _ = policy_loaded
        if produced_map is not None and expected_policy_summary is not None:
            # Strict set equality and values equality
            if set(produced_map.keys()) == set(expected_policy_summary.keys()):
                ok = True
                for k, vals in produced_map.items():
                    exp = expected_policy_summary.get(k)
                    if exp is None:
                        ok = False
                        break
                    if not (vals.get("total_policies") == exp.get("total_policies") and
                            vals.get("national_count") == exp.get("national_count") and
                            vals.get("provincial_count") == exp.get("provincial_count")):
                        ok = False
                        break
                scores["policy_summary_values_match_inputs"] = 1.0 if ok else 0.0

    if incidents_loaded is not None and expected_incidents_summary is not None:
        produced_map, _ = incidents_loaded
        if produced_map is not None and expected_incidents_summary is not None:
            if set(produced_map.keys()) == set(expected_incidents_summary.keys()):
                ok = True
                for k, vals in produced_map.items():
                    exp = expected_incidents_summary.get(k)
                    if exp is None:
                        ok = False
                        break
                    # total incidents
                    if vals.get("total_incidents") != exp.get("total_incidents"):
                        ok = False
                        break
                    # avg float compare to 2 decimals
                    vavg = round(float(vals.get("avg_incidents_per_year")), 2)
                    eavg = round(float(exp.get("avg_incidents_per_year")), 2)
                    if abs(vavg - eavg) > 1e-9:
                        ok = False
                        break
                scores["incidents_summary_values_match_inputs"] = 1.0 if ok else 0.0

    # Joined summary correctness: only pairs present in both and values match
    if joined_loaded is not None and policy_loaded is not None and incidents_loaded is not None:
        joined_map, _ = joined_loaded
        pol_map, _ = policy_loaded
        inc_map, _ = incidents_loaded
        if joined_map is not None and pol_map is not None and inc_map is not None:
            intersection = set(pol_map.keys()).intersection(set(inc_map.keys()))
            ok = True
            # Must equal intersection
            if set(joined_map.keys()) != intersection:
                ok = False
            else:
                for k, vals in joined_map.items():
                    pol_vals = pol_map.get(k)
                    inc_vals = inc_map.get(k)
                    if pol_vals is None or inc_vals is None:
                        ok = False
                        break
                    # Compare policy fields
                    if not (vals.get("total_policies") == pol_vals.get("total_policies") and
                            vals.get("national_count") == pol_vals.get("national_count") and
                            vals.get("provincial_count") == pol_vals.get("provincial_count")):
                        ok = False
                        break
                    # Compare incident fields
                    if vals.get("total_incidents") != inc_vals.get("total_incidents"):
                        ok = False
                        break
                    if abs(round(float(vals.get("avg_incidents_per_year")), 2) - round(float(inc_vals.get("avg_incidents_per_year")), 2)) > 1e-9:
                        ok = False
                        break
            scores["joined_summary_values_and_pairs_correct"] = 1.0 if ok else 0.0

    # Mismatches file correctness
    if _is_nonempty_file(out_mismatches) and policy_loaded is not None and incidents_loaded is not None:
        txt = _safe_read_text(out_mismatches)
        pol_map, _ = policy_loaded
        inc_map, _ = incidents_loaded
        if txt is not None and pol_map is not None and inc_map is not None:
            pol_pairs = set(pol_map.keys())
            inc_pairs = set(inc_map.keys())
            symdiff = pol_pairs.symmetric_difference(inc_pairs)
            content = txt.strip()
            if len(symdiff) == 0:
                # Expect exact text "No mismatches"
                if content == "No mismatches":
                    scores["mismatches_file_correct"] = 1.0
            else:
                # For each mismatched pair, ensure one line contains both tokens
                lines = [line.strip() for line in txt.splitlines() if line.strip() != ""]
                found_all = True
                for (decade, category) in symdiff:
                    matched = False
                    for ln in lines:
                        if decade in ln and category in ln:
                            matched = True
                            break
                    if not matched:
                        found_all = False
                        break
                if found_all:
                    scores["mismatches_file_correct"] = 1.0

    # Social rewrite checks
    if _is_nonempty_file(out_rewrite):
        text = _safe_read_text(out_rewrite) or ""
        no_placeholders = "【待填" not in text
        # bullets count 3-5
        import re
        bullet_lines = [ln for ln in text.splitlines() if re.match(r'^\s*[-*•·]\s+', ln)]
        bullet_ok = 3 <= len(bullet_lines) <= 5
        chinese_ok = _has_cjk(text)
        # cross-check at least two numbers from joined summary
        nums_in_text = _extract_numbers_from_text(text)
        two_numbers_ok = False
        if joined_loaded is not None:
            joined_map, _ = joined_loaded
            ints_set, floats_set = _collect_joined_numeric_values(joined_map)
            match_count = 0
            for num in nums_in_text:
                # if decimal part exists
                if abs(num - round(num)) > 1e-9:
                    # float
                    if any(abs(num - f) < 1e-9 for f in floats_set):
                        match_count += 1
                else:
                    # integer
                    if int(round(num)) in ints_set:
                        match_count += 1
                if match_count >= 2:
                    two_numbers_ok = True
                    break
        scores["social_rewrite_exists_no_placeholders"] = 1.0 if no_placeholders else 0.0
        scores["social_rewrite_bullet_count_ok"] = 1.0 if bullet_ok else 0.0
        scores["social_rewrite_two_numbers_from_joined"] = 1.0 if two_numbers_ok else 0.0
        scores["social_rewrite_chinese"] = 1.0 if chinese_ok else 0.0

    # Weibo thread checks
    if _is_nonempty_file(out_weibo):
        text = _safe_read_text(out_weibo) or ""
        import re
        bullet_lines = [ln for ln in text.splitlines() if re.match(r'^\s*[-*•·]\s+', ln)]
        bullet_ok = 3 <= len(bullet_lines) <= 5
        ref_ok = "基于本地数据汇总（见 CSV 输出）" in text
        chinese_ok = _has_cjk(text)
        nums_in_text = _extract_numbers_from_text(text)
        two_numbers_ok = False
        if joined_loaded is not None:
            joined_map, _ = joined_loaded
            ints_set, floats_set = _collect_joined_numeric_values(joined_map)
            match_count = 0
            for num in nums_in_text:
                if abs(num - round(num)) > 1e-9:
                    if any(abs(num - f) < 1e-9 for f in floats_set):
                        match_count += 1
                else:
                    if int(round(num)) in ints_set:
                        match_count += 1
                if match_count >= 2:
                    two_numbers_ok = True
                    break
        scores["weibo_exists_reference_and_chinese"] = 1.0 if (ref_ok and chinese_ok and _is_nonempty_file(out_weibo)) else 0.0
        scores["weibo_bullet_count_ok"] = 1.0 if bullet_ok else 0.0
        scores["weibo_two_numbers_from_joined"] = 1.0 if two_numbers_ok else 0.0

    # Status update checks
    if _is_nonempty_file(out_status):
        text = _safe_read_text(out_status) or ""
        # paragraphs separated by blank lines
        paras = [p for p in [p.strip() for p in text.split("\n\n")] if p != ""]
        para_ok = 1 <= len(paras) <= 2
        paths_ok = ("output/policy_summary_by_decade.csv" in text) and ("output/incidents_summary_by_decade.csv" in text)
        chinese_ok = _has_cjk(text)
        scores["status_exists_paths_and_chinese"] = 1.0 if (paths_ok and chinese_ok) else 0.0
        scores["status_paragraph_count_ok"] = 1.0 if para_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()