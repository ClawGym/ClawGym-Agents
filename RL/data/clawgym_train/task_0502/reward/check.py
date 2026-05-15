import csv
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _safe_read_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            headers = reader.fieldnames if reader.fieldnames is not None else []
            return rows, headers
    except Exception:
        return None, None


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _file_sha256(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _is_lowercase_text(text: str) -> bool:
    return not any("A" <= ch <= "Z" for ch in text)


def _tokenize_whitespace(text: str) -> List[str]:
    return text.split()


def _count_variant_in_tokens(tokens: List[str], variant: str) -> int:
    var_tokens = variant.lower().split()
    n = len(var_tokens)
    if n == 0 or len(tokens) < n:
        return 0
    count = 0
    for i in range(len(tokens) - n + 1):
        if tokens[i:i+n] == var_tokens:
            count += 1
    return count


def _float_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _find_section_indices(lines: List[str], section_name: str) -> Optional[int]:
    target = section_name.strip().lower()
    for idx, line in enumerate(lines):
        s = line.lstrip("#").strip().lower()
        if s.startswith(target + ":") or s == target or s.startswith(target + " "):
            return idx
    return None


def _get_section_block(lines: List[str], start_idx: int, next_start_idx: Optional[int]) -> List[str]:
    if start_idx is None:
        return []
    end = next_start_idx if next_start_idx is not None else len(lines)
    block = lines[start_idx + 1:end]
    return block


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores: Dict[str, float] = {
        "raw_texts_present": 0.0,
        "sources_manifest_valid": 0.0,
        "sources_manifest_checksums_match_files": 0.0,
        "clean_texts_present_and_lowercase": 0.0,
        "clean_texts_removed_gutenberg_headers": 0.0,
        "lexicon_counts_structure_complete": 0.0,
        "lexicon_counts_values_correct": 0.0,
        "rates_per_10k_correct": 0.0,
        "ranked_terms_structure_and_sorting": 0.0,
        "ranked_terms_values_correct": 0.0,
        "meeting_notes_sections_present": 0.0,
        "meeting_sources_summary_correct": 0.0,
        "meeting_method_covers_required_points": 0.0,
        "meeting_ranked_findings_top3_correct": 0.0,
        "meeting_observations_count": 0.0,
        "meeting_action_items_count": 0.0,
    }

    works_path = workspace / "input" / "works_metadata.csv"
    lexicon_path = workspace / "input" / "lexicon.csv"
    works_rows, works_headers = _safe_read_csv(works_path)
    lexicon_rows, lexicon_headers = _safe_read_csv(lexicon_path)

    if not works_rows or not lexicon_rows:
        works_rows = works_rows or []
        lexicon_rows = lexicon_rows or []

    works_by_id: Dict[str, Dict[str, str]] = {}
    gutenberg_ids: Dict[str, str] = {}
    work_ids: List[str] = []
    if works_rows:
        required_wcols = {"work_id", "title", "author", "publication_year", "gutenberg_id"}
        if works_headers and required_wcols.issubset(set(works_headers)):
            for row in works_rows:
                wid = row.get("work_id", "").strip()
                gid = row.get("gutenberg_id", "").strip()
                if wid and gid:
                    works_by_id[wid] = row
                    gutenberg_ids[wid] = gid
                    work_ids.append(wid)

    lexicon_variants: List[Tuple[str, str, str, str]] = []
    lexicon_map_by_group_variant: Dict[Tuple[str, str], Tuple[str, str]] = {}
    if lexicon_rows:
        required_lcols = {"term_group_id", "canonical", "variant", "variant_role"}
        if lexicon_headers and required_lcols.issubset(set(lexicon_headers)):
            for row in lexicon_rows:
                tg = row.get("term_group_id", "").strip()
                canonical = row.get("canonical", "").strip()
                variant = row.get("variant", "").strip()
                role = row.get("variant_role", "").strip()
                if tg and canonical and variant and role:
                    lexicon_variants.append((tg, canonical, variant, role))
                    lexicon_map_by_group_variant[(tg, variant)] = (canonical, role)

    raw_ok = True
    for wid in work_ids:
        gid = gutenberg_ids.get(wid, "")
        if not gid:
            raw_ok = False
            break
        raw_path = workspace / "data" / "raw" / f"pg_{gid}.txt"
        if not raw_path.exists() or not raw_path.is_file():
            raw_ok = False
            break
        try:
            if raw_path.stat().st_size <= 0:
                raw_ok = False
                break
        except Exception:
            raw_ok = False
            break
    scores["raw_texts_present"] = 1.0 if (work_ids and raw_ok) else 0.0

    sources_path = workspace / "outputs" / "sources.csv"
    sources_rows, sources_headers = _safe_read_csv(sources_path)
    sources_valid = False
    checksum_match = False
    if sources_rows is not None and sources_headers is not None:
        req_cols = {"work_id", "gutenberg_id", "download_url", "http_status", "bytes", "sha256"}
        if req_cols.issubset(set(sources_headers)):
            idx_by_work = {}
            for r in sources_rows:
                wid = (r.get("work_id") or "").strip()
                if wid and wid not in idx_by_work:
                    idx_by_work[wid] = r
            all_good = True
            checksum_good = True
            for wid in work_ids:
                if wid not in idx_by_work:
                    all_good = False
                    checksum_good = False
                    break
                r = idx_by_work[wid]
                gid = (r.get("gutenberg_id") or "").strip()
                url = (r.get("download_url") or "").strip()
                status = (r.get("http_status") or "").strip()
                bytes_s = (r.get("bytes") or "").strip()
                sha = (r.get("sha256") or "").strip()
                if gid != gutenberg_ids.get(wid, ""):
                    all_good = False
                if not url or ("gutenberg.org" not in url.lower()):
                    all_good = False
                if url.lower().endswith(".html") or url.lower().endswith(".htm"):
                    all_good = False
                if not (url.lower().endswith(".txt") or url.lower().endswith(".txt.utf-8") or url.lower().endswith(".zip")):
                    all_good = False
                try:
                    _ = int(status)
                except Exception:
                    all_good = False
                try:
                    bval = int(bytes_s)
                    if bval < 0:
                        all_good = False
                except Exception:
                    all_good = False
                if not re.fullmatch(r"[0-9a-fA-F]{64}", sha or ""):
                    all_good = False
                raw_path = workspace / "data" / "raw" / f"pg_{gid}.txt"
                if not raw_path.exists():
                    checksum_good = False
                else:
                    try:
                        size = raw_path.stat().st_size
                    except Exception:
                        size = -1
                    comp_sha = _file_sha256(raw_path)
                    if comp_sha is None or size < 0:
                        checksum_good = False
                    else:
                        if str(size) != bytes_s or comp_sha.lower() != sha.lower():
                            checksum_good = False
            sources_valid = all_good and len(idx_by_work) >= len(work_ids) and len(work_ids) > 0
            checksum_match = checksum_good and sources_valid
    scores["sources_manifest_valid"] = 1.0 if sources_valid else 0.0
    scores["sources_manifest_checksums_match_files"] = 1.0 if checksum_match else 0.0

    clean_ok = True
    lowercase_ok = True
    header_removed_ok = True
    tokens_by_work: Dict[str, List[str]] = {}
    for wid in work_ids:
        gid = gutenberg_ids.get(wid, "")
        clean_path = workspace / "data" / "clean" / f"pg_{gid}.clean.txt"
        txt = _safe_read_text(clean_path)
        if txt is None or len(txt.strip()) == 0:
            clean_ok = False
            lowercase_ok = False
            header_removed_ok = False
            break
        if not _is_lowercase_text(txt):
            lowercase_ok = False
        tokens = _tokenize_whitespace(txt)
        if len(tokens) == 0:
            clean_ok = False
        tokens_by_work[wid] = tokens
        low = txt.lower()
        markers = [
            "start of this project gutenberg ebook",
            "end of the project gutenberg ebook",
            "end of this project gutenberg ebook",
        ]
        if any(m in low for m in markers):
            header_removed_ok = False
    if work_ids:
        scores["clean_texts_present_and_lowercase"] = 1.0 if (clean_ok and lowercase_ok) else 0.0
        scores["clean_texts_removed_gutenberg_headers"] = 1.0 if header_removed_ok and clean_ok else 0.0
    else:
        scores["clean_texts_present_and_lowercase"] = 0.0
        scores["clean_texts_removed_gutenberg_headers"] = 0.0

    counts_path = workspace / "outputs" / "lexicon_counts.csv"
    counts_rows, counts_headers = _safe_read_csv(counts_path)
    structure_ok = False
    counts_correct_ok = False
    rates_ok = False
    if counts_rows is not None and counts_headers is not None and work_ids and lexicon_variants:
        req_cols = {"work_id", "title", "author", "publication_year", "term_group_id", "canonical", "variant", "variant_role", "count", "rate_per_10k"}
        header_has = req_cols.issubset(set(counts_headers))
        if header_has:
            expected_rows = len(work_ids) * len(lexicon_variants)
            seen_keys = set()
            per_row_meta_ok = True
            for row in counts_rows:
                wid = (row.get("work_id") or "").strip()
                tg = (row.get("term_group_id") or "").strip()
                canonical = (row.get("canonical") or "").strip()
                variant = (row.get("variant") or "").strip()
                role = (row.get("variant_role") or "").strip()
                title = (row.get("title") or "").strip()
                author = (row.get("author") or "").strip()
                pubyear = (row.get("publication_year") or "").strip()
                if wid not in works_by_id or (tg, variant) not in lexicon_map_by_group_variant:
                    per_row_meta_ok = False
                    break
                lex_canon, lex_role = lexicon_map_by_group_variant[(tg, variant)]
                if canonical != lex_canon or role != lex_role:
                    per_row_meta_ok = False
                    break
                md = works_by_id[wid]
                if title != (md.get("title") or "").strip() or author != (md.get("author") or "").strip() or pubyear != (md.get("publication_year") or "").strip():
                    per_row_meta_ok = False
                    break
                key = (wid, tg, variant)
                if key in seen_keys:
                    per_row_meta_ok = False
                    break
                seen_keys.add(key)
            structure_ok = per_row_meta_ok and len(counts_rows) == expected_rows and len(seen_keys) == expected_rows

            if structure_ok:
                counts_ok = True
                rates_all_ok = True
                total_tokens_by_work = {wid: len(tokens_by_work.get(wid, [])) for wid in work_ids}
                for row in counts_rows:
                    wid = row["work_id"].strip()
                    tg = row["term_group_id"].strip()
                    variant = row["variant"].strip().lower()
                    tokens = tokens_by_work.get(wid, [])
                    if not tokens:
                        counts_ok = False
                        rates_all_ok = False
                        break
                    expected_count = _count_variant_in_tokens(tokens, variant)
                    try:
                        reported_count = int(str(row.get("count", "0")).strip())
                    except Exception:
                        counts_ok = False
                        rates_all_ok = False
                        break
                    if reported_count != expected_count:
                        counts_ok = False
                    try:
                        reported_rate = float(str(row.get("rate_per_10k", "0")).strip())
                    except Exception:
                        rates_all_ok = False
                        continue
                    tkns = total_tokens_by_work[wid]
                    if tkns <= 0:
                        rates_all_ok = False
                        break
                    expected_rate = (expected_count * 10000.0) / float(tkns)
                    if not _float_equal(reported_rate, expected_rate, tol=1e-6):
                        rates_all_ok = False
                counts_correct_ok = counts_ok
                rates_ok = rates_all_ok

    scores["lexicon_counts_structure_complete"] = 1.0 if structure_ok else 0.0
    scores["lexicon_counts_values_correct"] = 1.0 if counts_correct_ok else 0.0
    scores["rates_per_10k_correct"] = 1.0 if rates_ok else 0.0

    ranked_path = workspace / "outputs" / "ranked_terms.csv"
    ranked_rows, ranked_headers = _safe_read_csv(ranked_path)
    ranked_structure_ok = False
    ranked_values_ok = False
    if ranked_rows is not None and ranked_headers is not None and structure_ok:
        req_cols = {"term_group_id", "canonical", "modern_total_rate", "historical_total_rate", "delta_modern_minus_historical", "dominant_variant", "trend_class"}
        if req_cols.issubset(set(ranked_headers)):
            seen_tg = set()
            deltas = []
            dom_variant_in_group_ok = True
            for r in ranked_rows:
                tg = (r.get("term_group_id") or "").strip()
                if tg in seen_tg:
                    dom_variant_in_group_ok = False
                    break
                seen_tg.add(tg)
                try:
                    delta = float(str(r.get("delta_modern_minus_historical", "0")).strip())
                except Exception:
                    dom_variant_in_group_ok = False
                    break
                deltas.append(delta)
                dom = (r.get("dominant_variant") or "").strip()
                group_variants = [v for (tg_id, _canon, v, _role) in lexicon_variants if tg_id == tg]
                if dom not in group_variants:
                    dom_variant_in_group_ok = False
                    break
                trend = (r.get("trend_class") or "").strip()
                if trend not in {"modernizing", "historicalizing", "mixed"}:
                    dom_variant_in_group_ok = False
                    break
            sorted_desc = all(deltas[i] >= deltas[i+1] for i in range(len(deltas)-1)) if deltas else False
            groups_in_lexicon = set([tg for (tg, _c, _v, _r) in lexicon_variants])
            ranked_structure_ok = dom_variant_in_group_ok and sorted_desc and (set(seen_tg) == groups_in_lexicon)
            if ranked_structure_ok and counts_rows is not None:
                rate_by_tg_variant = {}
                rate_by_tg_role_wid = {}
                years_by_wid = {}
                for w in works_rows:
                    if "work_id" in w and "publication_year" in w and w["work_id"]:
                        try:
                            years_by_wid[w["work_id"]] = int(w["publication_year"])
                        except Exception:
                            years_by_wid[w["work_id"]] = 0
                for row in counts_rows:
                    tg = row["term_group_id"].strip()
                    variant = row["variant"].strip()
                    wid = row["work_id"].strip()
                    role = row["variant_role"].strip()
                    try:
                        rate = float(str(row.get("rate_per_10k", "0")).strip())
                    except Exception:
                        rate = float("nan")
                    rate_by_tg_variant[(tg, variant)] = rate_by_tg_variant.get((tg, variant), 0.0) + rate
                    key = (tg, role, wid)
                    rate_by_tg_role_wid[key] = rate_by_tg_role_wid.get(key, 0.0) + rate

                def _monotonic(seq: List[float], nondecreasing: bool) -> bool:
                    if nondecreasing:
                        return all(seq[i] <= seq[i+1] + 1e-9 for i in range(len(seq)-1))
                    else:
                        return all(seq[i] >= seq[i+1] - 1e-9 for i in range(len(seq)-1))

                recomputed = {}
                for tg in groups_in_lexicon:
                    variants_in_group = [(tg_id, canon, v, role) for (tg_id, canon, v, role) in lexicon_variants if tg_id == tg]
                    modern_total = 0.0
                    historical_total = 0.0
                    for (_tg, _canon, v, role) in variants_in_group:
                        total_rate = rate_by_tg_variant.get((tg, v), 0.0)
                        if role.lower() == "modern":
                            modern_total += total_rate
                        elif role.lower() == "historical":
                            historical_total += total_rate
                    delta = modern_total - historical_total
                    ordered_w = sorted(work_ids, key=lambda w: years_by_wid.get(w, 0))
                    modern_seq = []
                    historical_seq = []
                    for wid in ordered_w:
                        modern_seq.append(rate_by_tg_role_wid.get((tg, "modern", wid), 0.0))
                        historical_seq.append(rate_by_tg_role_wid.get((tg, "historical", wid), 0.0))
                    if _monotonic(modern_seq, True) and _monotonic(historical_seq, False):
                        trend = "modernizing"
                    elif _monotonic(modern_seq, False) and _monotonic(historical_seq, True):
                        trend = "historicalizing"
                    else:
                        trend = "mixed"
                    variant_totals = {}
                    for (_tg, _canon, v, _role) in variants_in_group:
                        variant_totals[v] = rate_by_tg_variant.get((tg, v), 0.0)
                    if variant_totals:
                        max_val = max(variant_totals.values())
                        dom_candidates = [v for v, val in variant_totals.items() if abs(val - max_val) <= 1e-6]
                        dominant_choice = set(dom_candidates)
                    else:
                        dominant_choice = set()
                    recomputed[tg] = (modern_total, historical_total, delta, dominant_choice, trend)
                values_ok = True
                for r in ranked_rows:
                    tg = r["term_group_id"].strip()
                    canon = r["canonical"].strip()
                    canonical_from_lex = None
                    for (tg_id, c, _v, _role) in lexicon_variants:
                        if tg_id == tg:
                            canonical_from_lex = c
                            break
                    if canonical_from_lex is None or canon != canonical_from_lex:
                        values_ok = False
                        break
                    try:
                        modern_total_r = float(str(r.get("modern_total_rate", "0")).strip())
                        historical_total_r = float(str(r.get("historical_total_rate", "0")).strip())
                        delta_r = float(str(r.get("delta_modern_minus_historical", "0")).strip())
                    except Exception:
                        values_ok = False
                        break
                    dom_r = (r.get("dominant_variant") or "").strip()
                    trend_r = (r.get("trend_class") or "").strip()
                    if tg not in recomputed:
                        values_ok = False
                        break
                    m_exp, h_exp, d_exp, dom_set, trend_exp = recomputed[tg]
                    if not (_float_equal(modern_total_r, m_exp, 1e-6) and _float_equal(historical_total_r, h_exp, 1e-6) and _float_equal(delta_r, d_exp, 1e-6)):
                        values_ok = False
                        break
                    if dom_set and dom_r not in dom_set:
                        values_ok = False
                        break
                    if trend_r != trend_exp:
                        values_ok = False
                        break
                ranked_values_ok = values_ok

    scores["ranked_terms_structure_and_sorting"] = 1.0 if ranked_structure_ok else 0.0
    scores["ranked_terms_values_correct"] = 1.0 if ranked_values_ok else 0.0

    notes_path = workspace / "outputs" / "meeting_notes.md"
    notes_text = _safe_read_text(notes_path)
    sections_present_ok = False
    sources_summary_ok = False
    method_ok = False
    ranked_findings_ok = False
    observations_ok = False
    action_items_ok = False

    if notes_text is not None:
        lines = notes_text.splitlines()
        sec_names = ["Objective", "Sources", "Method", "Ranked Findings", "Observations", "Action Items"]
        sec_indices = {}
        for name in sec_names:
            idx = _find_section_indices(lines, name)
            if idx is not None:
                sec_indices[name] = idx
        next_indices = {}
        for i, name in enumerate(sec_names):
            if name in sec_indices:
                next_idx = None
                for j in range(i+1, len(sec_names)):
                    if sec_names[j] in sec_indices:
                        next_idx = sec_indices[sec_names[j]]
                        break
                next_indices[name] = next_idx
        all_present = all(name in sec_indices for name in sec_names)
        non_empty = True
        blocks = {}
        if all_present:
            for name in sec_names:
                blk = _get_section_block(lines, sec_indices[name], next_indices.get(name))
                blocks[name] = blk
                content_has_text = any(line.strip() for line in blk)
                if not content_has_text:
                    non_empty = False
        sections_present_ok = all_present and non_empty

        if sections_present_ok:
            src_block = "\n".join(blocks["Sources"]).lower()
            mention_manifest = "outputs/sources.csv" in src_block
            works_all_mentioned = True
            for wid in work_ids:
                md = works_by_id[wid]
                title = (md.get("title") or "").strip()
                author = (md.get("author") or "").strip()
                year = (md.get("publication_year") or "").strip()
                gid = (md.get("gutenberg_id") or "").strip()
                if (wid.lower() not in src_block or
                    title.lower() not in src_block or
                    author.lower() not in src_block or
                    year.lower() not in src_block or
                    gid.lower() not in src_block):
                    works_all_mentioned = False
                    break
            sources_summary_ok = works_all_mentioned and mention_manifest

            method_lines = [ln.strip().lower() for ln in blocks["Method"] if ln.strip().startswith(("-", "*"))]
            def contains_any(line: str, keywords: List[str]) -> bool:
                return any(k in line for k in keywords)
            has_download = any(contains_any(ln, ["download", "gutenberg", "url"]) for ln in method_lines)
            has_header_footer = any(contains_any(ln, ["header", "footer"]) for ln in method_lines)
            has_tokenization = any(contains_any(ln, ["token", "whitespace"]) for ln in method_lines)
            has_exact_matching = any(contains_any(ln, ["exact", "whole-word", "whole word", "whole-phrase", "whole phrase"]) for ln in method_lines)
            has_normalization = any(contains_any(ln, ["rate per 10k", "per 10k", "10,000", "10000"]) for ln in method_lines)
            method_ok = has_download and has_header_footer and has_tokenization and has_exact_matching and has_normalization

            ranked_block_lines = [ln for ln in blocks["Ranked Findings"] if ln.strip()]
            top3_ok = False
            if ranked_rows is not None and ranked_structure_ok:
                top3 = ranked_rows[:3]
                def line_satisfies(line: str, canonical: str, dominant: str, delta_val: float, trend: str) -> bool:
                    l = line.lower()
                    if canonical.lower() not in l:
                        return False
                    if dominant.lower() not in l:
                        return False
                    if trend.lower() not in l:
                        return False
                    nums = [float(m.group().replace(",", "")) for m in re.finditer(r"[-+]?\d+(?:,\d{3})*(?:\.\d+)?", line)]
                    return any(abs(n - delta_val) <= 1e-2 for n in nums)
                flags = []
                for r in top3:
                    canonical = (r.get("canonical") or "").strip()
                    dominant = (r.get("dominant_variant") or "").strip()
                    try:
                        delta_val = float(str(r.get("delta_modern_minus_historical", "0")).strip())
                    except Exception:
                        delta_val = float("nan")
                    trend = (r.get("trend_class") or "").strip()
                    found = any(line_satisfies(ln, canonical, dominant, delta_val, trend) for ln in ranked_block_lines)
                    flags.append(found)
                top3_ok = all(flags)
            ranked_findings_ok = top3_ok

            obs_lines = [ln for ln in blocks["Observations"] if ln.strip().startswith(("-", "*"))]
            observations_ok = 3 <= len(obs_lines) <= 5

            act_lines = [ln for ln in blocks["Action Items"] if ln.strip().startswith(("-", "*"))]
            action_items_ok = len(act_lines) >= 4

    scores["meeting_notes_sections_present"] = 1.0 if sections_present_ok else 0.0
    scores["meeting_sources_summary_correct"] = 1.0 if sources_summary_ok else 0.0
    scores["meeting_method_covers_required_points"] = 1.0 if method_ok else 0.0
    scores["meeting_ranked_findings_top3_correct"] = 1.0 if ranked_findings_ok else 0.0
    scores["meeting_observations_count"] = 1.0 if observations_ok else 0.0
    scores["meeting_action_items_count"] = 1.0 if action_items_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()