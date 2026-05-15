import csv
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


ALLOWED_PATHS = [
    "/leadership",
    "/about/leadership",
    "/company/leadership",
    "/about/management",
    "/executive-team",
    "/our-leadership",
    "/who-we-are/leadership",
    "/management",
    "/team",
    "/about-us/leadership",
]


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    # Try standard JSON
    try:
        return json.loads(text)
    except Exception:
        pass
    # Try JSON Lines (one JSON object per line)
    try:
        items = []
        for line in text.splitlines():
            s = line.strip()
            if not s:
                continue
            items.append(json.loads(s))
        return items
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = [dict(row) for row in reader]
            return header, rows
    except Exception:
        return None, None


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_int(x: Any) -> Optional[int]:
    try:
        if isinstance(x, bool):
            return int(x)
        if isinstance(x, (int,)):
            return int(x)
        if isinstance(x, float):
            return int(x)
        if isinstance(x, str) and x.strip() != "":
            return int(float(x))
        return None
    except Exception:
        return None


def _parse_iso8601(ts: Any) -> bool:
    if not isinstance(ts, str) or not ts.strip():
        return False
    s = ts.strip()
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        datetime.fromisoformat(s2)
        return True
    except Exception:
        return False


def _last_segment_from_path(path: str) -> str:
    if not isinstance(path, str):
        return ""
    s = path.strip()
    if not s:
        return ""
    s = s.strip("/")
    if not s:
        return ""
    parts = [p for p in s.split("/") if p]
    if not parts:
        return ""
    seg = parts[-1]
    return seg


def _calc_tokens(criteria: Dict[str, Any]) -> Tuple[List[str], Dict[str, float]]:
    tokens = []
    weights: Dict[str, float] = {}
    if isinstance(criteria, dict):
        tr = criteria.get("target_roles")
        if isinstance(tr, list):
            for t in tr:
                if isinstance(t, str):
                    tokens.append(t)
        w = criteria.get("weights")
        if isinstance(w, dict):
            for k, v in w.items():
                if isinstance(k, str) and isinstance(v, (int, float)):
                    weights[k] = float(v)
                    if k not in tokens:
                        tokens.append(k)
    # Unique tokens preserving order
    seen = set()
    uniq_tokens = []
    for t in tokens:
        if t not in seen:
            uniq_tokens.append(t)
            seen.add(t)
    return uniq_tokens, weights


def _title_best_token_weight(title: str, tokens: List[str], weights: Dict[str, float]) -> Tuple[Optional[str], Optional[float]]:
    if not isinstance(title, str):
        return None, None
    t_low = title.lower()
    best_token = None
    best_weight = None
    for tok in tokens:
        if not isinstance(tok, str):
            continue
        if tok.lower() in t_low:
            w = weights.get(tok)
            if w is None:
                w = 0.0
            if best_weight is None or w > best_weight:
                best_weight = w
                best_token = tok
    return best_token, best_weight


def _is_bullet_line(line: str) -> bool:
    s = line.strip()
    return bool(re.match(r"^(\-|\*|\d+\.)\s+", s))


def _find_section_indices(lines: List[str], label: str) -> List[int]:
    indices = []
    pattern = re.compile(rf"^\s*#*\s*{re.escape(label)}\s*:?\s*$", re.IGNORECASE)
    for idx, line in enumerate(lines):
        if pattern.match(line):
            indices.append(idx)
    return indices


def _get_section_text(text: str, label: str, all_labels: List[str]) -> Optional[str]:
    lines = text.splitlines()
    indices = _find_section_indices(lines, label)
    if not indices:
        alt_indices = []
        pattern = re.compile(rf"^\s*{re.escape(label)}\s*:.*$", re.IGNORECASE)
        for idx, line in enumerate(lines):
            if pattern.match(line):
                alt_indices.append(idx)
        indices = alt_indices
    if not indices:
        return None
    start = indices[0]
    end = len(lines)
    for next_label in all_labels:
        if next_label.lower() == label.lower():
            continue
        next_indices = _find_section_indices(lines, next_label)
        if not next_indices:
            patt = re.compile(rf"^\s*{re.escape(next_label)}\s*:.*$", re.IGNORECASE)
            for idx, line in enumerate(lines):
                if patt.match(line):
                    next_indices.append(idx)
        for ni in next_indices:
            if ni > start and ni < end:
                end = ni
    section_text = "\n".join(lines[start:end])
    return section_text


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "manifest_exists_and_valid_json": 0.0,
        "domains_covered_in_manifest": 0.0,
        "manifest_domains_from_input": 0.0,
        "attempted_paths_allowed": 0.0,
        "https_used_for_final_url": 0.0,
        "attempts_per_domain_limit": 0.0,
        "saved_files_integrity": 0.0,
        "parsed_csv_structure": 0.0,
        "parsed_rows_valid_references": 0.0,
        "parsed_rows_titles_have_tokens": 0.0,
        "parsed_dedup_within_domain": 0.0,
        "shortlist_structure": 0.0,
        "shortlist_scores_match_weights": 0.0,
        "shortlist_sorting_and_ranks": 0.0,
        "meeting_notes_sections_present": 0.0,
        "meeting_notes_stats_consistency": 0.0,
        "meeting_notes_top5_consistency": 0.0,
        "action_items_count": 0.0,
    }

    # Load inputs (used only for cross-file checks; do not award points for presence)
    targets_csv = workspace / "input" / "targets.csv"
    criteria_json = workspace / "input" / "ranking_criteria.json"

    header_targets, rows_targets = _load_csv_dicts(targets_csv)
    criteria = _load_json(criteria_json)
    target_domains: List[str] = []
    if header_targets and rows_targets is not None and isinstance(criteria, dict):
        if set(["company_name", "domain", "industry"]).issubset(set([h for h in header_targets])):
            target_domains = [r.get("domain", "").strip() for r in rows_targets if isinstance(r.get("domain", ""), str) and r.get("domain", "").strip()]

    tokens, weights = _calc_tokens(criteria if isinstance(criteria, dict) else {})

    # Load manifest
    manifest_path = workspace / "workspace" / "logs" / "download_manifest.json"
    manifest = _load_json(manifest_path)
    manifest_entries: List[Dict[str, Any]] = []
    if isinstance(manifest, list):
        manifest_entries = [m for m in manifest if isinstance(m, dict)]
        if len(manifest_entries) == len(manifest):
            basic_ok_count = 0
            for m in manifest_entries:
                domain_ok = isinstance(m.get("domain"), str) and m.get("domain") != ""
                attempted_ok = isinstance(m.get("attempted_path"), str) and m.get("attempted_path") != ""
                http_status_ok = _safe_int(m.get("http_status")) is not None
                bytes_field = m.get("bytes", None)
                bytes_ok = (bytes_field is None) or (_safe_int(bytes_field) is not None and _safe_int(bytes_field) >= 0)
                sha = m.get("sha256", None)
                sha_ok = (sha is None) or (isinstance(sha, str) and bool(re.fullmatch(r"[0-9a-fA-F]{64}", sha)))
                ts_ok = _parse_iso8601(m.get("timestamp"))
                basic_ok_count += 1 if (domain_ok and attempted_ok and http_status_ok and bytes_ok and sha_ok and ts_ok) else 0
            if basic_ok_count == len(manifest_entries) and len(manifest_entries) > 0:
                scores["manifest_exists_and_valid_json"] = 1.0
            else:
                scores["manifest_exists_and_valid_json"] = 0.0
        else:
            scores["manifest_exists_and_valid_json"] = 0.0
    else:
        scores["manifest_exists_and_valid_json"] = 0.0

    # Manifest coverage and constraints
    if manifest_entries:
        # domains_covered_in_manifest: fraction of input domains present at least once
        if target_domains:
            manifest_domains = set(m.get("domain") for m in manifest_entries if isinstance(m.get("domain"), str))
            covered = sum(1 for d in set(target_domains) if d in manifest_domains)
            scores["domains_covered_in_manifest"] = covered / max(1, len(set(target_domains)))
        else:
            scores["domains_covered_in_manifest"] = 0.0

        # manifest_domains_from_input: fraction of entries whose domain is from input
        if target_domains:
            cnt_ok = sum(1 for m in manifest_entries if m.get("domain") in set(target_domains))
            scores["manifest_domains_from_input"] = cnt_ok / max(1, len(manifest_entries))
        else:
            scores["manifest_domains_from_input"] = 0.0

        # attempted_paths_allowed: fraction of entries whose attempted_path in allowed list
        cnt_allowed = sum(1 for m in manifest_entries if isinstance(m.get("attempted_path"), str) and m.get("attempted_path") in ALLOWED_PATHS)
        scores["attempted_paths_allowed"] = cnt_allowed / max(1, len(manifest_entries))

        # https_used_for_final_url: fraction with final_url present that start with https://
        final_urls = [m.get("final_url") for m in manifest_entries if m.get("final_url") is not None]
        if final_urls:
            cnt_https = sum(1 for u in final_urls if isinstance(u, str) and u.lower().startswith("https://"))
            scores["https_used_for_final_url"] = cnt_https / max(1, len(final_urls))
        else:
            scores["https_used_for_final_url"] = 0.0  # No final_url present; do not award

        # attempts_per_domain_limit: proportion of domains that have attempts <= 10
        per_domain: Dict[str, int] = {}
        for m in manifest_entries:
            d = m.get("domain")
            if isinstance(d, str) and d:
                per_domain[d] = per_domain.get(d, 0) + 1
        if per_domain:
            cnt_ok = sum(1 for d, n in per_domain.items() if n <= 10)
            scores["attempts_per_domain_limit"] = cnt_ok / max(1, len(per_domain))
        else:
            scores["attempts_per_domain_limit"] = 0.0

        # saved_files_integrity: for entries with saved_path, verify integrity and placement
        saved_entries = [m for m in manifest_entries if isinstance(m.get("saved_path"), str) and m.get("saved_path").strip() != ""]
        if saved_entries:
            ok = 0
            for m in saved_entries:
                sp = m.get("saved_path")
                d = m.get("domain")
                attempted_path = m.get("attempted_path")
                sp_path = None
                placed_ok = False
                file_ok = False
                bytes_ok = False
                sha_ok = False
                name_ok = False
                try:
                    sp_path = workspace / sp
                except Exception:
                    sp_path = None
                if isinstance(sp_path, Path):
                    try:
                        placed_ok = (
                            sp_path.suffix.lower() == ".html"
                            and "workspace" in sp_path.parts
                            and "raw" in sp_path.parts
                            and isinstance(d, str)
                            and d in sp_path.parts
                        )
                    except Exception:
                        placed_ok = False
                    if sp_path.is_file():
                        try:
                            data = sp_path.read_bytes()
                            file_ok = True
                            b = _safe_int(m.get("bytes"))
                            if b is None:
                                bytes_ok = True
                            else:
                                bytes_ok = (b == len(data))
                            sha_field = m.get("sha256")
                            if isinstance(sha_field, str) and re.fullmatch(r"[0-9a-fA-F]{64}", sha_field or ""):
                                sha_ok = (_sha256_hex(data).lower() == sha_field.lower())
                            else:
                                sha_ok = False
                        except Exception:
                            file_ok = False
                    if isinstance(attempted_path, str):
                        last_seg = _last_segment_from_path(attempted_path)
                        try:
                            stem = sp_path.name.lower()
                        except Exception:
                            stem = ""
                        name_ok = (last_seg.lower() in stem) if last_seg else True
                if placed_ok and file_ok and bytes_ok and sha_ok and name_ok:
                    ok += 1
            scores["saved_files_integrity"] = ok / max(1, len(saved_entries))
        else:
            scores["saved_files_integrity"] = 0.0

    # Parsed candidates CSV checks
    parsed_csv_path = workspace / "workspace" / "parsed" / "executives_raw.csv"
    parsed_header, parsed_rows = _load_csv_dicts(parsed_csv_path)
    if parsed_header is not None and parsed_rows is not None:
        expected_headers = ["domain", "source_path", "candidate_name", "title", "context_snippet"]
        scores["parsed_csv_structure"] = 1.0 if parsed_header == expected_headers and len(parsed_rows) >= 0 else 0.0

        if parsed_rows:
            valid_ref_count = 0
            valid_token_count = 0
            for r in parsed_rows:
                domain = r.get("domain", "")
                src = r.get("source_path", "")
                title = r.get("title", "")
                cname = r.get("candidate_name", "")
                domain_ok = domain in set(target_domains) if target_domains else (isinstance(domain, str) and bool(domain.strip()))
                src_ok = False
                try:
                    src_ok = (workspace / src).is_file()
                except Exception:
                    src_ok = False
                name_ok = isinstance(cname, str) and cname.strip() != ""
                tok, _ = _title_best_token_weight(title or "", tokens, weights)
                token_ok = tok is not None
                if domain_ok and src_ok and name_ok:
                    valid_ref_count += 1
                if token_ok:
                    valid_token_count += 1
            scores["parsed_rows_valid_references"] = valid_ref_count / max(1, len(parsed_rows))
            scores["parsed_rows_titles_have_tokens"] = valid_token_count / max(1, len(parsed_rows))
            # Dedup within domain by (candidate_name, title), case-insensitive trimmed
            seen_pairs = set()
            for r in parsed_rows:
                d = (r.get("domain", "") or "").strip().lower()
                cn = (r.get("candidate_name", "") or "").strip().lower()
                tt = (r.get("title", "") or "").strip().lower()
                seen_pairs.add((d, cn, tt))
            if len(parsed_rows) > 0:
                scores["parsed_dedup_within_domain"] = len(seen_pairs) / len(parsed_rows)
            else:
                scores["parsed_dedup_within_domain"] = 0.0
        else:
            scores["parsed_rows_valid_references"] = 0.0
            scores["parsed_rows_titles_have_tokens"] = 0.0
            scores["parsed_dedup_within_domain"] = 0.0
    else:
        scores["parsed_csv_structure"] = 0.0
        scores["parsed_rows_valid_references"] = 0.0
        scores["parsed_rows_titles_have_tokens"] = 0.0
        scores["parsed_dedup_within_domain"] = 0.0

    # Shortlist CSV checks
    shortlist_path = workspace / "workspace" / "reports" / "executive_shortlist.csv"
    shortlist_header, shortlist_rows = _load_csv_dicts(shortlist_path)
    if shortlist_header is not None and shortlist_rows is not None:
        expected_headers = ["rank", "candidate_name", "normalized_title", "source_domain", "score", "source_path"]
        scores["shortlist_structure"] = 1.0 if shortlist_header == expected_headers and len(shortlist_rows) >= 0 else 0.0

        if shortlist_rows:
            score_match = 0
            for r in shortlist_rows:
                title = r.get("normalized_title", "")
                score_field = r.get("score", "")
                _, best_w = _title_best_token_weight(title or "", tokens, weights)
                try:
                    s_val = float(score_field)
                except Exception:
                    s_val = None
                if best_w is not None and s_val is not None and abs(s_val - best_w) < 1e-9:
                    score_match += 1
            scores["shortlist_scores_match_weights"] = score_match / max(1, len(shortlist_rows))
        else:
            scores["shortlist_scores_match_weights"] = 0.0

        if shortlist_rows:
            def row_key(r: Dict[str, str]) -> Tuple[float, str, str]:
                try:
                    sc = float(r.get("score", "0"))
                except Exception:
                    sc = float("-inf")
                name = r.get("candidate_name", "") or ""
                dom = r.get("source_domain", "") or ""
                return (-sc, name, dom)

            sorted_rows = sorted(shortlist_rows, key=row_key)
            sorting_ok = all(sorted_rows[i] == shortlist_rows[i] for i in range(len(shortlist_rows)))
            rank_ok = True
            for i, r in enumerate(shortlist_rows, start=1):
                try:
                    rank_val = int(float(r.get("rank", "0")))
                except Exception:
                    rank_val = None
                if rank_val != i:
                    rank_ok = False
                    break
            scores["shortlist_sorting_and_ranks"] = 1.0 if (sorting_ok and rank_ok) else 0.0
        else:
            scores["shortlist_sorting_and_ranks"] = 0.0
    else:
        scores["shortlist_structure"] = 0.0
        scores["shortlist_scores_match_weights"] = 0.0
        scores["shortlist_sorting_and_ranks"] = 0.0

    # Meeting notes checks
    meeting_notes_path = workspace / "workspace" / "reports" / "meeting_notes.md"
    meeting_text = _read_text(meeting_notes_path)
    if isinstance(meeting_text, str):
        labels = ["Overview", "Stats", "Top 5 Candidates", "Action Items"]
        sections_found = 0
        sections_text: Dict[str, str] = {}
        for lab in labels:
            sec = _get_section_text(meeting_text, lab, labels)
            if isinstance(sec, str) and sec.strip():
                sections_found += 1
                sections_text[lab] = sec
        scores["meeting_notes_sections_present"] = sections_found / len(labels)

        action_text = sections_text.get("Action Items")
        if action_text:
            bullets = [ln for ln in action_text.splitlines() if _is_bullet_line(ln)]
            scores["action_items_count"] = 1.0 if len(bullets) >= 3 else (len(bullets) / 3.0 if bullets else 0.0)
        else:
            scores["action_items_count"] = 0.0

        stats_text = sections_text.get("Stats", "")
        if isinstance(manifest_entries, list) and manifest_entries:
            domains_processed = len(set([m.get("domain") for m in manifest_entries if isinstance(m.get("domain"), str)]))
            attempted_pages = len(manifest_entries)
            succ = 0
            for m in manifest_entries:
                sp = m.get("saved_path")
                if isinstance(sp, str) and sp.strip():
                    sp_path = workspace / sp
                    if sp_path.is_file():
                        try:
                            data = sp_path.read_bytes()
                            sha_field = m.get("sha256")
                            if isinstance(sha_field, str) and _sha256_hex(data).lower() == sha_field.lower():
                                succ += 1
                        except Exception:
                            pass
            unique_candidates = len(parsed_rows) if parsed_rows else 0
        else:
            domains_processed = 0
            attempted_pages = 0
            succ = 0
            unique_candidates = len(parsed_rows) if parsed_rows else 0

        def _find_stat_number(text: str, keywords: List[str]) -> Optional[int]:
            found_val = None
            for line in text.splitlines():
                if all(kw.lower() in line.lower() for kw in keywords):
                    nums = re.findall(r"\d+", line)
                    if nums:
                        vals = [int(n) for n in nums]
                        found_val = max(vals)
                        break
            return found_val

        dom_val = _find_stat_number(stats_text, ["domain"])
        att_val = _find_stat_number(stats_text, ["attempt"])
        succ_val = _find_stat_number(stats_text, ["download"])
        cand_val = _find_stat_number(stats_text, ["candidate"])
        stat_checks = 0
        stat_total = 4
        if dom_val is not None and dom_val == domains_processed:
            stat_checks += 1
        if att_val is not None and att_val == attempted_pages:
            stat_checks += 1
        if succ_val is not None and succ_val == succ:
            stat_checks += 1
        if cand_val is not None and cand_val == unique_candidates:
            stat_checks += 1
        scores["meeting_notes_stats_consistency"] = stat_checks / stat_total

        top5_text = sections_text.get("Top 5 Candidates", "")
        top5_score = 0.0
        if shortlist_rows and isinstance(top5_text, str) and top5_text.strip():
            top_n = min(5, len(shortlist_rows))
            ok_count = 0
            for i in range(top_n):
                row = shortlist_rows[i]
                name = (row.get("candidate_name") or "").strip()
                domain = (row.get("source_domain") or "").strip()
                score_val = row.get("score")
                try:
                    score_str = str(int(float(score_val)))
                except Exception:
                    score_str = str(score_val) if score_val is not None else ""
                has_name = name and (name in top5_text)
                has_domain = domain and (domain in top5_text)
                has_score = score_str and (score_str in top5_text)
                if has_name and has_domain and has_score:
                    ok_count += 1
            top5_score = ok_count / max(1, top_n)
        else:
            top5_score = 0.0
        scores["meeting_notes_top5_consistency"] = top5_score

    else:
        scores["meeting_notes_sections_present"] = 0.0
        scores["action_items_count"] = 0.0
        scores["meeting_notes_stats_consistency"] = 0.0
        scores["meeting_notes_top5_consistency"] = 0.0

    # Clamp scores to [0,1]
    for k, v in list(scores.items()):
        try:
            fv = float(v)
        except Exception:
            fv = 0.0
        fv = max(0.0, min(1.0, fv))
        scores[k] = fv

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()