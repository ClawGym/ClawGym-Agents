import json
import csv
import sys
import re
from pathlib import Path
from typing import Tuple, List, Dict, Any, Optional


def _read_text(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        text = path.read_text(encoding="utf-8")
        return text, None
    except Exception as e:
        return None, str(e)


def _load_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data, None
    except Exception as e:
        return None, str(e)


def _load_jsonl(path: Path) -> Tuple[Optional[List[dict]], Optional[str]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception as e:
        return None, str(e)
    items = []
    for idx, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            items.append(json.loads(line))
        except Exception as e:
            return None, f"Malformed JSONL at line {idx}: {e}"
    return items, None


def _read_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None, "CSV missing header"
            rows = [row for row in reader]
            return header, rows, None
    except Exception as e:
        return None, None, str(e)


def _normalize_domain(value: str) -> str:
    if not isinstance(value, str):
        return ""
    v = value.strip().lower()
    v = re.sub(r"^\w+://", "", v)
    v = v.split("/")[0]
    if v.startswith("www."):
        v = v[4:]
    return v


def _is_official_domain(domain: str, official_hints: List[str]) -> bool:
    d = _normalize_domain(domain)
    if not d:
        return False
    if d.endswith(".gov"):
        return True
    for hint in official_hints:
        h = _normalize_domain(hint)
        if not h:
            continue
        if d == h or d.endswith("." + h):
            return True
    return False


def _compute_official_count(evidence_list: List[dict], official_hints: List[str]) -> int:
    cnt = 0
    for ev in evidence_list:
        sd = ev.get("source_domain", "")
        if _is_official_domain(sd, official_hints):
            cnt += 1
    return cnt


def _unique_values(lst: List[Any]) -> List[Any]:
    seen = set()
    out = []
    for x in lst:
        key = json.dumps(x, sort_keys=True) if isinstance(x, (dict, list)) else x
        if key not in seen:
            seen.add(key)
            out.append(x)
    return out


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    # Expected grade keys order (must match insertion order)
    # Raw search validation keys for c1, c2, c3
    scores: Dict[str, float] = {}

    # Load claims with fallback to task-provided content to derive official domain hints
    claims_path = workspace / "input" / "claims.jsonl"
    claims_list, claims_err = _load_jsonl(claims_path)
    if claims_list is None:
        claims_list = [
            {
                "claim_id": "c1",
                "claim_text": "In 2017, Qualcomm filed an ITC complaint seeking to block imports of Apple iPhones over modem patents.",
                "entities": ["Qualcomm", "Apple"],
                "event_type": "ITC complaint",
                "year_hint": 2017,
                "official_domains_hint": ["itc.gov"],
            },
            {
                "claim_id": "c2",
                "claim_text": "In February 2018, Waymo and Uber settled their trade secrets case with Uber granting Waymo equity (not cash).",
                "entities": ["Waymo", "Uber"],
                "event_type": "settlement",
                "year_hint": 2018,
                "official_domains_hint": ["courtlistener.com", "cand.uscourts.gov"],
            },
            {
                "claim_id": "c3",
                "claim_text": "In April 2021, the U.S. Supreme Court held that Google's use of Java API declaring code was fair use in Oracle v. Google.",
                "entities": ["Google", "Oracle"],
                "event_type": "Supreme Court opinion",
                "year_hint": 2021,
                "official_domains_hint": ["supremecourt.gov", "courtlistener.com"],
            },
        ]
    claim_by_id: Dict[str, dict] = {c.get("claim_id"): c for c in claims_list if isinstance(c, dict) and "claim_id" in c}
    claim_ids = ["c1", "c2", "c3"]
    for cid in claim_ids:
        if cid not in claim_by_id:
            claim_by_id[cid] = {"claim_id": cid, "claim_text": "", "official_domains_hint": []}

    raw_results_by_claim: Dict[str, List[dict]] = {}
    raw_queries_by_claim: Dict[str, List[str]] = {}
    raw_has_official_candidate: Dict[str, bool] = {}

    # Validate raw search files: workspace/data/raw_search/c{claim_id}.json
    for cid in claim_ids:
        key_valid = f"raw_{cid}_file_valid_structure"
        key_min = f"raw_{cid}_min_results_and_queries"
        scores[key_valid] = 0.0
        scores[key_min] = 0.0

        expected_path = workspace / "workspace" / "data" / "raw_search" / f"{cid}.json"
        alt_path = workspace / "workspace" / "data" / "raw_search" / f"c{cid[-1]}.json"  # same as expected when cid is c1, c2, c3
        raw_path = expected_path if expected_path.exists() else (alt_path if alt_path.exists() else None)
        if raw_path is None:
            # Fallback: user may omit the outer 'workspace/' folder
            fb = workspace / "data" / "raw_search" / f"{cid}.json"
            raw_path = fb if fb.exists() else None

        data = None
        if raw_path is not None and raw_path.exists():
            data, _ = _load_json(raw_path)

        valid_structure = False
        min_results_ok = False
        queries_collected: List[str] = []
        has_official = False
        if isinstance(data, list) and len(data) > 0:
            required_fields = ["query_used", "title", "url", "source_domain", "snippet", "fetch_status"]
            all_items_ok = True
            urls = []
            queries = []
            hints = claim_by_id.get(cid, {}).get("official_domains_hint", []) or []
            for item in data:
                if not isinstance(item, dict):
                    all_items_ok = False
                    break
                for rf in required_fields:
                    if rf not in item:
                        all_items_ok = False
                        break
                    v = item.get(rf)
                    if not isinstance(v, str) or not v.strip():
                        all_items_ok = False
                        break
                if not all_items_ok:
                    break
                if "published_date" in item and item["published_date"] is not None and not isinstance(item["published_date"], str):
                    all_items_ok = False
                    break
                if "error_message" in item and item["error_message"] is not None and not isinstance(item["error_message"], str):
                    all_items_ok = False
                    break
                urls.append(item.get("url", ""))
                queries.append(item.get("query_used", ""))
                sd = item.get("source_domain", "")
                if _is_official_domain(sd, hints):
                    has_official = True
            if all_items_ok:
                valid_structure = True
                unique_urls = {u.strip() for u in urls if isinstance(u, str)}
                unique_queries = {q.strip() for q in queries if isinstance(q, str)}
                if len(unique_urls) >= 3 and len(unique_queries) >= 2:
                    min_results_ok = True
            queries_collected = list({q for q in queries if isinstance(q, str)})

        scores[key_valid] = 1.0 if valid_structure else 0.0
        scores[key_min] = 1.0 if min_results_ok else 0.0
        raw_results_by_claim[cid] = data if isinstance(data, list) else []
        raw_queries_by_claim[cid] = queries_collected
        raw_has_official_candidate[cid] = has_official

    # Evidence JSON checks
    evidence_path = workspace / "workspace" / "out" / "evidence.json"
    if not evidence_path.exists():
        # Fallback without outer 'workspace' directory
        evidence_path = workspace / "out" / "evidence.json"
    evidence_data, evidence_err = _load_json(evidence_path) if evidence_path.exists() else (None, "missing")
    scores["evidence_json_valid_structure"] = 0.0
    scores["evidence_contains_all_claims"] = 0.0

    evidence_by_claim: Dict[str, dict] = {}
    if isinstance(evidence_data, list) and len(evidence_data) > 0:
        structure_ok = True
        for item in evidence_data:
            if not isinstance(item, dict):
                structure_ok = False
                break
            for key in ["claim_id", "claim_text", "queries", "evidence", "classification", "rationale", "evidence_counts"]:
                if key not in item:
                    structure_ok = False
                    break
            if not structure_ok:
                break
            if not isinstance(item.get("queries"), list) or not isinstance(item.get("evidence"), list):
                structure_ok = False
                break
            if item.get("classification") not in {"supported", "refuted", "inconclusive"}:
                structure_ok = False
                break
            if not isinstance(item.get("rationale"), str) or not item.get("rationale").strip():
                structure_ok = False
                break
            ec = item.get("evidence_counts")
            if not isinstance(ec, dict) or "total" not in ec or "official" not in ec:
                structure_ok = False
                break
        if structure_ok:
            scores["evidence_json_valid_structure"] = 1.0

        present_ids = {item.get("claim_id") for item in evidence_data if isinstance(item, dict)}
        all_claims_present = all(cid in present_ids for cid in claim_ids)
        if all_claims_present:
            scores["evidence_contains_all_claims"] = 1.0

        for item in evidence_data:
            cid = item.get("claim_id")
            if isinstance(cid, str):
                evidence_by_claim[cid] = item

    # Evidence per-claim checks (queries count, classification+rationale, evidence counts consistency, support/refute requirements)
    for cid in claim_ids:
        key_queries = f"evidence_queries_count_{cid}"
        key_class = f"classification_and_rationale_{cid}"
        key_counts = f"evidence_counts_consistent_{cid}"
        key_support = f"evidence_supported_refuted_requirements_{cid}"
        scores[key_queries] = 0.0
        scores[key_class] = 0.0
        scores[key_counts] = 0.0
        scores[key_support] = 0.0

        item = evidence_by_claim.get(cid)
        if isinstance(item, dict):
            # queries >= 2 and should match raw queries if available
            queries = item.get("queries", [])
            if isinstance(queries, list) and len(_unique_values([q for q in queries if isinstance(q, str) and q.strip()])) >= 2:
                raw_qs = set(q for q in raw_queries_by_claim.get(cid, []))
                if raw_qs:
                    if all((isinstance(q, str) and q in raw_qs) for q in queries):
                        scores[key_queries] = 1.0
                else:
                    scores[key_queries] = 1.0

            # classification validity and rationale
            classification = item.get("classification")
            rationale_ok = isinstance(item.get("rationale"), str) and bool(item.get("rationale").strip())
            if classification in {"supported", "refuted", "inconclusive"} and rationale_ok:
                scores[key_class] = 1.0

            # evidence items fields and counts consistency
            ev_list = item.get("evidence", [])
            ev_items_ok = True
            for ev in ev_list:
                if not isinstance(ev, dict):
                    ev_items_ok = False
                    break
                for rf in ["query_used", "title", "url", "source_domain", "snippet"]:
                    if rf not in ev or not isinstance(ev.get(rf), str) or not ev.get(rf).strip():
                        ev_items_ok = False
                        break
                if not ev_items_ok:
                    break
                if "published_date" in ev and ev["published_date"] is not None and not isinstance(ev["published_date"], str):
                    ev_items_ok = False
                    break
            ec = item.get("evidence_counts", {}) if isinstance(item.get("evidence_counts"), dict) else {}
            total_ok = isinstance(ec.get("total"), int) and ec.get("total") == (len(ev_list) if isinstance(ev_list, list) else 0)
            hints = claim_by_id.get(cid, {}).get("official_domains_hint", []) or []
            official_calc = _compute_official_count(ev_list if isinstance(ev_list, list) else [], hints)
            official_ok = isinstance(ec.get("official"), int) and ec.get("official") == official_calc
            if ev_items_ok and total_ok and official_ok:
                scores[key_counts] = 1.0

            # supported/refuted requirements: at least two independent sources and at least one official when possible
            support_ok = True
            if classification in {"supported", "refuted"}:
                urls = [ev.get("url") for ev in ev_list if isinstance(ev, dict)]
                unique_urls = set(u for u in urls if isinstance(u, str) and u.strip())
                if len(unique_urls) < 2 or len(ev_list) < 2:
                    support_ok = False
                if raw_has_official_candidate.get(cid, False):
                    if official_calc < 1:
                        support_ok = False
            if support_ok:
                scores[key_support] = 1.0

    # Summary CSV checks
    summary_path = workspace / "workspace" / "out" / "summary.csv"
    if not summary_path.exists():
        summary_path = workspace / "out" / "summary.csv"
    header, rows, csv_err = _read_csv(summary_path) if summary_path.exists() else (None, None, "missing")
    scores["summary_csv_valid_structure"] = 0.0
    scores["summary_matches_evidence"] = 0.0
    if header is not None and rows is not None:
        expected_header = ["claim_id", "classification", "total_sources", "official_sources"]
        if header == expected_header:
            scores["summary_csv_valid_structure"] = 1.0
        if isinstance(evidence_data, list) and evidence_by_claim:
            ok = True
            row_map = {r.get("claim_id"): r for r in rows if isinstance(r, dict)}
            for cid in claim_ids:
                ev = evidence_by_claim.get(cid)
                r = row_map.get(cid)
                if not ev or not r:
                    ok = False
                    break
                if r.get("classification") != ev.get("classification"):
                    ok = False
                    break
                try:
                    total_sources = int(r.get("total_sources"))
                    official_sources = int(r.get("official_sources"))
                except Exception:
                    ok = False
                    break
                ec = ev.get("evidence_counts", {})
                if not isinstance(ec, dict):
                    ok = False
                    break
                if total_sources != ec.get("total") or official_sources != ec.get("official"):
                    ok = False
                    break
            if ok:
                scores["summary_matches_evidence"] = 1.0

    # Diagnostics log checks
    diag_path = workspace / "workspace" / "logs" / "search_diagnostics.txt"
    if not diag_path.exists():
        diag_path = workspace / "logs" / "search_diagnostics.txt"
    diag_text, diag_err = _read_text(diag_path) if diag_path.exists() else (None, "missing")
    scores["diagnostics_log_basic_content"] = 0.0
    scores["diagnostics_log_contains_queries_for_all_claims"] = 0.0
    if isinstance(diag_text, str):
        text_lower = diag_text.lower()
        has_stdout = ("stdout" in text_lower)
        has_stderr = ("stderr" in text_lower)
        has_exit = ("exit" in text_lower)
        has_cids = all(cid in diag_text for cid in claim_ids)
        if has_stdout and has_stderr and has_exit and has_cids:
            scores["diagnostics_log_basic_content"] = 1.0
        queries_ok = True
        if isinstance(evidence_data, list) and evidence_by_claim:
            for cid in claim_ids:
                ev = evidence_by_claim.get(cid, {})
                qlist = ev.get("queries", [])
                if isinstance(qlist, list) and qlist:
                    for q in qlist:
                        if isinstance(q, str) and q.strip():
                            if q not in diag_text:
                                queries_ok = False
                                break
                else:
                    queries_ok = False
                if not queries_ok:
                    break
        else:
            queries_ok = False
        if queries_ok:
            scores["diagnostics_log_contains_queries_for_all_claims"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()