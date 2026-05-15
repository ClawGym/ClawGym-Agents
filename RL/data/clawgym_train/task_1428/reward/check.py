import json
import csv
import sys
import re
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime


def _read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _simple_yaml_load(path: Path):
    """
    Minimal YAML loader for simple flat mappings and one-level lists like:
    allowed_domains:
      - nih.gov
      - who.int
    min_sources_per_concept: 2
    output_dir: "outputs"
    """
    if not path.exists():
        return None
    try:
        data = {}
        current_key = None
        in_list = False
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if re.match(r"^[\w_]+:\s*(.+)?$", line) and not line.startswith("-"):
                # new key
                parts = line.split(":", 1)
                key = parts[0].strip()
                val = parts[1].strip() if len(parts) > 1 else ""
                if val == "":
                    # maybe a list or empty value
                    data[key] = []
                    current_key = key
                    in_list = True
                else:
                    # scalar
                    val = val.strip()
                    # remove surrounding quotes
                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]
                    # try int
                    if re.fullmatch(r"-?\d+", val):
                        try:
                            data[key] = int(val)
                        except Exception:
                            data[key] = val
                    else:
                        data[key] = val
                    current_key = None
                    in_list = False
            elif line.startswith("-"):
                # list item
                if not in_list or current_key is None:
                    # malformed for our simple parser
                    return None
                item = line[1:].strip()
                if (item.startswith('"') and item.endswith('"')) or (item.startswith("'") and item.endswith("'")):
                    item = item[1:-1]
                data[current_key].append(item)
            else:
                # unsupported structure for our simple parser
                return None
        return data
    except Exception:
        return None


def _safe_load_json(path: Path):
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_load_jsonl_lines(path: Path):
    if not path.exists():
        return None
    lines = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for raw in f:
                s = raw.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                except Exception:
                    return None
                lines.append(obj)
        return lines
    except Exception:
        return None


def _safe_read_csv_rows(path: Path):
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            # Ensure header exists
            if reader.fieldnames is None:
                return None
            return rows, reader.fieldnames
    except Exception:
        return None


def _parse_bool_str(s: str):
    if isinstance(s, bool):
        return s
    if not isinstance(s, str):
        return None
    sl = s.strip().lower()
    if sl == "true":
        return True
    if sl == "false":
        return False
    return None


def _count_sentences(text: str) -> int:
    if not isinstance(text, str):
        return 0
    # Split on ., !, ?, but ignore multiple spaces and empty
    parts = re.split(r"[.!?]+", text)
    return len([p for p in (x.strip() for x in parts) if p])


def _domain_from_url(url: str):
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if ":" in host:
            host = host.split(":")[0]
        # remove leading www.
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return None


def _is_url_domain_allowed(url: str, allowed_domains: list) -> bool:
    host = _domain_from_url(url)
    if not host:
        return False
    for ad in allowed_domains:
        adl = ad.lower()
        if host == adl or host.endswith("." + adl):
            return True
    return False


def _extract_candidates_from_outline(outline_text: str):
    # Candidate phrases as exemplified in the task
    candidate_phrases = [
        "innate immunity",
        "adaptive immunity",
        "antigen presentation",
        "MHC",
        "dendritic cells",
        "B cells",
        "T cells",
        "clonal selection",
        "cytokines",
        "complement system",
        "vaccination",
        "immunological memory",
        "hypersensitivity",
        "tolerance",
        "allergy",
        "neutralizing antibodies",
        "T helper cells",
        "chemokines",
    ]
    present = set()
    low = outline_text.lower()
    for phrase in candidate_phrases:
        pattern = r"\b" + re.escape(phrase.lower()) + r"\b"
        if re.search(pattern, low):
            present.add(phrase)
    return sorted(present, key=lambda x: x.lower())


def _compute_question_freqs(rows):
    # rows contain 'question' field
    all_text = " ".join([r.get("question", "") for r in rows]).lower()
    per_row_text = [r.get("question", "").lower() for r in rows]
    def count_phrase(phrase):
        # count occurrences across all rows using word boundary regex
        pat = re.compile(r"\b" + re.escape(phrase.lower()) + r"\b", re.IGNORECASE)
        total = 0
        for qt in per_row_text:
            total += len(pat.findall(qt))
        return total
    return count_phrase


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_snapshot_min_sources_and_output_dir": 0.0,
        "config_snapshot_allowed_domains_minimum_and_retention": 0.0,
        "modified_config_min_sources_and_output_dir": 0.0,
        "modified_config_allowed_domains_minimum_and_retention": 0.0,
        "config_snapshot_matches_modified_config": 0.0,
        "concept_index_selection_and_counts": 0.0,
        "concept_index_boolean_flags_correct": 0.0,
        "concept_summaries_structure_and_coverage": 0.0,
        "summaries_sources_domains_and_distinctness": 0.0,
        "search_log_structure_and_allowed_domains": 0.0,
        "cross_file_concept_set_consistency": 0.0,
    }

    # Paths
    outline_path = workspace / "input" / "lesson_outline.md"
    questions_path = workspace / "input" / "student_questions.csv"
    modified_config_path = workspace / "config" / "search_config.yaml"
    outputs_dir = workspace / "outputs"
    index_csv_path = outputs_dir / "concept_index.csv"
    summaries_json_path = outputs_dir / "concept_summaries.json"
    search_log_path = outputs_dir / "search_log.jsonl"
    config_snapshot_path = outputs_dir / "config_snapshot.yaml"

    # Load configs
    config_snapshot = _simple_yaml_load(config_snapshot_path)
    modified_config = _simple_yaml_load(modified_config_path)

    # Check config_snapshot min_sources and output_dir
    if isinstance(config_snapshot, dict):
        min_sources = config_snapshot.get("min_sources_per_concept", None)
        out_dir = config_snapshot.get("output_dir", None)
        if isinstance(min_sources, int) and min_sources == 2 and out_dir == "outputs":
            scores["config_snapshot_min_sources_and_output_dir"] = 1.0
        # allowed_domains requirements
        allowed_domains = config_snapshot.get("allowed_domains", None)
        if isinstance(allowed_domains, list):
            ad_set = set(d.lower() for d in allowed_domains if isinstance(d, str))
            if len(ad_set) >= 7 and "nih.gov" in ad_set and "who.int" in ad_set:
                scores["config_snapshot_allowed_domains_minimum_and_retention"] = 1.0

    # Check modified_config requirements similarly
    if isinstance(modified_config, dict):
        min_sources = modified_config.get("min_sources_per_concept", None)
        out_dir = modified_config.get("output_dir", None)
        if isinstance(min_sources, int) and min_sources == 2 and out_dir == "outputs":
            scores["modified_config_min_sources_and_output_dir"] = 1.0
        allowed_domains = modified_config.get("allowed_domains", None)
        if isinstance(allowed_domains, list):
            ad_set = set(d.lower() for d in allowed_domains if isinstance(d, str))
            if len(ad_set) >= 7 and "nih.gov" in ad_set and "who.int" in ad_set:
                scores["modified_config_allowed_domains_minimum_and_retention"] = 1.0

    # Check config snapshot matches modified config
    if isinstance(config_snapshot, dict) and isinstance(modified_config, dict):
        try:
            # Compare allowed_domains as sets of lower
            ad1 = set([d.lower() for d in config_snapshot.get("allowed_domains", [])])
            ad2 = set([d.lower() for d in modified_config.get("allowed_domains", [])])
            ms1 = config_snapshot.get("min_sources_per_concept", None)
            ms2 = modified_config.get("min_sources_per_concept", None)
            od1 = config_snapshot.get("output_dir", None)
            od2 = modified_config.get("output_dir", None)
            if ad1 == ad2 and ms1 == ms2 and od1 == od2:
                scores["config_snapshot_matches_modified_config"] = 1.0
        except Exception:
            pass

    # Prepare for concept checks: read inputs
    outline_text = _read_text(outline_path)
    questions_csv = _safe_read_csv_rows(questions_path)

    # Derive candidate intersection and frequencies
    candidates_in_outline = set()
    concept_freqs = {}
    total_candidates_with_mentions = set()
    if outline_text is not None and questions_csv is not None:
        rows, headers = questions_csv
        # Extract candidate phrases from outline
        candidates = _extract_candidates_from_outline(outline_text)
        candidates_in_outline = set(candidates)
        # Compute question frequency per candidate
        count_phrase = _compute_question_freqs(rows)
        for cand in candidates:
            freq = count_phrase(cand)
            if freq > 0:
                concept_freqs[cand] = freq
                total_candidates_with_mentions.add(cand)

    # Load outputs
    index_rows = None
    index_fields = None
    if index_csv_path.exists():
        idx = _safe_read_csv_rows(index_csv_path)
        if idx is not None:
            index_rows, index_fields = idx

    summaries = _safe_load_json(summaries_json_path)
    search_lines = _safe_load_jsonl_lines(search_log_path)

    # Determine allowed domains from config snapshot for downstream checks
    allowed_domains_final = []
    if isinstance(config_snapshot, dict) and isinstance(config_snapshot.get("allowed_domains", None), list):
        allowed_domains_final = [d for d in config_snapshot["allowed_domains"] if isinstance(d, str)]

    # concept_index_selection_and_counts: structure and selection validity
    index_valid = False
    if index_rows is not None and isinstance(index_fields, list):
        expected_cols = ["concept", "total_mentions_in_questions", "in_outline", "in_questions"]
        if index_fields == expected_cols:
            # Validate each row
            concepts_in_index = []
            row_ok = True
            for r in index_rows:
                concept = r.get("concept", None)
                tm = r.get("total_mentions_in_questions", None)
                in_outline_str = r.get("in_outline", None)
                in_questions_str = r.get("in_questions", None)
                if not isinstance(concept, str) or concept.strip() == "":
                    row_ok = False
                    break
                # parse int
                try:
                    tm_int = int(tm)
                except Exception:
                    row_ok = False
                    break
                # boolean parsing
                in_outline_val = _parse_bool_str(in_outline_str)
                in_questions_val = _parse_bool_str(in_questions_str)
                if in_outline_val is None or in_questions_val is None:
                    row_ok = False
                    break
                # selection rules checks if we could compute candidates
                if outline_text is not None and questions_csv is not None:
                    # concept must be among candidates with mentions
                    # If concept appears in questions? check via computed freqs if available, else via tm_int > 0
                    computed_freq = concept_freqs.get(concept, None)
                    if computed_freq is None:
                        # either not a valid candidate or did not appear in questions
                        row_ok = False
                        break
                    # total_mentions must equal computed
                    if tm_int != computed_freq:
                        row_ok = False
                        break
                    # flags must be true
                    if in_outline_val is not True or in_questions_val is not True:
                        row_ok = False
                        break
                else:
                    # If we cannot compute, at least ensure tm is non-negative and booleans are either true/false
                    if tm_int < 0:
                        row_ok = False
                        break
                concepts_in_index.append(concept)
            # Additional selection constraints: <= 8 and subset of intersection
            if row_ok:
                if len(concepts_in_index) <= 8 and len(concepts_in_index) >= 1:
                    if outline_text is not None and questions_csv is not None:
                        # All concepts are subset of valid intersection
                        if set(concepts_in_index).issubset(total_candidates_with_mentions):
                            # Ranking by frequency: ensure no excluded concept has strictly higher frequency than any included
                            if len(concepts_in_index) >= 1:
                                min_freq_included = min(concept_freqs[c] for c in concepts_in_index)
                                max_freq_excluded = 0
                                for c, f in concept_freqs.items():
                                    if c not in concepts_in_index:
                                        if f > max_freq_excluded:
                                            max_freq_excluded = f
                                if max_freq_excluded <= min_freq_included:
                                    index_valid = True
                            else:
                                # empty is not allowed by our chosen rule
                                index_valid = False
                        else:
                            index_valid = False
                    else:
                        # cannot validate subset without inputs, but structure was ok
                        index_valid = True
    if index_valid:
        scores["concept_index_selection_and_counts"] = 1.0

    # concept_index_boolean_flags_correct: ensure booleans reflect actual presence when inputs exist
    bools_ok = False
    if index_rows is not None and index_fields is not None and index_fields == ["concept", "total_mentions_in_questions", "in_outline", "in_questions"]:
        row_flag_ok = True
        if outline_text is not None and questions_csv is not None:
            # recompute booleans
            for r in index_rows:
                concept = r.get("concept", "")
                in_outline_val = _parse_bool_str(r.get("in_outline", ""))
                in_questions_val = _parse_bool_str(r.get("in_questions", ""))
                if in_outline_val is None or in_questions_val is None:
                    row_flag_ok = False
                    break
                # in_outline should be True if present in outline
                expected_in_outline = concept in candidates_in_outline
                expected_in_questions = concept_freqs.get(concept, 0) > 0
                if in_outline_val != expected_in_outline or in_questions_val != expected_in_questions:
                    row_flag_ok = False
                    break
        else:
            # If inputs missing, we cannot verify; keep False
            row_flag_ok = False
        if row_flag_ok:
            bools_ok = True
    if bools_ok:
        scores["concept_index_boolean_flags_correct"] = 1.0

    # concept_summaries_structure_and_coverage
    summaries_ok = False
    summaries_domains_ok = False
    concept_set_index = set([r["concept"] for r in index_rows]) if index_rows else set()
    if isinstance(summaries, list) and len(summaries) >= 1:
        # Ensure each is dict with required fields
        # Determine concept set from summaries
        concept_set_summaries = set()
        field_ok = True
        domain_ok = True
        for obj in summaries:
            if not isinstance(obj, dict):
                field_ok = False
                break
            if not all(k in obj for k in ["concept", "sources", "summary", "analogy", "keywords"]):
                field_ok = False
                break
            concept = obj.get("concept")
            if not isinstance(concept, str) or concept.strip() == "":
                field_ok = False
                break
            concept_set_summaries.add(concept)
            # summary 2–3 sentences
            summary = obj.get("summary")
            if not isinstance(summary, str) or not (2 <= _count_sentences(summary) <= 3):
                field_ok = False
                break
            # analogy 1 sentence
            analogy = obj.get("analogy")
            if not isinstance(analogy, str) or _count_sentences(analogy) != 1:
                field_ok = False
                break
            # keywords 2–4 items
            keywords = obj.get("keywords")
            if not isinstance(keywords, list) or not (2 <= len(keywords) <= 4):
                field_ok = False
                break
            for kw in keywords:
                if not isinstance(kw, str) or kw.strip() == "":
                    field_ok = False
                    break
            if not field_ok:
                break
            # sources list with at least 2, objects with source_domain and retrieved_title
            sources = obj.get("sources")
            if not isinstance(sources, list) or len(sources) < 2:
                domain_ok = False
                continue
            domains_seen = set()
            for s in sources:
                if not isinstance(s, dict):
                    domain_ok = False
                    break
                sd = s.get("source_domain")
                rt = s.get("retrieved_title")
                if not isinstance(sd, str) or not isinstance(rt, str):
                    domain_ok = False
                    break
                # source_domain must be exactly one of allowed_domains in modified config snapshot
                if allowed_domains_final:
                    if sd not in allowed_domains_final:
                        domain_ok = False
                        break
                domains_seen.add(sd)
            if not domain_ok:
                break
            # At least two distinct domains
            if len(domains_seen) < 2:
                domain_ok = False
                break
        # Coverage: concepts in summaries must match those in index if both exist
        if concept_set_index:
            if concept_set_summaries == concept_set_index and field_ok:
                summaries_ok = True
        else:
            # If index missing, at least field_ok true
            if field_ok:
                summaries_ok = True
        # Domain constraints
        if domain_ok:
            summaries_domains_ok = True

    if summaries_ok:
        scores["concept_summaries_structure_and_coverage"] = 1.0
    if summaries_domains_ok:
        scores["summaries_sources_domains_and_distinctness"] = 1.0

    # search_log_structure_and_allowed_domains
    log_ok = False
    if isinstance(search_lines, list) and len(search_lines) >= 1:
        # Build mapping concept -> entries
        per_concept = {}
        structure_ok = True
        allowed_ok = True
        # Determine min_sources requirement from snapshot or default 2 (as required)
        min_sources_required = 2
        if isinstance(config_snapshot, dict):
            m = config_snapshot.get("min_sources_per_concept", None)
            if isinstance(m, int):
                min_sources_required = m
        for entry in search_lines:
            if not isinstance(entry, dict):
                structure_ok = False
                break
            if not all(k in entry for k in ["concept", "query", "chosen_urls", "timestamp"]):
                structure_ok = False
                break
            if not isinstance(entry["concept"], str) or not isinstance(entry["query"], str):
                structure_ok = False
                break
            if not isinstance(entry["chosen_urls"], list) or len(entry["chosen_urls"]) == 0:
                structure_ok = False
                break
            # timestamp ISO 8601
            ts = entry.get("timestamp")
            if not isinstance(ts, str):
                structure_ok = False
                break
            try:
                ts_try = ts.replace("Z", "+00:00")
                datetime.fromisoformat(ts_try)
            except Exception:
                structure_ok = False
                break
            # allowed domains check for chosen_urls
            if allowed_domains_final:
                # ensure at least min_sources_required chosen_urls from allowed domains distinct
                domains_allowed = []
                for url in entry["chosen_urls"]:
                    if isinstance(url, str) and _is_url_domain_allowed(url, allowed_domains_final):
                        d = _domain_from_url(url)
                        if d:
                            # Normalize to allowed domain by matching suffix from allowed list
                            for ad in allowed_domains_final:
                                adl = ad.lower()
                                if d == adl or d.endswith("." + adl):
                                    domains_allowed.append(ad)
                                    break
                if len(set(domains_allowed)) < min_sources_required:
                    allowed_ok = False
                    break
            per_concept.setdefault(entry["concept"], []).append(entry)
        # Ensure coverage: at least one log entry per concept in index/summaries (if available)
        if concept_set_index:
            if all(c in per_concept for c in concept_set_index) and structure_ok and allowed_ok:
                log_ok = True
        elif isinstance(summaries, list) and len(summaries) > 0:
            concept_set_summaries = set(obj.get("concept") for obj in summaries if isinstance(obj, dict) and "concept" in obj)
            if all(c in per_concept for c in concept_set_summaries) and structure_ok and allowed_ok:
                log_ok = True
        else:
            if structure_ok and allowed_ok:
                log_ok = True
    if log_ok:
        scores["search_log_structure_and_allowed_domains"] = 1.0

    # cross_file_concept_set_consistency
    cross_ok = False
    if concept_set_index and isinstance(summaries, list) and isinstance(search_lines, list):
        sum_set = set([o.get("concept") for o in summaries if isinstance(o, dict) and "concept" in o])
        log_set = set([e.get("concept") for e in search_lines if isinstance(e, dict) and "concept" in e])
        if concept_set_index == sum_set and concept_set_index.issubset(log_set):
            # We allow logs to have extra concepts, but must include at least those selected
            cross_ok = True
    if cross_ok:
        scores["cross_file_concept_set_consistency"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()