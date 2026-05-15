import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_read_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            rows = [dict({k: (v if v is not None else "") for k, v in r.items()}) for r in reader]
            return headers, rows
    except Exception:
        return None, None


def _safe_read_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        objs = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                objs.append(json.loads(line))
        return objs
    except Exception:
        return None


def _tokenize_words(text: str) -> List[str]:
    return re.findall(r"\b\w+\b", text.lower())


def _count_words(text: str) -> int:
    return len(_tokenize_words(text))


def _parse_iso8601(s: str) -> bool:
    if not isinstance(s, str):
        return False
    s = s.strip()
    if not s:
        return False
    try:
        # Handle 'Z'
        if s.endswith("Z"):
            s_mod = s[:-1] + "+00:00"
            datetime.fromisoformat(s_mod)
        else:
            datetime.fromisoformat(s)
        return True
    except Exception:
        # Try a couple of common formats
        fmts = [
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ]
        for fmt in fmts:
            try:
                datetime.strptime(s, fmt)
                return True
            except Exception:
                continue
        return False


def _parse_simple_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML parser for the known structure:
    - top-level keys
      - lists using '- '
      - nested map for max_word_counts
    """
    text = _safe_read_text(path)
    if text is None:
        return None
    data: Dict[str, Any] = {}
    current_key: Optional[str] = None
    in_list = False
    in_map_key: Optional[str] = None
    lines = text.splitlines()
    for raw_line in lines:
        line = raw_line.strip("\n")
        if not line.strip():
            continue
        # Ignore comments
        if line.strip().startswith("#"):
            continue
        # Detect indentation level
        leading_spaces = len(raw_line) - len(raw_line.lstrip(" "))
        # Top-level key
        if leading_spaces == 0 and ":" in line:
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            if val == "":
                # Start of a block (list or map)
                if key == "max_word_counts":
                    data[key] = {}
                    current_key = key
                    in_list = False
                    in_map_key = key
                else:
                    data[key] = []
                    current_key = key
                    in_list = True
                    in_map_key = None
            else:
                # Scalar value
                # Strip possible quotes
                sval = val.strip()
                if (sval.startswith('"') and sval.endswith('"')) or (sval.startswith("'") and sval.endswith("'")):
                    sval = sval[1:-1]
                data[key] = sval
                current_key = None
                in_list = False
                in_map_key = None
            continue
        # Nested content
        if in_list and current_key:
            # Expect list items like "- value"
            stripped = raw_line.lstrip(" ")
            if stripped.startswith("- "):
                item = stripped[2:].strip()
                # Strip quotes if present
                if (item.startswith('"') and item.endswith('"')) or (item.startswith("'") and item.endswith("'")):
                    item = item[1:-1]
                data[current_key].append(item)
            else:
                # malformed
                return None
            continue
        if in_map_key:
            # Expect "  key: value"
            stripped = raw_line.lstrip(" ")
            if ":" not in stripped:
                return None
            k2, v2 = stripped.split(":", 1)
            k2 = k2.strip()
            v2 = v2.strip()
            # Convert to int if possible
            try:
                v2_parsed: Any = int(v2)
            except Exception:
                # Strip quotes if present
                if (v2.startswith('"') and v2.endswith('"')) or (v2.startswith("'") and v2.endswith("'")):
                    v2_parsed = v2[1:-1]
                else:
                    v2_parsed = v2
            data[in_map_key][k2] = v2_parsed
            continue
        # If we reach here, structure is not as expected
        return None
    return data


def _load_claims(path: Path) -> Optional[List[Dict[str, str]]]:
    headers, rows = _safe_read_csv(path)
    if headers is None or rows is None:
        return None
    # Expect columns id,topic,claim
    # We will normalize headers to lower
    lower_headers = [h.lower() for h in headers]
    required = ["id", "topic", "claim"]
    if not all(r in lower_headers for r in required):
        # Try to normalize rows by lower keys
        # If missing, fail
        return None
    # Normalize rows to lower-case keys
    norm_rows: List[Dict[str, str]] = []
    for r in rows:
        d: Dict[str, str] = {}
        for k, v in r.items():
            d[k.lower()] = (v or "").strip()
        # Ensure required keys exist
        if not all(k in d for k in required):
            return None
        norm_rows.append({"id": d["id"], "topic": d["topic"], "claim": d["claim"]})
    return norm_rows


def _load_allowed_domains(path: Path) -> Optional[List[str]]:
    text = _safe_read_text(path)
    if text is None:
        return None
    pats = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        # Ignore comments
        if s.startswith("#"):
            continue
        pats.append(s.lower())
    return pats


def _domain_matches_patterns(domain: str, patterns: List[str]) -> bool:
    d = (domain or "").strip().lower()
    if not d:
        return False
    for p in patterns:
        p = p.strip().lower()
        if not p:
            continue
        # Substring or suffix match acceptable
        if p in d:
            return True
        if d.endswith("." + p) or d.endswith(p):
            return True
    return False


def _email_contains_phrases(text: str, phrases: List[str]) -> bool:
    t = text.lower()
    for p in phrases:
        if p.lower() not in t:
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "queries_structure_and_counts": 0.0,
        "sources_structure_and_counts": 0.0,
        "sources_field_validity": 0.0,
        "rationales_distinct_for_shared_urls": 0.0,
        "summary_per_claim_and_match": 0.0,
        "invite_email_requirements": 0.0,
        "mod_dm_requirements": 0.0,
        "validator_script_exists": 0.0,
        "validation_report_exists_and_has_keys": 0.0,
    }

    # Load inputs
    claims_path = workspace / "input" / "claims.csv"
    allowed_domains_path = workspace / "input" / "allowed_domains.txt"
    email_reqs_path = workspace / "input" / "email_requirements.yaml"

    claims = _load_claims(claims_path)
    allowed_patterns = _load_allowed_domains(allowed_domains_path)
    email_reqs = _parse_simple_yaml(email_reqs_path)

    claim_ids: List[str] = []
    claim_texts: Dict[str, str] = {}
    if claims is not None:
        for c in claims:
            cid = c.get("id", "").strip()
            claim_ids.append(cid)
            claim_texts[cid] = c.get("claim", "").strip()

    # Queries checks
    queries_path = workspace / "logs" / "search_queries.csv"
    q_headers, q_rows = _safe_read_csv(queries_path)
    queries_ok = False
    queries_counts_ok = False
    if q_headers is not None and q_rows is not None and claims is not None:
        lower_headers = [h.strip().lower() for h in q_headers]
        required_cols = {"claim_id", "query"}
        if required_cols.issubset(set(lower_headers)):
            # Build counts
            per_claim_counts: Dict[str, int] = {cid: 0 for cid in claim_ids}
            nonempty_fields_ok = True
            for row in q_rows:
                # Normalize row keys
                row_norm = {k.lower(): (v or "").strip() for k, v in row.items()}
                cid = row_norm.get("claim_id", "")
                qry = row_norm.get("query", "")
                if cid in per_claim_counts:
                    if qry:
                        per_claim_counts[cid] += 1
                # Check non-empty fields
                if not cid or not qry:
                    nonempty_fields_ok = False
            if nonempty_fields_ok:
                queries_ok = True
            # Check ≥2 per claim
            if all(per_claim_counts.get(cid, 0) >= 2 for cid in claim_ids):
                queries_counts_ok = True
    scores["queries_structure_and_counts"] = 1.0 if (queries_ok and queries_counts_ok) else 0.0

    # Sources checks
    sources_path = workspace / "data" / "factcheck_sources.jsonl"
    sources = _safe_read_jsonl(sources_path)
    sources_structure_ok = False
    sources_counts_ok = False
    sources_fields_ok = False
    rationales_distinct_ok = False
    if sources is not None and claims is not None:
        # Validate each record fields
        required_fields = ["claim_id", "query_used", "source_title", "source_domain", "url", "publisher", "accessed_utc", "rationale"]
        fields_ok = True
        for obj in sources:
            # All required keys present and non-empty strings
            for k in required_fields:
                if k not in obj:
                    fields_ok = False
                    break
                v = obj.get(k)
                if not isinstance(v, str) or not v.strip():
                    fields_ok = False
                    break
            if not fields_ok:
                break
            # url starts with http
            if not obj["url"].strip().lower().startswith("http"):
                fields_ok = False
                break
            # accessed_utc parses
            if not _parse_iso8601(obj["accessed_utc"].strip()):
                fields_ok = False
                break
            # rationale length 30-400
            rl = len(obj["rationale"].strip())
            if not (30 <= rl <= 400):
                fields_ok = False
                break
        if fields_ok:
            sources_structure_ok = True
            sources_fields_ok = True

        # Counts per claim (≥2 per claim in input)
        if sources_structure_ok:
            per_claim_srcs: Dict[str, int] = {cid: 0 for cid in claim_ids}
            for obj in sources:
                cid = str(obj.get("claim_id", "")).strip()
                if cid in per_claim_srcs:
                    per_claim_srcs[cid] += 1
            if all(per_claim_srcs.get(cid, 0) >= 2 for cid in claim_ids):
                sources_counts_ok = True

        # Rationales distinct for shared URLs across claims
        if sources_structure_ok:
            url_to_entries: Dict[str, List[Dict[str, Any]]] = {}
            for obj in sources:
                url = obj.get("url", "").strip()
                if not url:
                    continue
                url_to_entries.setdefault(url, []).append(obj)
            distinct_ok = True
            for url, entries in url_to_entries.items():
                # Group by claim_id
                claim_to_rationales: Dict[str, List[str]] = {}
                for e in entries:
                    cid = str(e.get("claim_id", "")).strip()
                    r = str(e.get("rationale", "")).strip().lower()
                    claim_to_rationales.setdefault(cid, []).append(r)
                # If more than one distinct claim id present for this url, ensure rationales across claim_ids differ
                if len([k for k in claim_to_rationales.keys() if k]) >= 2:
                    reps = [r_list[0] if r_list else "" for r_list in claim_to_rationales.values()]
                    if len(set(reps)) != len(reps):
                        distinct_ok = False
                        break
            rationales_distinct_ok = distinct_ok

    scores["sources_structure_and_counts"] = 1.0 if (sources_structure_ok and sources_counts_ok) else 0.0
    scores["sources_field_validity"] = 1.0 if sources_fields_ok else 0.0
    scores["rationales_distinct_for_shared_urls"] = 1.0 if rationales_distinct_ok else 0.0

    # Summary checks
    summary_path = workspace / "reports" / "summary.md"
    summary_text = _safe_read_text(summary_path)
    summary_ok = False
    domains_match_ok = False
    credible_match_ok = False
    if summary_text is not None and claims is not None and sources is not None:
        # Compute domains per claim in insertion order
        domains_per_claim: Dict[str, List[str]] = {}
        for cid in claim_ids:
            domains_per_claim[cid] = []
        for obj in sources:
            cid = str(obj.get("claim_id", "")).strip()
            dom = str(obj.get("source_domain", "")).strip()
            if cid in domains_per_claim and dom:
                if dom not in domains_per_claim[cid]:
                    domains_per_claim[cid].append(dom)
        # Compute credible per claim
        allowed = allowed_patterns if allowed_patterns is not None else []
        credible_per_claim: Dict[str, bool] = {}
        for cid in claim_ids:
            doms = domains_per_claim.get(cid, [])
            cred = any(_domain_matches_patterns(d, allowed) for d in doms)
            credible_per_claim[cid] = cred

        lines = [ln.strip() for ln in summary_text.splitlines() if ln.strip() != ""]
        expected_line_count = 3 * len(claim_ids)
        if len(lines) == expected_line_count:
            structure_ok = True
            domains_ok = True
            credible_ok = True
            for i, cid in enumerate(claim_ids):
                claim_line = lines[3 * i + 0]
                domains_line = lines[3 * i + 1]
                credible_line = lines[3 * i + 2]
                # Check claim line exact
                expected_claim = f"Claim {cid}: {claim_texts.get(cid, '')}"
                if claim_line != expected_claim:
                    structure_ok = False
                    break
                # Check domains line format and content (set equality, uniqueness)
                if not domains_line.startswith("Domains: "):
                    structure_ok = False
                    break
                # Parse listed domains
                listed = domains_line[len("Domains: "):].strip()
                if listed == "":
                    listed_domains: List[str] = []
                else:
                    listed_domains = [s.strip() for s in listed.split(",")]
                # Ensure uniqueness in listed_domains
                if len(listed_domains) != len(set(listed_domains)):
                    domains_ok = False
                    break
                # Compare sets with computed
                computed_doms = domains_per_claim.get(cid, [])
                if set(listed_domains) != set(computed_doms):
                    domains_ok = False
                    break
                # Check credible line
                if not credible_line.startswith("Credible: "):
                    structure_ok = False
                    break
                listed_cred = credible_line[len("Credible: "):].strip()
                expected_cred = "Yes" if credible_per_claim.get(cid, False) else "No"
                if listed_cred != expected_cred:
                    credible_ok = False
                    break
            summary_ok = structure_ok
            domains_match_ok = domains_ok
            credible_match_ok = credible_ok

    scores["summary_per_claim_and_match"] = 1.0 if (summary_ok and domains_match_ok and credible_match_ok) else 0.0

    # Outreach invite email checks
    invite_path = workspace / "outreach" / "invite_email.md"
    invite_text = _safe_read_text(invite_path)
    invite_ok = False
    if invite_text is not None and email_reqs is not None:
        lines = invite_text.splitlines()
        if len(lines) >= 1:
            first_line = lines[0].strip()
            subj_prefix = str(email_reqs.get("subject_prefix", "")).strip()
            required_phrases = email_reqs.get("required_phrases", [])
            max_invite = None
            if isinstance(email_reqs.get("max_word_counts"), dict):
                max_invite = email_reqs["max_word_counts"].get("invite")
            # Validate subject line
            subj_ok = first_line.startswith("Subject: ") and (subj_prefix in first_line if subj_prefix else True)
            # Word count
            wc = _count_words(invite_text)
            wc_ok = False
            try:
                wc_ok = (max_invite is None) or (int(max_invite) >= wc)
            except Exception:
                wc_ok = False
            # Required phrases present (case-insensitive substring)
            phrases_ok = True
            if isinstance(required_phrases, list):
                phrases_ok = _email_contains_phrases(invite_text, required_phrases)
            else:
                phrases_ok = False
            invite_ok = subj_ok and wc_ok and phrases_ok
    scores["invite_email_requirements"] = 1.0 if invite_ok else 0.0

    # Moderator DM checks
    dm_path = workspace / "outreach" / "mod_dm.txt"
    dm_text = _safe_read_text(dm_path)
    dm_ok = False
    if dm_text is not None and email_reqs is not None:
        max_dm = None
        if isinstance(email_reqs.get("max_word_counts"), dict):
            max_dm = email_reqs["max_word_counts"].get("mod_dm")
        dm_required = email_reqs.get("dm_required_keywords", [])
        wc = _count_words(dm_text)
        wc_ok = False
        try:
            wc_ok = (max_dm is None) or (int(max_dm) >= wc)
        except Exception:
            wc_ok = False
        # word-level presence
        tokens = set(_tokenize_words(dm_text))
        keywords_ok = True
        if isinstance(dm_required, list):
            for kw in dm_required:
                if kw.lower() not in tokens:
                    keywords_ok = False
                    break
        else:
            keywords_ok = False
        dm_ok = wc_ok and keywords_ok
    scores["mod_dm_requirements"] = 1.0 if dm_ok else 0.0

    # Validator script existence
    validator_script = workspace / "tests" / "validate_outputs.py"
    scores["validator_script_exists"] = 1.0 if validator_script.exists() and validator_script.is_file() else 0.0

    # Validation report exists and has keys
    validation_report_path = workspace / "reports" / "validation_report.json"
    vr = _safe_load_json(validation_report_path) if validation_report_path.exists() else None
    vr_ok = False
    if isinstance(vr, dict) and claims is not None:
        # Required keys
        required_bool_keys = ["queries_ok", "sources_ok", "summary_ok", "invite_ok", "dm_ok"]
        if all(k in vr and isinstance(vr[k], bool) for k in required_bool_keys) and "credible_counts" in vr and isinstance(vr["credible_counts"], dict):
            # Check credible_counts structure for all claim_ids
            cc = vr["credible_counts"]
            cc_ok = True
            for cid in claim_ids:
                if cid not in cc:
                    cc_ok = False
                    break
                entry = cc[cid]
                if not isinstance(entry, dict):
                    cc_ok = False
                    break
                if "total" not in entry or "credible" not in entry:
                    cc_ok = False
                    break
                if not isinstance(entry["total"], int) or not isinstance(entry["credible"], bool):
                    cc_ok = False
                    break
            vr_ok = cc_ok
    scores["validation_report_exists_and_has_keys"] = 1.0 if vr_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()