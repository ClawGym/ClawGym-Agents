import json
import csv
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def safe_load_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        if not path.exists():
            return None, f"missing:{path}"
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data, None
    except Exception as e:
        return None, f"json_error:{e}"


def safe_read_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    try:
        if not path.exists():
            return None, f"missing:{path}"
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader]
            return rows, None
    except Exception as e:
        return None, f"csv_error:{e}"


def extract_ints_from_text(s: str) -> List[int]:
    if not isinstance(s, str):
        return []
    # Remove commas in numbers and extract integers
    s_nocomma = re.sub(r",", "", s)
    return [int(m.group(0)) for m in re.finditer(r"\d+", s_nocomma)]


def has_year(text: str) -> bool:
    if not isinstance(text, str):
        return False
    return re.search(r"\b(19|20)\d{2}\b", text) is not None


def load_inputs(workspace: Path) -> Dict[str, Any]:
    inputs = {}
    inputs["testimony_path"] = workspace / "input" / "testimony.txt"
    inputs["law_path"] = workspace / "input" / "law_excerpt.html"
    inputs["data_csv_path"] = workspace / "input" / "data" / "disenfranchisement.csv"
    # For cross-checking data values
    rows, err = safe_read_csv(inputs["data_csv_path"])
    if rows is None:
        inputs["data_rows"] = []
    else:
        inputs["data_rows"] = rows
    return inputs


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "extracted_facts_valid_structure": 0.0,
        "testimony_timeline_facts_present": 0.0,
        "law_facts_required_keys_present": 0.0,
        "data_facts_requirements_met": 0.0,
        "posts_file_valid_structure": 0.0,
        "posts_platform_mix_correct": 0.0,
        "posts_theme_mix_correct": 0.0,
        "twitter_posts_within_length": 0.0,
        "posts_source_ids_exist_and_nonempty": 0.0,
        "law_explainer_posts_cite_amendment": 0.0,
        "personal_story_posts_reference_testimony": 0.0,
        "data_point_posts_reference_data": 0.0,
        "riverland_2020_fact_cited_in_data_post": 0.0,
        "coverage_csv_has_required_columns": 0.0,
        "coverage_row_count_matches_posts": 0.0,
        "coverage_rows_match_posts_and_facts": 0.0,
    }

    # Paths
    facts_path = workspace / "output" / "extracted_facts.json"
    posts_path = workspace / "output" / "posts.json"
    coverage_path = workspace / "output" / "coverage.csv"

    # Load inputs for cross-checking
    inputs = load_inputs(workspace)
    data_rows = inputs.get("data_rows", [])
    # Extract Riverland 2020 figure from inputs
    riverland_2020_value: Optional[int] = None
    for r in data_rows:
        try:
            if r.get("state") == "Riverland" and str(r.get("year")) == "2020":
                val_str = r.get("people_denied", "")
                if val_str is not None and str(val_str).strip() != "":
                    riverland_2020_value = int(str(val_str).replace(",", "").strip())
        except Exception:
            pass

    # Load extracted facts
    facts_json, facts_err = safe_load_json(facts_path)
    facts_list: List[Dict[str, Any]] = []
    if isinstance(facts_json, list):
        facts_list = facts_json

    # Validate extracted facts structure
    facts_valid = True
    fact_ids = set()
    allowed_source_types = {"testimony", "law", "data"}
    if not isinstance(facts_json, list) or len(facts_list) == 0:
        # Allow empty list to still evaluate structure errors explicitly
        if not isinstance(facts_json, list):
            facts_valid = False
        else:
            # An empty facts list likely fails other checks but can still pass structure if fields check is vacuous
            pass
    for item in facts_list:
        if not isinstance(item, dict):
            facts_valid = False
            break
        required_fields = ["id", "source_file", "source_type", "key", "text", "citation"]
        for f in required_fields:
            if f not in item:
                facts_valid = False
                break
        if not facts_valid:
            break
        if not isinstance(item.get("id"), str) or item["id"].strip() == "":
            facts_valid = False
            break
        if item["id"] in fact_ids:
            facts_valid = False
            break
        fact_ids.add(item["id"])
        if not isinstance(item.get("source_file"), str) or not item["source_file"].startswith("input/"):
            facts_valid = False
            break
        if item.get("source_type") not in allowed_source_types:
            facts_valid = False
            break
        if not isinstance(item.get("key"), str) or item["key"].strip() == "":
            facts_valid = False
            break
        if not isinstance(item.get("text"), str) or item["text"].strip() == "":
            facts_valid = False
            break
        if not isinstance(item.get("citation"), str) or item["citation"].strip() == "":
            facts_valid = False
            break
    if facts_valid and isinstance(facts_json, list):
        scores["extracted_facts_valid_structure"] = 1.0

    # Build facts maps
    facts_by_id: Dict[str, Dict[str, Any]] = {}
    facts_by_key: Dict[str, List[Dict[str, Any]]] = {}
    for f in facts_list:
        if isinstance(f, dict) and "id" in f:
            facts_by_id[f["id"]] = f
            facts_by_key.setdefault(f.get("key", ""), []).append(f)

    # Check testimony timeline facts (with explicit years) from input/testimony.txt
    testimony_count_with_years = 0
    for f in facts_list:
        if f.get("source_type") == "testimony" and f.get("source_file") == "input/testimony.txt":
            if has_year(f.get("text", "")):
                testimony_count_with_years += 1
    if testimony_count_with_years >= 2:
        scores["testimony_timeline_facts_present"] = 1.0

    # Law facts: must include keys "sec-12-4b" and "amendment-hb-88"
    law_sec_ok = False
    law_amend_ok = False
    for k in ["sec-12-4b", "amendment-hb-88"]:
        if k in facts_by_key:
            for f in facts_by_key[k]:
                if f.get("source_type") == "law" and f.get("source_file") == "input/law_excerpt.html":
                    if k == "sec-12-4b":
                        law_sec_ok = True
                    if k == "amendment-hb-88":
                        law_amend_ok = True
    if law_sec_ok and law_amend_ok:
        scores["law_facts_required_keys_present"] = 1.0

    # Data facts: at least two, and include Riverland-2020 with correct figure
    data_facts = [f for f in facts_list if f.get("source_type") == "data" and f.get("source_file") == "input/data/disenfranchisement.csv"]
    # Ensure at least two data facts and keys look like "State-YYYY"
    data_key_pattern_count = sum(1 for f in data_facts if isinstance(f.get("key"), str) and re.match(r"^[A-Za-z][A-Za-z ]*-\d{4}$", f.get("key", "")) is not None)
    riverland_2020_facts = [f for f in data_facts if f.get("key") == "Riverland-2020"]
    riverland_2020_value_ok = False
    if riverland_2020_facts:
        # Check that the text or citation includes the 2020 value from input (if available)
        target_val = riverland_2020_value
        # Fallback to 24000 if CSV couldn't be read, to maintain determinism
        if target_val is None:
            target_val = 24000
        for f in riverland_2020_facts:
            ints_in_text = extract_ints_from_text(f.get("text", ""))
            ints_in_cit = extract_ints_from_text(f.get("citation", ""))
            if target_val in ints_in_text or target_val in ints_in_cit:
                riverland_2020_value_ok = True
                break
    if len(data_facts) >= 2 and data_key_pattern_count >= 2 and riverland_2020_facts and riverland_2020_value_ok:
        scores["data_facts_requirements_met"] = 1.0

    # Load posts
    posts_json, posts_err = safe_load_json(posts_path)
    posts_list: List[Dict[str, Any]] = []
    if isinstance(posts_json, list):
        posts_list = posts_json

    # Validate posts structure
    posts_structure_ok = True
    if not isinstance(posts_json, list) or len(posts_list) != 6:
        posts_structure_ok = False
    else:
        for p in posts_list:
            if not isinstance(p, dict):
                posts_structure_ok = False
                break
            # required fields
            required_pf = ["id", "platform", "theme", "post_text", "source_ids", "hashtags"]
            for f in required_pf:
                if f not in p:
                    posts_structure_ok = False
                    break
            if not posts_structure_ok:
                break
            # types
            if not isinstance(p.get("id"), str) or p["id"].strip() == "":
                posts_structure_ok = False
                break
            if p.get("platform") not in {"twitter", "facebook"}:
                posts_structure_ok = False
                break
            if p.get("theme") not in {"personal_story", "law_explainer", "data_point"}:
                posts_structure_ok = False
                break
            if not isinstance(p.get("post_text"), str):
                posts_structure_ok = False
                break
            if not isinstance(p.get("source_ids"), list) or any(not isinstance(x, str) for x in p.get("source_ids")):
                posts_structure_ok = False
                break
            if not isinstance(p.get("hashtags"), list) or len(p.get("hashtags")) < 2 or len(p.get("hashtags")) > 5 or any(not isinstance(h, str) for h in p.get("hashtags")):
                posts_structure_ok = False
                break
    if posts_structure_ok:
        scores["posts_file_valid_structure"] = 1.0

    # Posts platform mix: exactly 3 twitter and 3 facebook
    if posts_structure_ok:
        platform_counts = {"twitter": 0, "facebook": 0}
        for p in posts_list:
            platform_counts[p["platform"]] += 1
        if platform_counts.get("twitter", 0) == 3 and platform_counts.get("facebook", 0) == 3:
            scores["posts_platform_mix_correct"] = 1.0

    # Posts theme mix: exactly 2 of each theme
    if posts_structure_ok:
        theme_counts = {"personal_story": 0, "law_explainer": 0, "data_point": 0}
        for p in posts_list:
            theme_counts[p["theme"]] += 1
        if theme_counts.get("personal_story", 0) == 2 and theme_counts.get("law_explainer", 0) == 2 and theme_counts.get("data_point", 0) == 2:
            scores["posts_theme_mix_correct"] = 1.0

    # Twitter 280 char limit
    twitter_len_ok = True
    if posts_structure_ok:
        for p in posts_list:
            if p["platform"] == "twitter":
                if len(p["post_text"]) > 280:
                    twitter_len_ok = False
                    break
        if twitter_len_ok:
            scores["twitter_posts_within_length"] = 1.0

    # Posts source_ids exist and non-empty (grounded)
    posts_refs_ok = True
    if posts_structure_ok and facts_valid:
        for p in posts_list:
            src_ids = p.get("source_ids", [])
            if not isinstance(src_ids, list) or len(src_ids) == 0:
                posts_refs_ok = False
                break
            for sid in src_ids:
                if sid not in facts_by_id:
                    posts_refs_ok = False
                    break
            if not posts_refs_ok:
                break
        if posts_refs_ok:
            scores["posts_source_ids_exist_and_nonempty"] = 1.0
    else:
        # If either posts or facts invalid, cannot verify references
        posts_refs_ok = False

    # Law explainer posts cite amendment-hb-88
    law_amendment_ids = set([f["id"] for f in facts_by_key.get("amendment-hb-88", [])])
    law_explainer_ok = False
    if posts_structure_ok and posts_refs_ok and law_amendment_ids:
        ok = True
        for p in posts_list:
            if p["theme"] == "law_explainer":
                if not any(sid in law_amendment_ids for sid in p.get("source_ids", [])):
                    ok = False
                    break
        if ok:
            law_explainer_ok = True
    if law_explainer_ok:
        scores["law_explainer_posts_cite_amendment"] = 1.0

    # Personal_story posts reference at least one testimony fact
    personal_story_ok = False
    if posts_structure_ok and posts_refs_ok:
        ok = True
        for p in posts_list:
            if p["theme"] == "personal_story":
                # At least one testimony source
                if not any(facts_by_id.get(sid, {}).get("source_type") == "testimony" for sid in p.get("source_ids", [])):
                    ok = False
                    break
        if ok:
            personal_story_ok = True
    if personal_story_ok:
        scores["personal_story_posts_reference_testimony"] = 1.0

    # Data_point posts reference at least one data fact
    data_point_ok = False
    if posts_structure_ok and posts_refs_ok:
        ok = True
        for p in posts_list:
            if p["theme"] == "data_point":
                if not any(facts_by_id.get(sid, {}).get("source_type") == "data" for sid in p.get("source_ids", [])):
                    ok = False
                    break
        if ok:
            data_point_ok = True
    if data_point_ok:
        scores["data_point_posts_reference_data"] = 1.0

    # Riverland-2020 data fact cited by at least one data_point post
    riverland_2020_ids = set([f["id"] for f in facts_by_key.get("Riverland-2020", [])])
    rl2020_cited_ok = False
    if posts_structure_ok and posts_refs_ok and riverland_2020_ids:
        for p in posts_list:
            if p["theme"] == "data_point":
                if any(sid in riverland_2020_ids for sid in p.get("source_ids", [])):
                    rl2020_cited_ok = True
                    break
    if rl2020_cited_ok:
        scores["riverland_2020_fact_cited_in_data_post"] = 1.0

    # Load coverage CSV
    coverage_rows, coverage_err = safe_read_csv(coverage_path)
    coverage_has_columns = False
    if coverage_rows is not None:
        # Check columns
        required_cols = {"post_id", "theme", "platform", "source_id", "source_type"}
        header_cols = set(coverage_rows[0].keys()) if coverage_rows else set()
        if required_cols.issubset(header_cols):
            coverage_has_columns = True
    if coverage_has_columns:
        scores["coverage_csv_has_required_columns"] = 1.0

    # Coverage row count matches total source_ids used across posts
    if coverage_has_columns and posts_structure_ok:
        expected_count = sum(len(p.get("source_ids", [])) for p in posts_list)
        actual_count = len(coverage_rows)
        if expected_count == actual_count:
            scores["coverage_row_count_matches_posts"] = 1.0

    # Coverage rows match posts and facts (theme/platform/source_type)
    coverage_rows_match = False
    if coverage_has_columns and posts_structure_ok and facts_valid:
        post_by_id = {p["id"]: p for p in posts_list}
        ok = True
        for row in coverage_rows:
            pid = row.get("post_id", "")
            sid = row.get("source_id", "")
            r_theme = row.get("theme", "")
            r_platform = row.get("platform", "")
            r_source_type = row.get("source_type", "")
            # Post must exist
            if pid not in post_by_id:
                ok = False
                break
            p = post_by_id[pid]
            # Theme and platform must match
            if p.get("theme") != r_theme or p.get("platform") != r_platform:
                ok = False
                break
            # Source id must exist in facts and type must match
            if sid not in facts_by_id:
                ok = False
                break
            fact = facts_by_id[sid]
            if fact.get("source_type") != r_source_type:
                ok = False
                break
            # Optional: ensure that source is actually referenced by the post
            # The spec says one row per (post, referenced fact) pair, so require sid in post.source_ids
            if sid not in p.get("source_ids", []):
                ok = False
                break
        if ok:
            coverage_rows_match = True
    if coverage_rows_match:
        scores["coverage_rows_match_posts_and_facts"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()