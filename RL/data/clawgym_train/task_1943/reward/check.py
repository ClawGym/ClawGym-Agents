import json
import sys
import csv
import re
from pathlib import Path
import importlib.util

def safe_read_text(p: Path):
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None

def safe_load_jsonl(p: Path):
    records = []
    try:
        with p.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    records.append(obj)
                except Exception:
                    return None
        return records
    except Exception:
        return None

def parse_categories_yaml(p: Path):
    text = safe_read_text(p)
    if text is None:
        return None
    lines = text.splitlines()
    in_categories = False
    categories = {}
    current_cat = None
    current_kw_type = None  # "positive" or "negative"
    for raw in lines:
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        # remove tabs just in case
        line = line.replace("\t", "    ")
        if not in_categories:
            if line.strip() == "categories:":
                in_categories = True
            continue
        # Now inside categories
        # category name at indent 2: "  Pricing:"
        m_cat = re.match(r"^\s{2}([A-Za-z0-9 _-]+):\s*$", line)
        if m_cat:
            current_cat = m_cat.group(1).strip()
            categories[current_cat] = {"positive": {}, "negative": {}}
            current_kw_type = None
            continue
        # keyword section at indent 4: "    positive_keywords:" or "    negative_keywords:"
        m_kw_section = re.match(r"^\s{4}(positive_keywords|negative_keywords):\s*$", line)
        if m_kw_section and current_cat is not None:
            typ = m_kw_section.group(1)
            current_kw_type = "positive" if typ == "positive_keywords" else "negative"
            continue
        # key: value at indent 6
        m_kw = re.match(r"^\s{6}(.+?):\s*([0-9]+)\s*$", line)
        if m_kw and current_cat is not None and current_kw_type in ("positive", "negative"):
            key = m_kw.group(1).strip()
            # strip surrounding quotes if present
            if (key.startswith('"') and key.endswith('"')) or (key.startswith("'") and key.endswith("'")):
                key = key[1:-1]
            try:
                val = int(m_kw.group(2))
            except Exception:
                return None
            categories[current_cat][current_kw_type][key] = val
            continue
        # Anything else is ignored safely
    if not categories:
        return None
    return categories

def load_text_filters_module(workspace: Path):
    mod_path = workspace / "scripts" / "text_filters.py"
    if not mod_path.exists():
        return None
    try:
        spec = importlib.util.spec_from_file_location("text_filters", str(mod_path))
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore
        # must have clean_text
        if not hasattr(module, "clean_text"):
            return None
        return module
    except Exception:
        return None

def tokenize_cleaned(s: str):
    return s.split(" ")

def single_word(keyword: str) -> bool:
    return " " not in keyword.strip()

def match_keyword(cleaned_text: str, tokens_set: set, keyword: str) -> bool:
    if single_word(keyword):
        return keyword in tokens_set
    else:
        # exact substring match in cleaned text for multi-word phrases
        return keyword in cleaned_text

def compute_record_metrics(cleaned_text: str, categories: dict):
    tokens = tokenize_cleaned(cleaned_text)
    tokens_set = set(tokens)
    category_scores = {}
    matched_pos_total = set()
    matched_neg_total = set()
    # Compute per category
    for cat, kv in categories.items():
        score = 0
        # positives
        pos_keys = kv.get("positive", {})
        for kw, wt in pos_keys.items():
            if match_keyword(cleaned_text, tokens_set, kw):
                score += wt
                matched_pos_total.add(kw)
        # negatives
        neg_keys = kv.get("negative", {})
        for kw, wt in neg_keys.items():
            if match_keyword(cleaned_text, tokens_set, kw):
                score -= wt
                matched_neg_total.add(kw)
        category_scores[cat] = score
    # assigned category
    if all(v == 0 for v in category_scores.values()):
        assigned = "Uncategorized"
    else:
        max_score = max(category_scores.values())
        # gather categories with max score
        best_cats = [c for c, v in category_scores.items() if v == max_score]
        assigned = sorted(best_cats)[0]
    # satisfaction score across all categories (count per category when duplicated across categories)
    satisfaction = 0
    for cat, kv in categories.items():
        for kw, wt in kv.get("positive", {}).items():
            if match_keyword(cleaned_text, tokens_set, kw):
                satisfaction += wt
        for kw, wt in kv.get("negative", {}).items():
            if match_keyword(cleaned_text, tokens_set, kw):
                satisfaction -= wt
    return {
        "category_scores": category_scores,
        "assigned_category": assigned,
        "satisfaction_score": satisfaction,
        "matched_positive_set": matched_pos_total,
        "matched_negative_set": matched_neg_total,
    }

def read_csv_with_header(p: Path):
    if not p.exists():
        return None, None
    try:
        with p.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return [], []
        header = rows[0]
        data = []
        for r in rows[1:]:
            if not any(field.strip() for field in r):
                continue
            # pad or trim to header length
            if len(r) < len(header):
                r = r + [""] * (len(header) - len(r))
            elif len(r) > len(header):
                r = r[:len(header)]
            data.append(dict(zip(header, r)))
        return header, data
    except Exception:
        return None, None

def parse_semicolon_list(s: str):
    if s is None:
        return set()
    parts = [x.strip() for x in s.split(";")]
    return set([x for x in parts if x != ""])

def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "segment_classification_file_structure": 0.0,
        "classification_rows_count_correct": 0.0,
        "classification_assigned_category_accuracy": 0.0,
        "classification_satisfaction_score_accuracy": 0.0,
        "classification_matched_positive_accuracy": 0.0,
        "classification_matched_negative_accuracy": 0.0,
        "top_segments_file_structure": 0.0,
        "top_segments_rank_and_content_accuracy": 0.0,
        "rewrite_top10_file_structure": 0.0,
        "rewrite_top10_ids_and_order_correct": 0.0,
        "rewrite_top10_length_and_format_compliance": 0.0,
    }

    # Load required inputs/gates
    tf_mod = load_text_filters_module(workspace)
    categories = parse_categories_yaml(workspace / "config" / "categories.yaml")
    r1_path = workspace / "input" / "transcripts_round1.jsonl"
    r2_path = workspace / "input" / "transcripts_round2.jsonl"
    r1 = safe_load_jsonl(r1_path)
    r2 = safe_load_jsonl(r2_path)

    if tf_mod is None or categories is None or r1 is None or r2 is None:
        # Cannot proceed with validation without core inputs
        return scores

    clean_text = tf_mod.clean_text

    # Build records
    all_records = []
    for obj in r1:
        if not isinstance(obj, dict):
            continue
        rid = obj.get("respondent_id")
        text = obj.get("text")
        if rid is None or text is None:
            continue
        all_records.append({
            "respondent_id": str(rid),
            "source_file": "input/transcripts_round1.jsonl",
            "text": str(text),
        })
    for obj in r2:
        if not isinstance(obj, dict):
            continue
        rid = obj.get("respondent_id")
        text = obj.get("text")
        if rid is None or text is None:
            continue
        all_records.append({
            "respondent_id": str(rid),
            "source_file": "input/transcripts_round2.jsonl",
            "text": str(text),
        })

    # Compute cleaned text and metrics
    expected_by_key = {}  # (respondent_id, source_file) -> metrics
    for rec in all_records:
        cleaned = clean_text(rec["text"])
        metrics = compute_record_metrics(cleaned, categories)
        metrics["text_cleaned"] = cleaned
        expected_by_key[(rec["respondent_id"], rec["source_file"])] = metrics

    N = len(all_records)

    # Validate outputs/segment_classification.csv
    seg_path = workspace / "outputs" / "segment_classification.csv"
    expected_header_seg = ["respondent_id", "source_file", "assigned_category", "satisfaction_score", "matched_positive", "matched_negative"]
    header, data = read_csv_with_header(seg_path)
    if header == expected_header_seg and data is not None:
        scores["segment_classification_file_structure"] = 1.0
        # Count rows correct (must equal N)
        if N > 0:
            scores["classification_rows_count_correct"] = 1.0 if len(data) == N else 0.0
        else:
            # If no records, structure is sufficient; count considered correct if file also has 0 rows
            scores["classification_rows_count_correct"] = 1.0 if len(data) == 0 else 0.0
        # Build lookup
        # Evaluate per-row correctness
        assigned_correct = 0
        satisfaction_correct = 0
        matched_pos_correct = 0
        matched_neg_correct = 0
        total_rows_for_content = 0
        # Also verify that all expected keys are present
        seen_keys = set()
        for row in data:
            rid = row.get("respondent_id", "")
            src = row.get("source_file", "")
            key = (rid, src)
            if key not in expected_by_key:
                # Unknown row; content checks will naturally not count it as correct
                continue
            exp = expected_by_key[key]
            total_rows_for_content += 1
            seen_keys.add(key)
            # assigned_category
            if row.get("assigned_category", "") == exp["assigned_category"]:
                assigned_correct += 1
            # satisfaction_score
            try:
                s_val = int(row.get("satisfaction_score", ""))
                if s_val == exp["satisfaction_score"]:
                    satisfaction_correct += 1
            except Exception:
                pass
            # matched lists as sets
            got_pos = parse_semicolon_list(row.get("matched_positive", ""))
            got_neg = parse_semicolon_list(row.get("matched_negative", ""))
            if got_pos == exp["matched_positive_set"]:
                matched_pos_correct += 1
            if got_neg == exp["matched_negative_set"]:
                matched_neg_correct += 1
        # Compute accuracies over expected number of records (N)
        denom = float(N) if N > 0 else 1.0
        scores["classification_assigned_category_accuracy"] = assigned_correct / denom
        scores["classification_satisfaction_score_accuracy"] = satisfaction_correct / denom
        scores["classification_matched_positive_accuracy"] = matched_pos_correct / denom
        scores["classification_matched_negative_accuracy"] = matched_neg_correct / denom
    else:
        # If file exists but malformed header, attempt to set row count to 0
        scores["segment_classification_file_structure"] = 0.0
        scores["classification_rows_count_correct"] = 0.0
        scores["classification_assigned_category_accuracy"] = 0.0
        scores["classification_satisfaction_score_accuracy"] = 0.0
        scores["classification_matched_positive_accuracy"] = 0.0
        scores["classification_matched_negative_accuracy"] = 0.0

    # Validate outputs/top_segments_ranked.csv
    top_path = workspace / "outputs" / "top_segments_ranked.csv"
    expected_header_top = ["respondent_id", "source_file", "assigned_category", "satisfaction_score", "text_cleaned"]
    header_t, data_t = read_csv_with_header(top_path)
    if header_t == expected_header_top and data_t is not None:
        scores["top_segments_file_structure"] = 1.0
        # Determine expected top K
        K = min(20, N)
        # Build list of tuples (rid, src, satisfaction)
        all_with_scores = []
        for rec in all_records:
            key = (rec["respondent_id"], rec["source_file"])
            met = expected_by_key[key]
            all_with_scores.append((rec["respondent_id"], rec["source_file"], met["satisfaction_score"]))
        # Sort by satisfaction desc
        all_with_scores_sorted = sorted(all_with_scores, key=lambda x: (-x[2], x[0], x[1]))
        # The sorted tie-breaker includes id and source to stabilize; used only for expected selection when N > K
        topK_expected = all_with_scores_sorted[:K]
        # Validate row count
        count_ok = (len(data_t) == K)
        # Validate content and order by non-increasing satisfaction_score
        order_ok = True
        included_set = set()
        content_ok_count = 0
        for i, row in enumerate(data_t):
            rid = row.get("respondent_id", "")
            src = row.get("source_file", "")
            key = (rid, src)
            if key not in expected_by_key:
                order_ok = False
                continue
            exp = expected_by_key[key]
            # satisfaction parse and match
            try:
                s_val = int(row.get("satisfaction_score", ""))
            except Exception:
                s_val = None
            # order check
            if i > 0:
                try:
                    prev_s = int(data_t[i-1].get("satisfaction_score", ""))
                    if s_val is None or prev_s < s_val:
                        order_ok = False
                except Exception:
                    order_ok = False
            # text_cleaned must match
            text_cleaned_ok = (row.get("text_cleaned", "") == exp["text_cleaned"])
            assigned_ok = (row.get("assigned_category", "") == exp["assigned_category"])
            satisfaction_ok = (s_val == exp["satisfaction_score"])
            if text_cleaned_ok and assigned_ok and satisfaction_ok:
                content_ok_count += 1
            included_set.add(key)
        # Check inclusion: when N <= K, included_set should equal all_records set
        all_keys_set = set([(rec["respondent_id"], rec["source_file"]) for rec in all_records])
        inclusion_ok = True
        if N <= K:
            inclusion_ok = (included_set == all_keys_set)
        else:
            # More general: ensure no record with score greater than the kth expected is missing
            kth_score = topK_expected[-1][2] if topK_expected else None
            # All records with score > kth must be included
            must_include = set([(rid, src) for (rid, src, sc) in all_with_scores_sorted if sc > kth_score])
            if not must_include.issubset(included_set):
                inclusion_ok = False
            # All included must have score >= kth
            for key in included_set:
                sc = expected_by_key[key]["satisfaction_score"]
                if sc < kth_score:
                    inclusion_ok = False
                    break
        if count_ok and order_ok and inclusion_ok and content_ok_count == len(data_t):
            scores["top_segments_rank_and_content_accuracy"] = 1.0
        else:
            scores["top_segments_rank_and_content_accuracy"] = 0.0
    else:
        scores["top_segments_file_structure"] = 0.0
        scores["top_segments_rank_and_content_accuracy"] = 0.0

    # Validate outputs/rewrite_top10.txt
    rewrite_path = workspace / "outputs" / "rewrite_top10.txt"
    if rewrite_path.exists():
        try:
            lines = rewrite_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            lines = None
        if lines is not None:
            scores["rewrite_top10_file_structure"] = 1.0
            # Determine expected negatives
            negatives = []
            for rec in all_records:
                key = (rec["respondent_id"], rec["source_file"])
                sc = expected_by_key[key]["satisfaction_score"]
                if sc < 0:
                    negatives.append((rec["respondent_id"], rec["source_file"], sc, rec["text"]))
            negatives_sorted = sorted(negatives, key=lambda x: (x[2], x[0], x[1]))  # most negative first
            M = min(10, len(negatives_sorted))
            # ids expected in order
            expected_ids_in_order = [rid for (rid, src, sc, txt) in negatives_sorted[:M]]
            # Validate line count
            ids_and_order_ok = True
            length_and_format_ok = True
            if len(lines) != M:
                ids_and_order_ok = False
                # still check whatever lines exist for format/length
            # Check per-line
            for idx in range(min(len(lines), M)):
                line = lines[idx]
                # length cap
                if len(line) > 160:
                    length_and_format_ok = False
                # format "respondent_id: rewritten_text"
                if ": " not in line:
                    length_and_format_ok = False
                    ids_and_order_ok = False
                    continue
                rid_part, rest = line.split(": ", 1)
                if rid_part != expected_ids_in_order[idx]:
                    ids_and_order_ok = False
                if rest.strip() == "":
                    length_and_format_ok = False
            # If M == 0, require file to have 0 lines
            if M == 0 and len(lines) != 0:
                ids_and_order_ok = False
            scores["rewrite_top10_ids_and_order_correct"] = 1.0 if ids_and_order_ok else 0.0
            scores["rewrite_top10_length_and_format_compliance"] = 1.0 if length_and_format_ok else 0.0
        else:
            scores["rewrite_top10_file_structure"] = 0.0
            scores["rewrite_top10_ids_and_order_correct"] = 0.0
            scores["rewrite_top10_length_and_format_compliance"] = 0.0
    else:
        # missing file
        scores["rewrite_top10_file_structure"] = 0.0
        scores["rewrite_top10_ids_and_order_correct"] = 0.0
        scores["rewrite_top10_length_and_format_compliance"] = 0.0

    return scores

def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()