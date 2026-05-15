#!/usr/bin/env python3
import sys
import json
import re
import os

def load_text(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

def main():
    if len(sys.argv) != 5:
        print("Usage: python3 scripts/validate_posts.py <captions_md> <banned_terms_txt> <config_json> <output_report_json>")
        sys.exit(2)

    captions_md = sys.argv[1]
    banned_terms_txt = sys.argv[2]
    config_json = sys.argv[3]
    output_json = sys.argv[4]

    captions_raw = load_text(captions_md)
    with open(banned_terms_txt, 'r', encoding='utf-8') as f:
        banned_terms = [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]
    with open(config_json, 'r', encoding='utf-8') as f:
        config = json.load(f)

    allowed_emojis = config.get("allowed_emojis", [])
    min_chars = int(config.get("min_chars", 0))
    max_chars = int(config.get("max_chars", 10**9))
    required_disclaimer = str(config.get("required_disclaimer", "")).strip()

    split_token = "\n---\n"
    if split_token in captions_raw:
        captions_list = [c.strip() for c in captions_raw.split(split_token)]
    else:
        captions_list = [captions_raw.strip()] if captions_raw.strip() else []

    report = {"total_captions": len(captions_list), "captions": []}
    overall_pass = True

    for idx, cap in enumerate(captions_list, start=1):
        char_count = len(cap)
        emoji_count = sum(cap.count(e) for e in allowed_emojis)
        disclaimer_count = cap.count(required_disclaimer) if required_disclaimer else 0

        banned_found = []
        for term in banned_terms:
            if not term:
                continue
            pattern = r'\b' + re.escape(term) + r'\b'
            if re.search(pattern, cap, flags=re.IGNORECASE):
                banned_found.append(term)

        violations = []
        if char_count < min_chars or char_count > max_chars:
            violations.append(f"char_count_out_of_range:{char_count}")
        if emoji_count < 1 or emoji_count > 2:
            violations.append(f"emoji_count_out_of_range:{emoji_count}")
        if required_disclaimer:
            if disclaimer_count != 1:
                violations.append(f"disclaimer_count:{disclaimer_count}")
        if banned_found:
            violations.append("banned_terms:" + ",".join(sorted(set(banned_found))))

        status = "pass" if not violations else "fail"
        if status == "fail":
            overall_pass = False

        report["captions"].append({
            "index": idx,
            "char_count": char_count,
            "emoji_count": emoji_count,
            "has_required_disclaimer": disclaimer_count == 1,
            "disclaimer_count": disclaimer_count,
            "banned_terms_found": sorted(list(set(banned_found))),
            "status": status,
            "violations": violations
        })

    report["violations_count"] = sum(1 for c in report["captions"] if c["status"] == "fail")
    # Require exactly three captions to pass overall
    report["overall_status"] = "pass" if overall_pass and report["total_captions"] == 3 else "fail"

    os.makedirs(os.path.dirname(output_json) or '.', exist_ok=True)
    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
