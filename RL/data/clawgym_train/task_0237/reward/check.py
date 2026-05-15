import csv
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def parse_csv_file(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [row for row in reader]
    except Exception:
        return None


def load_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        objs: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                objs.append(json.loads(line))
        return objs
    except Exception:
        return None


def is_domain(s: str) -> bool:
    s = s.strip().lower()
    if not s or len(s) > 253:
        return False
    # basic domain pattern: labels of a-z0-9- separated by dots, ending with TLD 2+ chars
    return bool(re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}", s))


def normalize_domain(s: str) -> str:
    s = s.strip().lower()
    if s.startswith("www."):
        s = s[4:]
    return s


def domain_from_url(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url.strip())
        if parsed.scheme not in ("http", "https"):
            return None
        netloc = parsed.netloc.lower()
        # strip port
        netloc = netloc.split("@")[-1]  # remove potential userinfo
        netloc = netloc.split(":")[0]
        if netloc.startswith("www."):
            netloc = netloc[4:]
        if is_domain(netloc):
            return netloc
        return None
    except Exception:
        return None


def domains_match(official: str, candidate: str) -> bool:
    off = normalize_domain(official)
    cand = normalize_domain(candidate)
    return cand == off or cand.endswith("." + off) or off.endswith("." + cand)


def normalize_tri(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "yes", "y"):
            return "true"
        if v in ("false", "no", "n"):
            return "false"
        if v in ("unknown", "na", "n/a", ""):
            return "unknown"
    return "unknown"


def is_permissive_license(s: str) -> bool:
    if not isinstance(s, str) or not s.strip():
        return False
    v = s.strip().lower()
    # accept common permissive licenses
    permissive_keywords = [
        "mit",
        "apache-2.0",
        "apache 2.0",
        "apache license 2.0",
        "bsd-2-clause",
        "bsd-3-clause",
        "bsd",
        "isc",
        "the unlicense",
        "unlicense",
    ]
    for kw in permissive_keywords:
        if kw in v:
            return True
    # known non-permissive or disallowed
    disallowed_keywords = [
        "gpl",
        "agpl",
        "lgpl",
        "mpl",
        "mozilla public license",
        "copyleft",
        "proprietary",
        "commercial",
        "unknown",
    ]
    for kw in disallowed_keywords:
        if kw in v:
            return False
    # default to not permissive if unclear
    return False


def count_words(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def parse_constraints(path: Path) -> Dict[str, Any]:
    # Minimal ad-hoc parser for just the needed fields
    defaults = {
        "license_policy": {"permissive_only": True},
        "required_features": ["built-in validation", "async or concurrency"],
        "max_words": {"architecture_brief": 250, "scoring_notes": 200},
    }
    txt = read_text(path)
    if txt is None:
        return defaults
    lp_perm = None
    req_features: List[str] = []
    max_words_arch = None
    lines = [line.rstrip("\n") for line in txt.splitlines()]
    section = None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith(" "):  # top-level key
            if stripped.startswith("license_policy:"):
                section = "license_policy"
            elif stripped.startswith("required_features:"):
                section = "required_features"
            elif stripped.startswith("max_words:"):
                section = "max_words"
            else:
                section = None
            continue
        # nested content
        if section == "license_policy":
            m = re.search(r"permissive_only:\s*(\w+)", stripped)
            if m:
                lp_perm = m.group(1).strip().lower() in ("true", "yes", "1")
        elif section == "required_features":
            m = re.search(r"-\s*(.+)", stripped)
            if m:
                req_features.append(m.group(1).strip())
        elif section == "max_words":
            m = re.search(r"architecture_brief:\s*(\d+)", stripped)
            if m:
                try:
                    max_words_arch = int(m.group(1))
                except Exception:
                    pass
    if lp_perm is None:
        lp_perm = defaults["license_policy"]["permissive_only"]
    if not req_features:
        req_features = defaults["required_features"]
    if max_words_arch is None:
        max_words_arch = defaults["max_words"]["architecture_brief"]
    return {
        "license_policy": {"permissive_only": lp_perm},
        "required_features": req_features,
        "max_words": {"architecture_brief": max_words_arch, "scoring_notes": defaults["max_words"]["scoring_notes"]},
    }


def get_candidates_map(path: Path) -> Optional[Dict[str, str]]:
    rows = parse_csv_file(path)
    if rows is None:
        return None
    mapping: Dict[str, str] = {}
    for r in rows:
        name = (r.get("name") or "").strip()
        lang = (r.get("language") or "").strip()
        if name:
            mapping[name] = lang
    return mapping


def validate_evidence_schema(objs: List[Dict[str, Any]]) -> Tuple[float, float]:
    if not objs:
        return 0.0, 0.0
    total = len(objs)
    schema_ok = 0
    domain_link_ok = 0
    for obj in objs:
        try:
            official_site_domain = obj.get("official_site_domain")
            docs_page_title = obj.get("docs_page_title")
            license_str = obj.get("license")
            evidence_links = obj.get("evidence_links")
            required_features_found = obj.get("required_features_found")
            notes = obj.get("notes")
            # Validate required fields
            if not isinstance(official_site_domain, str) or not is_domain(official_site_domain):
                continue
            if not isinstance(docs_page_title, str) or not docs_page_title.strip():
                continue
            if not isinstance(license_str, str) or not license_str.strip():
                continue
            if not isinstance(evidence_links, list) or not (1 <= len(evidence_links) <= 3):
                continue
            if not isinstance(required_features_found, dict):
                continue
            if "built_in_validation" not in required_features_found or "async_or_concurrency" not in required_features_found:
                continue
            biv = normalize_tri(required_features_found.get("built_in_validation"))
            aoc = normalize_tri(required_features_found.get("async_or_concurrency"))
            if biv not in ("true", "false", "unknown"):
                continue
            if aoc not in ("true", "false", "unknown"):
                continue
            if not isinstance(notes, str) or not notes.strip() or "\n" in notes or len(notes) > 200:
                continue
            # evidence_links must be http(s) and at least one link domain matches official_site_domain
            link_domains = []
            http_ok = True
            for link in evidence_links:
                if not isinstance(link, str):
                    http_ok = False
                    break
                d = domain_from_url(link)
                if d is None:
                    http_ok = False
                    break
                link_domains.append(d)
            if not http_ok:
                continue
        except Exception:
            continue
        schema_ok += 1
        if any(domains_match(official_site_domain, ld) for ld in link_domains):
            domain_link_ok += 1
    return schema_ok / total, domain_link_ok / total


def compute_eligible_count(objs: List[Dict[str, Any]], permissive_only: bool) -> int:
    count = 0
    for obj in objs:
        try:
            license_str = str(obj.get("license", "")).strip()
            features = obj.get("required_features_found", {})
            biv = normalize_tri(features.get("built_in_validation"))
            aoc = normalize_tri(features.get("async_or_concurrency"))
            if permissive_only:
                if not is_permissive_license(license_str):
                    continue
            else:
                if not license_str:
                    continue
            if biv == "true" and aoc == "true":
                count += 1
        except Exception:
            continue
    return count


def parse_ranking_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    rows = parse_csv_file(path)
    return rows


def check_ranking_header(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return False
            expected = ["name", "language", "score", "reasons"]
            return header == expected
    except Exception:
        return False


def scores_sorted_desc_and_formatted(rows: List[Dict[str, str]]) -> bool:
    prev = None
    for r in rows:
        s = (r.get("score") or "").strip()
        if not re.fullmatch(r"^(?:0\.\d{3}|1\.000)$", s):
            return False
        try:
            val = float(s)
        except Exception:
            return False
        if prev is not None and val > prev + 1e-12:
            # not descending
            return False
        prev = val
    return True


def reasons_citation_ok(rows: List[Dict[str, str]]) -> bool:
    # require each reasons to include either a domain-like token or an index citation [0-2]
    domain_pat = re.compile(r"\b(?:[a-z0-9-]+\.)+[a-z]{2,}\b", re.IGNORECASE)
    for r in rows:
        reasons = (r.get("reasons") or "")
        if "\n" in reasons or "\r" in reasons:
            return False
        has_domain = bool(domain_pat.search(reasons))
        has_index = any(f"[{i}]" in reasons for i in range(3))
        if not (has_domain or has_index):
            return False
    return True


def architecture_bullets_for_top2(text: str, top1: Optional[str], top2: Optional[str]) -> bool:
    if not top1 or not top2:
        return False
    bullet_lines = []
    for line in text.splitlines():
        if line.lstrip().startswith(("- ", "* ")):
            bullet_lines.append(line.strip())
    if not bullet_lines:
        return False
    domain_pat = re.compile(r"(?:[a-z0-9-]+\.)+[a-z]{2,}", re.IGNORECASE)
    def has_bullet(name: str) -> bool:
        for bl in bullet_lines:
            if name in bl and domain_pat.search(bl):
                return True
        return False
    return has_bullet(top1) and has_bullet(top2)


def architecture_mentions_top_and_elements(text: str, top1: Optional[str]) -> bool:
    if not top1:
        return False
    if top1 not in text:
        return False
    keywords = {"rest", "websocket", "cache", "caching", "deduplicate", "deduplication", "async", "concurrency", "queue", "worker", "api", "latency"}
    present = 0
    low = text.lower()
    for k in keywords:
        if k in low:
            present += 1
    return present >= 2


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "evidence_file_present": 0.0,
        "evidence_line_count_matches_candidates": 0.0,
        "evidence_schema_and_fields_valid": 0.0,
        "evidence_links_match_official_domain": 0.0,
        "ranking_header_and_columns_valid": 0.0,
        "ranking_names_subset_and_languages_match": 0.0,
        "ranking_sorted_desc_and_score_format": 0.0,
        "ranking_candidate_count_matches_filters": 0.0,
        "ranking_reasons_cite_domains_or_indices": 0.0,
        "architecture_brief_exists_and_within_word_limit": 0.0,
        "architecture_mentions_top_framework_and_key_elements": 0.0,
        "architecture_top2_listed_with_bullets_and_domains": 0.0,
    }

    input_dir = workspace / "input"
    output_dir = workspace / "output"

    candidates_path = input_dir / "candidates.csv"
    constraints_path = input_dir / "constraints.yaml"
    context_path = input_dir / "context.md"  # existence not graded directly
    priorities_path = input_dir / "priorities.json"  # existence not graded directly

    evidence_path = output_dir / "framework_evidence.jsonl"
    ranking_path = output_dir / "ranking.csv"
    arch_path = output_dir / "architecture_brief.md"

    candidates_map = get_candidates_map(candidates_path) or {}
    num_candidates = len(candidates_map)

    # Evidence checks
    if evidence_path.exists():
        scores["evidence_file_present"] = 1.0
        objs = load_jsonl(evidence_path)
        if objs is not None:
            # line count check
            if len(objs) == num_candidates and num_candidates > 0:
                scores["evidence_line_count_matches_candidates"] = 1.0
            elif num_candidates == 0 and len(objs) == 0:
                scores["evidence_line_count_matches_candidates"] = 1.0
            else:
                scores["evidence_line_count_matches_candidates"] = 0.0
            schema_ratio, domain_ratio = validate_evidence_schema(objs)
            # Only give full credit if all lines valid; otherwise partial credit equals ratio
            scores["evidence_schema_and_fields_valid"] = schema_ratio
            scores["evidence_links_match_official_domain"] = domain_ratio
        else:
            scores["evidence_line_count_matches_candidates"] = 0.0
            scores["evidence_schema_and_fields_valid"] = 0.0
            scores["evidence_links_match_official_domain"] = 0.0
    else:
        scores["evidence_file_present"] = 0.0

    # Ranking checks
    ranking_rows = parse_ranking_csv(ranking_path) if ranking_path.exists() else None
    if ranking_path.exists() and ranking_rows is not None:
        # header check
        scores["ranking_header_and_columns_valid"] = 1.0 if check_ranking_header(ranking_path) else 0.0
        # names subset and languages match
        names_ok = True
        for r in ranking_rows:
            name = (r.get("name") or "").strip()
            lang = (r.get("language") or "").strip()
            if not name or name not in candidates_map:
                names_ok = False
                break
            if candidates_map.get(name, "") != lang:
                names_ok = False
                break
        scores["ranking_names_subset_and_languages_match"] = 1.0 if names_ok else 0.0
        # sorted desc and score format
        scores["ranking_sorted_desc_and_score_format"] = 1.0 if scores_sorted_desc_and_formatted(ranking_rows) else 0.0
        # reasons citation
        scores["ranking_reasons_cite_domains_or_indices"] = 1.0 if reasons_citation_ok(ranking_rows) else 0.0
        # filter count compliance
        objs = load_jsonl(evidence_path) if evidence_path.exists() else None
        constraints = parse_constraints(constraints_path)
        if objs is not None and isinstance(objs, list):
            eligible_count = compute_eligible_count(objs, permissive_only=constraints["license_policy"]["permissive_only"])
            ranked_count = len(ranking_rows)
            scores["ranking_candidate_count_matches_filters"] = 1.0 if ranked_count == eligible_count else 0.0
        else:
            scores["ranking_candidate_count_matches_filters"] = 0.0
    else:
        scores["ranking_header_and_columns_valid"] = 0.0
        scores["ranking_names_subset_and_languages_match"] = 0.0
        scores["ranking_sorted_desc_and_score_format"] = 0.0
        scores["ranking_reasons_cite_domains_or_indices"] = 0.0
        scores["ranking_candidate_count_matches_filters"] = 0.0

    # Architecture brief checks
    constraints = parse_constraints(constraints_path)
    max_words = constraints.get("max_words", {}).get("architecture_brief", 250)
    arch_text = read_text(arch_path) if arch_path.exists() else None
    if arch_text is not None:
        # word limit
        scores["architecture_brief_exists_and_within_word_limit"] = 1.0 if count_words(arch_text) <= max_words else 0.0
        # Determine top 2 frameworks from ranking
        top1 = None
        top2 = None
        if ranking_rows:
            if len(ranking_rows) >= 1:
                top1 = ranking_rows[0].get("name")
            if len(ranking_rows) >= 2:
                top2 = ranking_rows[1].get("name")
        # mentions top1 and architecture elements
        scores["architecture_mentions_top_framework_and_key_elements"] = 1.0 if architecture_mentions_top_and_elements(arch_text, top1) else 0.0
        # bullets for top2 with domains
        scores["architecture_top2_listed_with_bullets_and_domains"] = 1.0 if architecture_bullets_for_top2(arch_text, top1, top2) else 0.0
    else:
        scores["architecture_brief_exists_and_within_word_limit"] = 0.0
        scores["architecture_mentions_top_framework_and_key_elements"] = 0.0
        scores["architecture_top2_listed_with_bullets_and_domains"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()