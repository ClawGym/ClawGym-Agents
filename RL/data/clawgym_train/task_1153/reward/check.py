import json
import os
import sys
import re
import math
import csv

def round2_half_up(x, ndigits=2):
    factor = 10 ** ndigits
    return math.floor(x * factor + 0.5) / factor

def compute_metrics(text):
    # Lowercase for all computations where specified
    lower_text = text.lower()

    # Words: lowercase, split on whitespace
    words = lower_text.split()
    total_words = len(words)
    unique_words = len(set(words)) if total_words > 0 else 0

    # Simplified perplexity: 100 / (unique/total) = 100 * total / unique, capped at 100
    if total_words == 0 or unique_words == 0:
        perplexity = 100.0
    else:
        perplexity = 100.0 * total_words / unique_words
        if perplexity > 100.0:
            perplexity = 100.0

    # Burstiness: coefficient of variation of sentence lengths
    # Sentences split on . ! ? ; filter empty after trim
    sentences = [s for s in re.split(r'[.!?]+', text) if s.strip()]
    if len(sentences) < 2:
        burstiness = 0.0
    else:
        lengths = [len(s.split()) for s in sentences]
        if len(lengths) == 0:
            burstiness = 0.0
        else:
            avg = sum(lengths) / len(lengths)
            if avg == 0:
                burstiness = 0.0
            else:
                variance = sum((l - avg) ** 2 for l in lengths) / len(lengths)
                stddev = math.sqrt(variance)
                burstiness = stddev / avg
                if burstiness > 1.0:
                    burstiness = 1.0

    # Shannon entropy over all lowercase characters (including spaces and punctuation)
    chars = list(lower_text)
    total_chars = len(chars)
    if total_chars == 0:
        entropy = 0.0
    else:
        freq = {}
        for ch in chars:
            freq[ch] = freq.get(ch, 0) + 1
        entropy = 0.0
        for count in freq.values():
            p = count / total_chars
            entropy -= p * math.log2(p)

    # Token stats
    vocab_richness = (unique_words / total_words) if total_words > 0 else 0.0

    # Rounded outputs for reporting
    perplexity_r = round2_half_up(perplexity, 2)
    burstiness_r = round2_half_up(burstiness, 2)
    entropy_r = round2_half_up(entropy, 2)
    vocab_richness_r = round2_half_up(vocab_richness, 2)

    return {
        "perplexity_raw": perplexity,
        "burstiness_raw": burstiness,
        "entropy_raw": entropy,
        "perplexity": perplexity_r,
        "burstiness": burstiness_r,
        "entropy": entropy_r,
        "totalWords": total_words,
        "uniqueWords": unique_words,
        "vocabularyRichness": vocab_richness_r
    }

def compute_classification_and_confidence(perplexity_raw, burstiness_raw, entropy_raw, thresholds):
    # isAI: perplexity < threshold AND burstiness < threshold
    is_ai = (perplexity_raw < thresholds.get("perplexity", float('inf'))) and (burstiness_raw < thresholds.get("burstiness", float('inf')))
    # Confidence calculation
    perplexity_score = max(0.0, 1.0 - (perplexity_raw / 100.0))
    burstiness_score = max(0.0, 1.0 - (burstiness_raw / 0.5))
    entropy_score = 0.8 if (entropy_raw > 3.5 and entropy_raw < 5.0) else 0.4
    avg_score = (perplexity_score + burstiness_score + entropy_score) / 3.0
    conf = avg_score * 100.0
    # Half-up rounding to nearest integer
    conf_int = int(math.floor(conf + 0.5))
    # Clamp to [0,100]
    conf_int = max(0, min(100, conf_int))
    return is_ai, conf_int

def read_jsonl(path):
    items = []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                items.append(json.loads(s))
    except Exception:
        return None
    return items

def load_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return None

def parse_csv(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            rows = list(reader)
        return rows
    except Exception:
        return None

def to_bool_from_csv(s):
    if isinstance(s, bool):
        return s
    if s is None:
        return None
    ls = str(s).strip().lower()
    if ls == 'true':
        return True
    if ls == 'false':
        return False
    return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "results_json_exists_and_array": False,
        "results_entries_count_matches_input": False,
        "results_thresholds_fields_ok": False,
        "results_metrics_values_ok": False,
        "results_classification_ok": False,
        "results_confidence_ok": False,
        "results_short_text_handling_ok": False,
        "summary_csv_exists_and_header_ok": False,
        "summary_rows_count_ok": False,
        "summary_values_match_computed": False,
        "summary_consistent_with_results": False,
        "methodology_md_valid": False
    }

    # Load inputs
    articles_path = os.path.join(input_dir, "articles.jsonl")
    config_path = os.path.join(input_dir, "config.json")
    articles = read_jsonl(articles_path)
    config = load_json(config_path)

    if not isinstance(articles, list) or config is None or not isinstance(config, dict):
        # Cannot proceed without inputs; leave checks as False
        result = {"reward": 0.0}
        result.update(checks)
        print(json.dumps(result))
        return

    min_len = config.get("minTextLength")
    thr_perp = config.get("perplexityThreshold")
    thr_burst = config.get("burstinessThreshold")
    thresholds = {"perplexity": thr_perp, "burstiness": thr_burst}

    # Load outputs
    results_path = os.path.join(output_dir, "results.json")
    summary_path = os.path.join(output_dir, "summary.csv")
    methodology_path = os.path.join(output_dir, "methodology.md")

    results = load_json(results_path)
    if isinstance(results, list):
        checks["results_json_exists_and_array"] = True

    # Check results count matches input
    if checks["results_json_exists_and_array"]:
        if len(results) == len(articles):
            checks["results_entries_count_matches_input"] = True

    # Prepare expected computations
    analyzable_mask = []
    for art in articles:
        text = art.get("text", "")
        analyzable_mask.append(len(text) >= (min_len if isinstance(min_len, int) else 0))

    # Evaluate results.json content for metrics, thresholds, classification, confidence, and short-text handling
    thresholds_ok = True
    metrics_ok_all = True
    class_ok_all = True
    conf_ok_all = True
    short_ok = True
    results_ready = checks["results_json_exists_and_array"] and checks["results_entries_count_matches_input"]

    # Only proceed if results ready
    if results_ready:
        for idx, art in enumerate(articles):
            res = results[idx] if idx < len(results) else {}
            text = art.get("text", "")
            is_short = not analyzable_mask[idx]

            if is_short:
                # Short text handling: must include error with "short" and minLength equals config, and omit metrics/tokenStats
                err = res.get("error")
                min_len_field = res.get("minLength")
                # Only positively verify when fields present
                if (isinstance(err, str) and ("short" in err.lower())) and (min_len_field == min_len):
                    # Ensure metrics and tokenStats omitted
                    if ("metrics" in res) or ("tokenStats" in res):
                        short_ok = False
                else:
                    short_ok = False
                continue  # no further checks for short entries

            # For analyzable entries:
            # thresholds correctness
            th = res.get("thresholds", {})
            if not (isinstance(th, dict) and th.get("perplexity") == thr_perp and th.get("burstiness") == thr_burst):
                thresholds_ok = False

            # Compute expected metrics
            met = compute_metrics(text)
            # Compare metrics fields rounded to 2 decimals
            res_metrics = res.get("metrics", {})
            try:
                rp = float(res_metrics.get("perplexity"))
                rb = float(res_metrics.get("burstiness"))
                re_ = float(res_metrics.get("entropy"))
            except Exception:
                metrics_ok_all = False
                # Still compute further checks to collect more failures
                rp = rb = re_ = None

            if rp is None or rb is None or re_ is None:
                metrics_ok_all = False
            else:
                if not (round2_half_up(rp, 2) == met["perplexity"] and round2_half_up(rb, 2) == met["burstiness"] and round2_half_up(re_, 2) == met["entropy"]):
                    metrics_ok_all = False

            # Token stats
            ts = res.get("tokenStats", {})
            try:
                tw = int(ts.get("totalWords"))
                uw = int(ts.get("uniqueWords"))
                vr = float(ts.get("vocabularyRichness"))
            except Exception:
                metrics_ok_all = False
                tw = uw = None
                vr = None
            if tw is None or uw is None or vr is None:
                metrics_ok_all = False
            else:
                if not (tw == met["totalWords"] and uw == met["uniqueWords"] and round2_half_up(vr, 2) == met["vocabularyRichness"]):
                    metrics_ok_all = False

            # Classification
            is_ai_exp, conf_exp = compute_classification_and_confidence(met["perplexity_raw"], met["burstiness_raw"], met["entropy_raw"], thresholds)
            is_ai_res = res.get("isAI")
            if isinstance(is_ai_res, bool):
                if is_ai_res != is_ai_exp:
                    class_ok_all = False
            else:
                class_ok_all = False

            # Confidence
            try:
                conf_res = int(res.get("confidence"))
            except Exception:
                conf_res = None
            if conf_res is None or conf_res != conf_exp:
                conf_ok_all = False

        # If there are no short entries, consider short handling check as True (not applicable)
        if any(not m for m in analyzable_mask):
            checks["results_short_text_handling_ok"] = short_ok and results_ready
        else:
            # No short texts present; requirement not applicable but pass to avoid penalizing
            checks["results_short_text_handling_ok"] = results_ready

        checks["results_thresholds_fields_ok"] = thresholds_ok and results_ready
        checks["results_metrics_values_ok"] = metrics_ok_all and results_ready
        checks["results_classification_ok"] = class_ok_all and results_ready
        checks["results_confidence_ok"] = conf_ok_all and results_ready

    # Check summary.csv
    rows = parse_csv(summary_path)
    header_expected = "id,title,isAI,confidence,perplexity,burstiness,entropy,totalWords,uniqueWords,vocabularyRichness"
    if rows is not None and len(rows) >= 1:
        header_row = ",".join(rows[0])
        if header_row == header_expected:
            checks["summary_csv_exists_and_header_ok"] = True

    # Validate rows count (excluding header) equals number of analyzable samples
    if checks["summary_csv_exists_and_header_ok"]:
        data_rows = rows[1:]
        analyzable_count = sum(1 for m in analyzable_mask if m)
        if len(data_rows) == analyzable_count:
            checks["summary_rows_count_ok"] = True

        # Validate values match computed and match results.json
        values_match = True
        consistent_with_results = True
        # Iterate analyzable samples in input order
        expected_indices = [i for i, m in enumerate(analyzable_mask) if m]
        for j, i in enumerate(expected_indices):
            art = articles[i]
            text = art.get("text", "")
            met = compute_metrics(text)
            is_ai_exp, conf_exp = compute_classification_and_confidence(met["perplexity_raw"], met["burstiness_raw"], met["entropy_raw"], thresholds)

            row = data_rows[j] if j < len(data_rows) else None
            if row is None or len(row) != 10:
                values_match = False
                consistent_with_results = False
                break
            id_str, title_str, isai_str, conf_str, per_str, bur_str, ent_str, tw_str, uw_str, vr_str = row

            # Compare id and title as strings to input
            if str(id_str) != str(art.get("id")) or str(title_str) != str(art.get("title")):
                values_match = False

            # Parse and compare values
            isai_val = to_bool_from_csv(isai_str)
            try:
                conf_val = int(conf_str)
                per_val = float(per_str)
                bur_val = float(bur_str)
                ent_val = float(ent_str)
                tw_val = int(tw_str)
                uw_val = int(uw_str)
                vr_val = float(vr_str)
            except Exception:
                values_match = False
                isai_val = None
                conf_val = None
                per_val = bur_val = ent_val = tw_val = uw_val = vr_val = None

            if isai_val is None or isai_val != is_ai_exp:
                values_match = False
            if conf_val is None or conf_val != conf_exp:
                values_match = False
            if per_val is None or round2_half_up(per_val, 2) != met["perplexity"]:
                values_match = False
            if bur_val is None or round2_half_up(bur_val, 2) != met["burstiness"]:
                values_match = False
            if ent_val is None or round2_half_up(ent_val, 2) != met["entropy"]:
                values_match = False
            if tw_val is None or tw_val != met["totalWords"]:
                values_match = False
            if uw_val is None or uw_val != met["uniqueWords"]:
                values_match = False
            if vr_val is None or round2_half_up(vr_val, 2) != met["vocabularyRichness"]:
                values_match = False

            # Consistency with results.json
            if results_ready and i < len(results):
                r = results[i]
                if analyzable_mask[i]:
                    # Compare to results fields
                    r_isai = r.get("isAI")
                    r_conf = r.get("confidence")
                    r_metrics = r.get("metrics", {})
                    r_ts = r.get("tokenStats", {})
                    try:
                        r_per = float(r_metrics.get("perplexity"))
                        r_bur = float(r_metrics.get("burstiness"))
                        r_ent = float(r_metrics.get("entropy"))
                        r_tw = int(r_ts.get("totalWords"))
                        r_uw = int(r_ts.get("uniqueWords"))
                        r_vr = float(r_ts.get("vocabularyRichness"))
                    except Exception:
                        consistent_with_results = False
                        r_isai = None
                        r_conf = None
                        r_per = r_bur = r_ent = r_tw = r_uw = r_vr = None

                    if r_isai is None or to_bool_from_csv(isai_str) != r_isai:
                        consistent_with_results = False
                    try:
                        if int(conf_str) != int(r_conf):
                            consistent_with_results = False
                    except Exception:
                        consistent_with_results = False
                    # Compare rounded numeric metrics
                    if r_per is None or round2_half_up(float(per_str), 2) != round2_half_up(r_per, 2):
                        consistent_with_results = False
                    if r_bur is None or round2_half_up(float(bur_str), 2) != round2_half_up(r_bur, 2):
                        consistent_with_results = False
                    if r_ent is None or round2_half_up(float(ent_str), 2) != round2_half_up(r_ent, 2):
                        consistent_with_results = False
                    if r_tw is None or int(tw_str) != r_tw:
                        consistent_with_results = False
                    if r_uw is None or int(uw_str) != r_uw:
                        consistent_with_results = False
                    if r_vr is None or round2_half_up(float(vr_str), 2) != round2_half_up(r_vr, 2):
                        consistent_with_results = False
                else:
                    # Should not be in CSV if not analyzable; handled by rows_count_ok
                    pass

        if values_match:
            checks["summary_values_match_computed"] = True
        if consistent_with_results and results_ready:
            checks["summary_consistent_with_results"] = True

    # Validate methodology.md
    methodology = read_text(methodology_path)
    if methodology is not None:
        text_lower = methodology.lower()
        # Word count between 150 and 300
        words = methodology.split()
        has_length = 150 <= len(words) <= 300
        has_terms = ("perplexity" in text_lower) and ("burstiness" in text_lower) and ("entropy" in text_lower)
        has_risk = any(term in text_lower for term in ["risk", "limitations", "false positive", "false negatives", "false negative", "false positives"])
        if has_length and has_terms and has_risk:
            checks["methodology_md_valid"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # No-op baseline: if output directory missing or required artifacts missing, reward must be 0.0
    # If none of the key output files exist, ensure reward is 0.0
    required_any = checks["results_json_exists_and_array"] or checks["summary_csv_exists_and_header_ok"] or checks["methodology_md_valid"]
    if not required_any:
        reward = 0.0

    # Print final JSON
    out = {"reward": reward}
    out.update(checks)
    print(json.dumps(out))

if __name__ == "__main__":
    main()