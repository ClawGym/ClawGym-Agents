import json
import csv
import sys
import re
from pathlib import Path
from urllib.parse import urlparse


def read_csv_safe(path: Path):
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            rows = [row for row in reader]
            return headers, rows
    except Exception:
        return None, None


def load_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def load_jsonl_safe(path: Path):
    items = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    items.append(obj)
                except Exception:
                    return None
        return items
    except Exception:
        return None


def parse_domain_from_url(url: str) -> str:
    if not url or not isinstance(url, str):
        return ""
    u = url
    if "://" not in u:
        u = "http://" + u
    try:
        parsed = urlparse(u)
        host = parsed.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def is_plain_domain(value: str) -> bool:
    if not value or not isinstance(value, str):
        return False
    v = value.strip().lower()
    if any(tok in v for tok in ["http://", "https://", "/", " "]):
        return False
    return bool(re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", v))


def extract_novelty_words(path: Path):
    text = load_text_safe(path)
    if not text:
        return []
    for line in text.splitlines():
        if "Novelty words to watch" in line:
            if ":" in line:
                parts = line.split(":", 1)[1]
                words = [w.strip().lower() for w in parts.split(",") if w.strip()]
                return words
    return []


def load_startup_ideas(path: Path):
    headers, rows = read_csv_safe(path)
    ideas = []
    if headers is None or rows is None:
        return ideas
    required_cols = ["idea_id", "idea_name", "customer_segment", "problem_hypothesis", "keywords"]
    if headers != required_cols:
        if not all(col in (headers or []) for col in required_cols):
            return ideas
    for row in rows:
        try:
            idea_id = int(row.get("idea_id", "").strip())
        except Exception:
            continue
        ideas.append({
            "idea_id": idea_id,
            "idea_name": row.get("idea_name", "").strip(),
            "customer_segment": row.get("customer_segment", "").strip(),
            "problem_hypothesis": row.get("problem_hypothesis", "").strip(),
            "keywords": row.get("keywords", "").strip(),
        })
    return ideas


def tokenize_words(text: str):
    return re.findall(r"[A-Za-z0-9']+", text.lower())


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "competitors_files_present": 0.0,
        "competitors_columns_valid": 0.0,
        "competitors_rows_valid": 0.0,
        "competitors_minimum_count": 0.0,
        "competitors_source_domains_official": 0.0,
        "search_log_structure": 0.0,
        "search_log_covers_competitors": 0.0,
        "competitors_pricing_supported_by_log": 0.0,
        "idea_scores_file_and_columns": 0.0,
        "idea_scores_metrics_correct": 0.0,
        "idea_scores_rationale_quality": 0.0,
        "value_prop_rewrite_present": 0.0,
        "value_prop_sections_per_idea": 0.0,
        "value_prop_mentions_competitors": 0.0,
        "value_prop_mentions_scores": 0.0,
        "value_prop_avoids_novelty_words": 0.0,
    }

    input_ideas_path = workspace / "input" / "startup_ideas.csv"
    ideas = load_startup_ideas(input_ideas_path)
    novelty_words = extract_novelty_words(workspace / "notes" / "failure_patterns.md")

    competitor_headers_expected = [
        "idea_id",
        "idea_name",
        "competitor_name",
        "source_domain",
        "has_pricing_page",
        "evidence_note",
    ]
    competitors_per_idea = {}
    competitors_files_exist_flags = []
    columns_valid_flags = []
    rows_valid_counts = []
    rows_total_counts = []
    minimum_count_scores = []
    official_domain_valid_rows = 0
    official_domain_total_rows = 0

    banned_aggregators = {
        "crunchbase.com",
        "g2.com",
        "capterra.com",
        "getapp.com",
        "producthunt.com",
        "angel.co",
        "wikipedia.org",
        "linkedin.com",
        "facebook.com",
        "twitter.com",
        "x.com",
        "youtube.com",
        "github.com",
        "gitlab.com",
        "sourceforge.net",
        "alternativeto.net",
        "stackshare.io",
        "quora.com",
        "reddit.com",
        "medium.com",
        "docs.google.com",
        "notion.site",
    }

    for idea in ideas:
        iid = idea["idea_id"]
        comp_path = workspace / "output" / f"competitors_{iid}.csv"
        if comp_path.exists():
            competitors_files_exist_flags.append(1.0)
        else:
            competitors_files_exist_flags.append(0.0)
            competitors_per_idea[iid] = {"headers": None, "rows": []}
            columns_valid_flags.append(0.0)
            rows_valid_counts.append(0)
            rows_total_counts.append(0)
            minimum_count_scores.append(0.0)
            continue

        headers, rows = read_csv_safe(comp_path)
        competitors_per_idea[iid] = {"headers": headers, "rows": rows or []}

        if headers == competitor_headers_expected:
            columns_valid_flags.append(1.0)
        else:
            columns_valid_flags.append(0.0)

        valid_rows = 0
        total_rows = 0
        for r in (rows or []):
            total_rows += 1
            try:
                rid = int(str(r.get("idea_id", "")).strip())
            except Exception:
                rid = None
            idea_id_ok = (rid == iid)
            idea_name_ok = (str(r.get("idea_name", "")).strip() == idea["idea_name"])
            comp_name_ok = bool(str(r.get("competitor_name", "")).strip())
            source_domain = str(r.get("source_domain", "")).strip().lower()
            source_domain_ok = is_plain_domain(source_domain)
            has_pricing = str(r.get("has_pricing_page", "")).strip().lower()
            has_pricing_ok = has_pricing in {"yes", "no"}
            evidence_note = str(r.get("evidence_note", "")).strip()
            words = tokenize_words(evidence_note)
            evidence_ok = 3 <= len(words) <= 20

            if idea_id_ok and idea_name_ok and comp_name_ok and source_domain_ok and has_pricing_ok and evidence_ok:
                valid_rows += 1

            if source_domain:
                official_domain_total_rows += 1
                if source_domain_ok and (source_domain not in banned_aggregators):
                    official_domain_valid_rows += 1

        rows_valid_counts.append(valid_rows)
        rows_total_counts.append(total_rows)

        if rows:
            if len(rows) >= 2:
                minimum_count_scores.append(1.0)
            elif len(rows) == 1:
                enote = str(rows[0].get("evidence_note", "")).lower()
                if ("only one" in enote) or ("single competitor" in enote) or ("only 1" in enote) or ("one competitor" in enote):
                    minimum_count_scores.append(0.5)
                else:
                    minimum_count_scores.append(0.0)
            else:
                minimum_count_scores.append(0.0)
        else:
            minimum_count_scores.append(0.0)

    if competitors_files_exist_flags:
        scores["competitors_files_present"] = sum(competitors_files_exist_flags) / len(competitors_files_exist_flags)
    else:
        scores["competitors_files_present"] = 0.0

    if columns_valid_flags:
        scores["competitors_columns_valid"] = sum(columns_valid_flags) / len(columns_valid_flags)
    else:
        scores["competitors_columns_valid"] = 0.0

    if rows_total_counts and sum(rows_total_counts) > 0:
        scores["competitors_rows_valid"] = sum(rows_valid_counts) / max(1, sum(rows_total_counts))
    else:
        scores["competitors_rows_valid"] = 0.0

    if minimum_count_scores:
        scores["competitors_minimum_count"] = sum(minimum_count_scores) / len(minimum_count_scores)
    else:
        scores["competitors_minimum_count"] = 0.0

    if official_domain_total_rows > 0:
        scores["competitors_source_domains_official"] = official_domain_valid_rows / official_domain_total_rows
    else:
        scores["competitors_source_domains_official"] = 0.0

    search_log_path = workspace / "output" / "search_log.jsonl"
    search_entries = load_jsonl_safe(search_log_path)

    search_map = {}
    structure_per_idea = []
    if search_entries is not None and ideas:
        entries_by_id = {}
        for entry in search_entries:
            eid = entry.get("idea_id")
            try:
                eid_int = int(eid)
            except Exception:
                eid_int = None
            if eid_int is not None:
                entries_by_id[eid_int] = entry

        for idea in ideas:
            iid = idea["idea_id"]
            entry = entries_by_id.get(iid)
            if not entry:
                structure_per_idea.append(0.0)
                continue
            queries = entry.get("queries")
            selected_urls = entry.get("selected_urls")
            queries_ok = isinstance(queries, list) and all(isinstance(q, str) and q.strip() for q in queries) and len(queries) >= 1
            urls_ok = isinstance(selected_urls, list) and all(isinstance(u, str) and u.strip() for u in selected_urls) and len(selected_urls) >= 1
            structure_per_idea.append(1.0 if (queries_ok and urls_ok) else 0.0)
            search_map[iid] = {
                "queries": queries if isinstance(queries, list) else [],
                "selected_urls": selected_urls if isinstance(selected_urls, list) else [],
            }
    else:
        structure_per_idea = [0.0 for _ in ideas]

    scores["search_log_structure"] = (sum(structure_per_idea) / len(structure_per_idea)) if structure_per_idea else 0.0

    total_comp_rows = 0
    comp_rows_covered = 0

    total_pricing_yes = 0
    pricing_yes_supported = 0

    for idea in ideas:
        iid = idea["idea_id"]
        comp_bundle = competitors_per_idea.get(iid, {"rows": []})
        comp_rows = comp_bundle.get("rows") or []
        search = search_map.get(iid, {"selected_urls": []})
        selected_urls = search.get("selected_urls") or []
        selected_domains = [parse_domain_from_url(u) for u in selected_urls]

        for r in comp_rows:
            sd = str(r.get("source_domain", "")).strip().lower()
            if not sd:
                continue
            total_comp_rows += 1
            if sd in selected_domains:
                comp_rows_covered += 1

            hp = str(r.get("has_pricing_page", "")).strip().lower()
            if hp == "yes":
                total_pricing_yes += 1
                supported = False
                for u in selected_urls:
                    dom = parse_domain_from_url(u)
                    if dom == sd and ("pricing" in u.lower()):
                        supported = True
                        break
                if supported:
                    pricing_yes_supported += 1

    if total_comp_rows > 0:
        scores["search_log_covers_competitors"] = comp_rows_covered / total_comp_rows
    else:
        scores["search_log_covers_competitors"] = 0.0

    # Require explicit support evidence for claimed pricing pages; no claims -> 0.0
    if total_pricing_yes == 0:
        scores["competitors_pricing_supported_by_log"] = 0.0
    else:
        scores["competitors_pricing_supported_by_log"] = pricing_yes_supported / total_pricing_yes

    idea_scores_path = workspace / "output" / "idea_scores.csv"
    idea_scores_headers, idea_scores_rows = read_csv_safe(idea_scores_path)
    expected_scores_cols = [
        "idea_id",
        "idea_name",
        "segment_specified",
        "problem_specificity",
        "has_2plus_competitors",
        "any_pricing_page_found",
        "novelty_flag",
        "market_alignment_score",
        "rationale",
    ]
    if idea_scores_headers == expected_scores_cols and idea_scores_rows is not None:
        scores["idea_scores_file_and_columns"] = 1.0
    else:
        scores["idea_scores_file_and_columns"] = 0.0

    expected_metrics = {}
    for idea in ideas:
        iid = idea["idea_id"]
        seg_specified = 1 if idea["customer_segment"].strip() != "" else 0
        prob_specificity = 1 if len(idea["problem_hypothesis"]) > 60 else 0
        comp_rows = (competitors_per_idea.get(iid, {}).get("rows") or [])
        comp_rows = [r for r in comp_rows if str(r.get("idea_id", "")).strip() in {str(iid)}]
        has_2plus_comp = 1 if len(comp_rows) >= 2 else 0
        any_pricing = 1 if any(str(r.get("has_pricing_page", "")).strip().lower() == "yes" for r in comp_rows) else 0
        text_join = (idea["idea_name"] + " " + idea["problem_hypothesis"]).lower()
        novelty_hit = 0
        for w in novelty_words:
            if re.search(r"\b" + re.escape(w.lower()) + r"\b", text_join):
                novelty_hit = 1
                break
        market_alignment_score = seg_specified + prob_specificity + has_2plus_comp + any_pricing - novelty_hit
        expected_metrics[iid] = {
            "idea_name": idea["idea_name"],
            "segment_specified": seg_specified,
            "problem_specificity": prob_specificity,
            "has_2plus_competitors": has_2plus_comp,
            "any_pricing_page_found": any_pricing,
            "novelty_flag": novelty_hit,
            "market_alignment_score": market_alignment_score,
        }

    metrics_correct_per_idea = []
    rationale_quality_per_idea = []

    if idea_scores_headers == expected_scores_cols and idea_scores_rows is not None:
        provided_by_id = {}
        for row in idea_scores_rows:
            try:
                iid = int(str(row.get("idea_id", "")).strip())
            except Exception:
                continue
            provided_by_id[iid] = row
        for idea in ideas:
            iid = idea["idea_id"]
            provided = provided_by_id.get(iid)
            if not provided:
                metrics_correct_per_idea.append(0.0)
                rationale_quality_per_idea.append(0.0)
                continue
            exp = expected_metrics.get(iid)
            all_ok = True
            if str(provided.get("idea_name", "")).strip() != exp["idea_name"]:
                all_ok = False
            for key in ["segment_specified", "problem_specificity", "has_2plus_competitors", "any_pricing_page_found", "novelty_flag"]:
                try:
                    val = int(str(provided.get(key, "")).strip())
                except Exception:
                    all_ok = False
                    break
                if val != int(exp[key]):
                    all_ok = False
            try:
                mas = int(str(provided.get("market_alignment_score", "")).strip())
            except Exception:
                mas = None
            if mas != int(exp["market_alignment_score"]):
                all_ok = False
            metrics_correct_per_idea.append(1.0 if all_ok else 0.0)

            rationale = str(provided.get("rationale", "")).strip()
            if not rationale:
                rationale_quality_per_idea.append(0.0)
            else:
                length_ok = len(rationale) <= 220
                kw_ok = any(k in rationale.lower() for k in ["segment", "specific", "competitor", "pricing", "novel", "score"])
                rationale_quality_per_idea.append(1.0 if (length_ok and kw_ok) else 0.0)
    else:
        metrics_correct_per_idea = [0.0 for _ in ideas]
        rationale_quality_per_idea = [0.0 for _ in ideas]

    scores["idea_scores_metrics_correct"] = (sum(metrics_correct_per_idea) / len(metrics_correct_per_idea)) if metrics_correct_per_idea else 0.0
    scores["idea_scores_rationale_quality"] = (sum(rationale_quality_per_idea) / len(rationale_quality_per_idea)) if rationale_quality_per_idea else 0.0

    vp_path = workspace / "output" / "value_prop_rewrite.md"
    vp_text = load_text_safe(vp_path)
    if vp_text.strip():
        scores["value_prop_rewrite_present"] = 1.0
    else:
        scores["value_prop_rewrite_present"] = 0.0

    sections_cover_flags = []
    mentions_competitors_flags = []
    mentions_scores_flags = []

    comp_names_by_idea = {}
    for idea in ideas:
        iid = idea["idea_id"]
        comp_rows = competitors_per_idea.get(iid, {}).get("rows") or []
        comp_names = [str(r.get("competitor_name", "")).strip() for r in comp_rows if str(r.get("competitor_name", "")).strip()]
        comp_names_by_idea[iid] = comp_names

    if vp_text.strip():
        lower_vp = vp_text.lower()
        for idea in ideas:
            iid = idea["idea_id"]
            name_present = idea["idea_name"].lower() in lower_vp
            sections_cover_flags.append(1.0 if name_present else 0.0)

            comp_names = comp_names_by_idea.get(iid, [])
            comp_mention = False
            for cn in comp_names:
                if cn and cn.lower() in lower_vp:
                    comp_mention = True
                    break
            mentions_competitors_flags.append(1.0 if comp_mention else 0.0)

            exp = expected_metrics.get(iid, {})
            mas = exp.get("market_alignment_score")
            score_present = False
            if mas is not None:
                if re.search(r"\b" + re.escape(str(mas)) + r"\b", vp_text):
                    score_present = True
            mentions_scores_flags.append(1.0 if score_present else 0.0)
    else:
        sections_cover_flags = [0.0 for _ in ideas]
        mentions_competitors_flags = [0.0 for _ in ideas]
        mentions_scores_flags = [0.0 for _ in ideas]

    scores["value_prop_sections_per_idea"] = (sum(sections_cover_flags) / len(sections_cover_flags)) if sections_cover_flags else 0.0
    scores["value_prop_mentions_competitors"] = (sum(mentions_competitors_flags) / len(mentions_competitors_flags)) if mentions_competitors_flags else 0.0
    scores["value_prop_mentions_scores"] = (sum(mentions_scores_flags) / len(mentions_scores_flags)) if mentions_scores_flags else 0.0

    novelty_present = False
    if vp_text.strip():
        for w in novelty_words:
            if re.search(r"\b" + re.escape(w.lower()) + r"\b", vp_text.lower()):
                novelty_present = True
                break
        scores["value_prop_avoids_novelty_words"] = 0.0 if novelty_present else 1.0
    else:
        scores["value_prop_avoids_novelty_words"] = 0.0

    for k, v in list(scores.items()):
        try:
            fv = float(v)
        except Exception:
            fv = 0.0
        if fv < 0.0:
            fv = 0.0
        if fv > 1.0:
            fv = 1.0
        scores[k] = fv

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=None, separators=(",", ":")))


if __name__ == "__main__":
    main()