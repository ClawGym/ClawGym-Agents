import json
import os
import sys
import csv
from datetime import datetime
import re
from typing import List, Dict, Any, Tuple

def read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def read_jsonl(path: str) -> List[Dict[str, Any]]:
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    items.append(obj)
            except Exception:
                continue
    return items

def parse_iso_date(date_str: str) -> datetime:
    # Attempt robust ISO parsing, allowing Z and various formats.
    s = date_str.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        # Try fromisoformat
        return datetime.fromisoformat(s)
    except Exception:
        pass
    # Common patterns
    fmts = [
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S.%f",
    ]
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    # Fallback: take first 10 chars as date
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d")
    except Exception:
        # As a last resort, return epoch
        return datetime.fromtimestamp(0)

POSITIVE_KEYWORDS = [
    "love","great","amazing","awesome","excellent","perfect","best","fantastic",
    "wonderful","recommend","happy","satisfied","quality","worth","impressed",
    "reliable","favorite","brilliant","superb"
]
NEGATIVE_KEYWORDS = [
    "hate","terrible","awful","worst","bad","horrible","disappointed","waste",
    "scam","fake","poor","broken","useless","regret","avoid","never","refund",
    "complaint","problem","issue","sucks"
]
CRISIS_KEYWORDS = [
    "lawsuit","recall","investigation","fraud","scandal","danger","safety",
    "warning","banned","illegal","death","injury","toxic"
]

def sentiment_of(text: str) -> str:
    t = (text or "").lower()
    pos = 0
    neg = 0
    for kw in POSITIVE_KEYWORDS:
        if kw in t:
            pos += 1
    for kw in NEGATIVE_KEYWORDS:
        if kw in t:
            neg += 1
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"

def compute_brand_stats(mentions: List[Dict[str, Any]]) -> Dict[str, Any]:
    platforms = ["reddit","google_news","youtube","duckduckgo"]
    counts_by_platform = {p: 0 for p in platforms}
    sentiments = {"positive": 0, "neutral": 0, "negative": 0}
    total = 0
    influential_negative_exists = False
    crisis_exists = False

    for m in mentions:
        total += 1
        platform = (m.get("platform") or "").lower()
        if platform in counts_by_platform:
            counts_by_platform[platform] += 1
        s = sentiment_of(m.get("content",""))
        sentiments[s] += 1
        if s == "negative":
            try:
                engagement = int(m.get("engagement", 0))
            except Exception:
                engagement = 0
            if engagement > 1000:
                influential_negative_exists = True
        # crisis detection
        text = (m.get("content") or "").lower()
        for kw in CRISIS_KEYWORDS:
            if kw in text:
                crisis_exists = True
                break

    neg_ratio = (sentiments["negative"]/total) if total > 0 else 0.0
    # percentages:
    if total > 0:
        pos_pct = sentiments["positive"] / total * 100.0
        neu_pct = sentiments["neutral"] / total * 100.0
        neg_pct = sentiments["negative"] / total * 100.0
    else:
        pos_pct = neu_pct = neg_pct = 0.0

    return {
        "total": total,
        "counts_by_platform": counts_by_platform,
        "sentiments": sentiments,
        "percentages": {"positive": pos_pct, "neutral": neu_pct, "negative": neg_pct},
        "neg_ratio": neg_ratio,
        "influential_negative_exists": influential_negative_exists,
        "crisis_exists": crisis_exists
    }

def is_valid_iso_date(s: str) -> bool:
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except Exception:
        return False

def read_csv_rows(path: str) -> List[List[str]]:
    with open(path, "r", encoding="utf-8") as f:
        rdr = csv.reader(f)
        return [row for row in rdr]

def parse_keywords_csv(path: str) -> Tuple[bool, List[Tuple[str,int]]]:
    try:
        rows = read_csv_rows(path)
    except Exception:
        return False, []
    if not rows:
        return False, []
    header = [h.strip().lower() for h in rows[0]]
    if header != ["keyword","frequency"]:
        return False, []
    data = []
    for r in rows[1:]:
        if len(r) != 2:
            return False, []
        kw = r[0].strip().lower()
        try:
            freq = int(str(r[1]).strip())
        except Exception:
            return False, []
        data.append((kw, freq))
    return True, data

def parse_trend_csv(path: str) -> Tuple[bool, List[Tuple[str,int]]]:
    try:
        rows = read_csv_rows(path)
    except Exception:
        return False, []
    if not rows:
        return False, []
    header = [h.strip().lower() for h in rows[0]]
    if header != ["date","count"]:
        return False, []
    data = []
    for r in rows[1:]:
        if len(r) != 2:
            return False, []
        date_s = r[0].strip()
        if not is_valid_iso_date(date_s):
            return False, []
        try:
            cnt = int(str(r[1]).strip())
        except Exception:
            return False, []
        data.append((date_s, cnt))
    return True, data

def get_text_contains_keywords(mentions: List[Dict[str, Any]], keywords: List[str]) -> Dict[str, bool]:
    flags = {k: False for k in keywords}
    for m in mentions:
        text = (m.get("content") or "").lower()
        for k in keywords:
            if k.lower() in text:
                flags[k] = True
    return flags

def extract_competitor_counts(comp_mentions: List[Dict[str, Any]], competitors: List[str]) -> Dict[str, int]:
    counts = {c: 0 for c in competitors}
    for m in comp_mentions:
        name = m.get("brand") or m.get("competitor") or ""
        name = str(name)
        # exact match against provided competitor list
        if name in counts:
            counts[name] += 1
    return counts

def build_checks_result(checks: Dict[str, bool], applicable_mask: Dict[str, bool]) -> float:
    # Reward is average of applicable checks that depend on outputs; if none applicable or no outputs, reward 0.0
    applicable_keys = [k for k, applicable in applicable_mask.items() if applicable]
    if not applicable_keys:
        return 0.0
    true_count = sum(1 for k in applicable_keys if checks.get(k, False))
    return true_count / len(applicable_keys)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir = os.path.join(workspace_root, "reward")  # not used in checks

    # Initialize checks
    checks: Dict[str, bool] = {
        "has_summary_json": False,
        "summary_brand_matches": False,
        "summary_total_mentions_correct": False,
        "summary_platform_counts_correct": False,
        "summary_sentiment_breakdown_valid": False,

        "has_alerts_json": False,
        "alert_high_negative_present": False,
        "alert_influential_negative_present": False,
        "alert_crisis_present": False,

        "has_keywords_csv": False,
        "keywords_format_valid": False,
        "keywords_contains_shipping_quality_if_applicable": False,

        "has_trend_csv": False,
        "trend_format_valid": False,
        "trend_seven_rows": False,
        "trend_total_matches_summary": False,

        "has_competitors_json": False,
        "competitors_include_all": False,
        "competitors_share_of_voice_valid": False,

        "has_report_md": False,
        "report_contains_header_and_platforms": False,
    }

    # Applicable mask: which checks count into reward denominator
    applicable: Dict[str, bool] = {k: True for k in checks.keys()}

    # Load inputs
    brand_cfg_path = os.path.join(input_dir, "brand_config.json")
    mentions_path = os.path.join(input_dir, "mentions.jsonl")
    competitor_mentions_path = os.path.join(input_dir, "competitor_mentions.jsonl")

    try:
        brand_cfg = read_json(brand_cfg_path)
    except Exception:
        brand_cfg = {}
    brand_name = brand_cfg.get("brand")
    competitors = brand_cfg.get("competitors", []) if isinstance(brand_cfg.get("competitors", []), list) else []
    platforms_cfg = brand_cfg.get("platforms", []) if isinstance(brand_cfg.get("platforms", []), list) else []

    mentions = []
    try:
        mentions = read_jsonl(mentions_path)
    except Exception:
        mentions = []
    comp_mentions = []
    try:
        comp_mentions = read_jsonl(competitor_mentions_path)
    except Exception:
        comp_mentions = []

    # Compute expected stats from inputs
    brand_stats = compute_brand_stats(mentions)
    total_mentions = brand_stats["total"]
    counts_by_platform = brand_stats["counts_by_platform"]
    sentiments_counts = brand_stats["sentiments"]
    percents = brand_stats["percentages"]
    neg_ratio = brand_stats["neg_ratio"]
    influential_negative_exists = brand_stats["influential_negative_exists"]
    crisis_exists = brand_stats["crisis_exists"]

    # Conditions for alerts applicability
    requires_high_negative_alert = (total_mentions > 0 and neg_ratio > 0.4)
    requires_influential_alert = influential_negative_exists
    requires_crisis_alert = crisis_exists

    # Map applicability for alert checks: only applicable if expected by input data
    applicable["alert_high_negative_present"] = requires_high_negative_alert
    applicable["alert_influential_negative_present"] = requires_influential_alert
    applicable["alert_crisis_present"] = requires_crisis_alert

    # Verify output files existence
    summary_path = os.path.join(output_dir, "summary.json")
    alerts_path = os.path.join(output_dir, "alerts.json")
    keywords_path = os.path.join(output_dir, "keywords.csv")
    trend_path = os.path.join(output_dir, "trend.csv")
    competitors_out_path = os.path.join(output_dir, "competitors.json")
    report_path = os.path.join(output_dir, "report.md")

    # summary.json checks
    if os.path.isfile(summary_path):
        checks["has_summary_json"] = True
        try:
            summary = read_json(summary_path)
        except Exception:
            summary = {}

        # brand matches
        if summary.get("brand") == brand_name and isinstance(summary.get("brand"), str):
            checks["summary_brand_matches"] = True

        # total mentions matches
        if isinstance(summary.get("total_mentions"), int) and summary.get("total_mentions") == total_mentions:
            checks["summary_total_mentions_correct"] = True

        # platform counts correct
        mentions_by_platform = summary.get("mentions_by_platform")
        needed_keys = ["reddit","google_news","youtube","duckduckgo"]
        platform_counts_ok = False
        if isinstance(mentions_by_platform, dict) and all(k in mentions_by_platform for k in needed_keys):
            platform_counts_ok = True
            for k in needed_keys:
                if not isinstance(mentions_by_platform.get(k), int):
                    platform_counts_ok = False
                    break
                if mentions_by_platform.get(k) != counts_by_platform.get(k, 0):
                    platform_counts_ok = False
                    break
        if platform_counts_ok:
            checks["summary_platform_counts_correct"] = True

        # sentiment breakdown: percentages sum and match tolerance
        sb = summary.get("sentiment_breakdown")
        def close(a: float, b: float, tol: float = 2.0) -> bool:
            try:
                return abs(float(a) - float(b)) <= tol
            except Exception:
                return False
        if isinstance(sb, dict) and all(k in sb for k in ["positive","neutral","negative"]):
            try:
                pos_r = float(sb["positive"])
                neu_r = float(sb["neutral"])
                neg_r = float(sb["negative"])
                ssum = pos_r + neu_r + neg_r
                sum_ok = abs(ssum - 100.0) <= 1.0
                match_ok = close(pos_r, percents["positive"]) and close(neu_r, percents["neutral"]) and close(neg_r, percents["negative"])
                if sum_ok and match_ok:
                    checks["summary_sentiment_breakdown_valid"] = True
            except Exception:
                pass

    # alerts.json checks
    if os.path.isfile(alerts_path):
        checks["has_alerts_json"] = True
        try:
            alerts = read_json(alerts_path)
        except Exception:
            alerts = []
        if isinstance(alerts, list):
            # Normalize textual fields to lowercase for search
            def alert_text_fields(a: Dict[str, Any]) -> str:
                parts = []
                for key in ["title","description","trigger","level"]:
                    v = a.get(key)
                    if isinstance(v, str):
                        parts.append(v.lower())
                return " | ".join(parts)

            # High negative ratio alert (critical)
            if requires_high_negative_alert:
                for a in alerts:
                    if isinstance(a, dict) and str(a.get("level","")).lower() == "critical":
                        t = alert_text_fields(a)
                        # Look for indications of negative ratio threshold
                        if ("negative" in t and ("ratio" in t or "0.4" in t or "40" in t or "40%" in t)):
                            checks["alert_high_negative_present"] = True
                            break

            # Influential negative alert (critical, engagement > 1000)
            if requires_influential_alert:
                for a in alerts:
                    if isinstance(a, dict) and str(a.get("level","")).lower() == "critical":
                        t = alert_text_fields(a)
                        if ("influential" in t) or ("engagement" in t) or ("1000" in t):
                            checks["alert_influential_negative_present"] = True
                            break

            # Crisis keyword alert (critical)
            if requires_crisis_alert:
                for a in alerts:
                    if isinstance(a, dict) and str(a.get("level","")).lower() == "critical":
                        t = alert_text_fields(a)
                        if ("crisis" in t) or ("keyword" in t) or ("detected" in t):
                            checks["alert_crisis_present"] = True
                            break

    # keywords.csv checks
    if os.path.isfile(keywords_path):
        checks["has_keywords_csv"] = True
        fmt_ok, data = parse_keywords_csv(keywords_path)
        if fmt_ok:
            checks["keywords_format_valid"] = True
            # Should list top 8 keywords -> expect exactly 8 rows (not counting header)
            if len(data) == 8:
                # if shipping/quality occur in mentions, ensure they appear in csv
                flags = get_text_contains_keywords(mentions, ["shipping","quality"])
                ok = True
                for k, present in flags.items():
                    if present:
                        # must exist in CSV
                        if all(kw != k for kw, _ in data):
                            ok = False
                            break
                if ok:
                    checks["keywords_contains_shipping_quality_if_applicable"] = True

    # trend.csv checks
    if os.path.isfile(trend_path):
        checks["has_trend_csv"] = True
        fmt_ok, trend_rows = parse_trend_csv(trend_path)
        if fmt_ok:
            checks["trend_format_valid"] = True
            if len(trend_rows) == 7:
                checks["trend_seven_rows"] = True
            # sum equals total_mentions in summary (if summary exists) else fallback to computed total
            trend_sum = sum(cnt for _, cnt in trend_rows)
            target_total = total_mentions
            if checks["has_summary_json"]:
                try:
                    s = read_json(summary_path)
                    if isinstance(s.get("total_mentions"), int):
                        target_total = s["total_mentions"]
                except Exception:
                    pass
            if trend_sum == target_total:
                checks["trend_total_matches_summary"] = True

    # competitors.json checks
    if os.path.isfile(competitors_out_path):
        checks["has_competitors_json"] = True
        try:
            comp_out = read_json(competitors_out_path)
        except Exception:
            comp_out = []
        if isinstance(comp_out, list):
            # include all competitors
            out_names = set()
            for c in comp_out:
                if isinstance(c, dict) and "name" in c:
                    out_names.add(c["name"])
            if set(competitors).issubset(out_names):
                checks["competitors_include_all"] = True
            # share of voice within tolerance
            # compute expected sov per competitor
            comp_counts = extract_competitor_counts(comp_mentions, competitors)
            sov_ok = True
            for name in competitors:
                comp_ct = comp_counts.get(name, 0)
                denom = total_mentions + comp_ct
                expected_sov = (comp_ct / denom) if denom > 0 else 0.0
                # find in comp_out
                found = False
                reported = None
                for c in comp_out:
                    if isinstance(c, dict) and c.get("name") == name and isinstance(c.get("share_of_voice"), (int, float)):
                        found = True
                        reported = float(c["share_of_voice"])
                        break
                if not found:
                    sov_ok = False
                    break
                if abs(reported - expected_sov) > 0.05:
                    sov_ok = False
                    break
            if sov_ok and checks["competitors_include_all"]:
                checks["competitors_share_of_voice_valid"] = True

    # report.md checks
    if os.path.isfile(report_path):
        checks["has_report_md"] = True
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                report_txt = f.read()
        except Exception:
            report_txt = ""
        lower = report_txt.lower()
        header_ok = ("brand monitoring report" in lower)
        platforms_ok = all(p in lower for p in ["reddit","google_news","youtube","duckduckgo"])
        if header_ok and platforms_ok:
            checks["report_contains_header_and_platforms"] = True

    # Determine applicability of checks that depend on outputs
    # For non-existent files, the checks remain applicable to ensure missing outputs reduce reward,
    # except alert checks which are only applicable if the triggering condition exists.
    # Prepare denominator keys
    applicable_mask = applicable.copy()

    # If absolutely no outputs exist, reward must be 0.0
    required_outputs = [summary_path, alerts_path, keywords_path, trend_path, competitors_out_path, report_path]
    any_output_exists = any(os.path.isfile(p) for p in required_outputs)
    if not any_output_exists:
        reward = 0.0
    else:
        reward = build_checks_result(checks, applicable_mask)

    # Print result JSON
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()