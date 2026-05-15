import json
import os
import sys
import re

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return None

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return json.load(f)
    except Exception:
        return None

def word_count(text):
    return len(re.findall(r"\S+", text)) if text else 0

def is_int_like(val):
    return isinstance(val, int) and not isinstance(val, bool)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    newsletter_path = os.path.join(output_dir, "newsletter", "issue-17.md")
    subjects_path = os.path.join(output_dir, "newsletter", "subject-lines.json")
    linkedin_path = os.path.join(output_dir, "social", "linkedin-issue-17.md")
    qc_path = os.path.join(output_dir, "reports", "quality-check.json")

    # Initialize checks
    checks = {
        # Newsletter checks
        "newsletter_exists": False,
        "newsletter_has_sections": False,
        "newsletter_exactly_one_cta": False,
        "newsletter_no_banned_phrases": False,
        "newsletter_has_digit": False,

        # Subject lines checks
        "subjects_exists": False,
        "subjects_valid_json": False,
        "subjects_len_5": False,
        "subjects_schema_valid": False,
        "subjects_unique_and_length": False,
        "subjects_scores_valid": False,
        "subjects_risk_level_valid": False,
        "subjects_two_top_picks": False,

        # LinkedIn checks
        "linkedin_exists": False,
        "linkedin_word_count_ok": False,
        "linkedin_no_hashtags": False,
        "linkedin_ends_with_question": False,

        # Quality check JSON checks
        "qc_exists": False,
        "qc_valid_json_and_keys": False,
        "qc_one_cta_only_true_and_consistent": False,
        "qc_no_filler_true_and_consistent": False,
        "qc_concrete_example_true_and_consistent": False,
        "qc_word_count_within_20pct": False,
        "qc_passive_voice_percent_range": False,
        "qc_banned_words_found_empty": False,
    }

    # Constants
    required_sections = ["HOOK", "MAIN CONTENT", "PRACTICAL TAKEAWAY", "CLOSING"]
    banned_phrases = [
        "leverage",
        "synergy",
        "unlock your potential",
        "it's important to note that",
        "in today's fast-paced world",
        "certainly!",
        "great question!",
    ]
    allowed_risk = {"Low", "Med", "High"}

    # 1) Newsletter checks
    newsletter_text = None
    if os.path.isfile(newsletter_path):
        checks["newsletter_exists"] = True
        newsletter_text = read_text_file(newsletter_path)
        if newsletter_text is None:
            newsletter_text = ""
        # Sections present
        if all(sec in newsletter_text for sec in required_sections):
            checks["newsletter_has_sections"] = True

        # Exactly one CTA line labeled "CTA:" (case-sensitive), where a line stripped equals "CTA:"
        cta_count = 0
        for line in newsletter_text.splitlines():
            if line.strip() == "CTA:":
                cta_count += 1
        if cta_count == 1:
            checks["newsletter_exactly_one_cta"] = True

        # No banned phrases (case-insensitive)
        lower_news = newsletter_text.lower()
        found_any_banned = any(phrase.lower() in lower_news for phrase in banned_phrases)
        if not found_any_banned:
            checks["newsletter_no_banned_phrases"] = True

        # At least one digit
        if re.search(r"\d", newsletter_text) is not None:
            checks["newsletter_has_digit"] = True

    # 2) Subject lines checks
    subjects_data = None
    if os.path.isfile(subjects_path):
        checks["subjects_exists"] = True
        subjects_data = load_json_file(subjects_path)
        if isinstance(subjects_data, list):
            checks["subjects_valid_json"] = True

            # Length = 5
            if len(subjects_data) == 5:
                checks["subjects_len_5"] = True

            # Schema and per-item validation
            schema_ok = True
            texts = []
            lengths_ok = True
            scores_ok = True
            risk_ok = True
            top_picks = 0
            top_pick_bools_ok = True

            for item in subjects_data if isinstance(subjects_data, list) else []:
                # Basic schema
                if not isinstance(item, dict):
                    schema_ok = False
                    break
                if "text" not in item or "scores" not in item or "risk_level" not in item or "top_pick" not in item:
                    schema_ok = False
                    break
                if not isinstance(item["text"], str):
                    schema_ok = False
                    break
                if not isinstance(item["scores"], dict):
                    schema_ok = False
                    break
                if not isinstance(item["risk_level"], str):
                    schema_ok = False
                    break
                if not isinstance(item["top_pick"], bool):
                    schema_ok = False
                    top_pick_bools_ok = False
                    break

                # Collect text and length check (trimmed length <= 50)
                txt = item["text"].strip()
                texts.append(txt)
                if len(txt) > 50:
                    lengths_ok = False

                # Scores validation: integers 1-10
                s = item["scores"]
                for k in ["open_rate_appeal", "clarity", "brand_fit"]:
                    if k not in s or not is_int_like(s[k]) or not (1 <= s[k] <= 10):
                        scores_ok = False
                        break

                # Risk level
                if item["risk_level"] not in allowed_risk:
                    risk_ok = False

                # Count top picks
                if item["top_pick"] is True:
                    top_picks += 1

            if schema_ok:
                checks["subjects_schema_valid"] = True
            if schema_ok and lengths_ok and len(texts) == len(set(texts)):
                checks["subjects_unique_and_length"] = True
            if schema_ok and scores_ok:
                checks["subjects_scores_valid"] = True
            if schema_ok and risk_ok:
                checks["subjects_risk_level_valid"] = True
            if schema_ok and top_pick_bools_ok and top_picks == 2:
                checks["subjects_two_top_picks"] = True

    # 3) LinkedIn post checks
    linkedin_text = None
    if os.path.isfile(linkedin_path):
        checks["linkedin_exists"] = True
        linkedin_text = read_text_file(linkedin_path)
        if linkedin_text is None:
            linkedin_text = ""
        # Word count between 150 and 250 inclusive
        wc = word_count(linkedin_text)
        if 150 <= wc <= 250:
            checks["linkedin_word_count_ok"] = True
        # No '#' characters
        if "#" not in linkedin_text:
            checks["linkedin_no_hashtags"] = True
        # Last non-whitespace char is '?'
        stripped = linkedin_text.rstrip()
        if stripped.endswith("?"):
            checks["linkedin_ends_with_question"] = True

    # 4) Quality check JSON consistency checks
    qc_data = None
    if os.path.isfile(qc_path):
        checks["qc_exists"] = True
        qc_data = load_json_file(qc_path)
        if isinstance(qc_data, dict):
            # Validate required keys and types
            required_bool_keys = [
                "voice_match",
                "no_filler_phrases",
                "opening_strength",
                "active_voice",
                "paragraph_length",
                "one_cta_only",
                "concrete_example_present",
                "ending_lands",
            ]
            keys_ok = all(k in qc_data for k in required_bool_keys + ["word_count", "passive_voice_estimate_percent", "banned_words_found"])
            types_ok = True
            if keys_ok:
                for k in required_bool_keys:
                    if not isinstance(qc_data.get(k), bool):
                        types_ok = False
                        break
                # word_count int > 0
                wc_val = qc_data.get("word_count")
                if not is_int_like(wc_val) or wc_val <= 0:
                    types_ok = False
                # passive_voice_estimate_percent number (int or float)
                pv = qc_data.get("passive_voice_estimate_percent")
                if not (isinstance(pv, (int, float)) and not isinstance(pv, bool)):
                    types_ok = False
                # banned_words_found list of strings
                bwf = qc_data.get("banned_words_found")
                if not isinstance(bwf, list) or any(not isinstance(x, str) for x in bwf):
                    types_ok = False

            if keys_ok and types_ok:
                checks["qc_valid_json_and_keys"] = True

            # Consistency checks that depend on newsletter and qc
            # One CTA only must be true and consistent with newsletter having exactly one "CTA:" line
            if checks["qc_valid_json_and_keys"] and checks["newsletter_exists"]:
                if qc_data.get("one_cta_only") is True and checks["newsletter_exactly_one_cta"]:
                    checks["qc_one_cta_only_true_and_consistent"] = True

                # No filler phrases true and consistent with newsletter having none
                if qc_data.get("no_filler_phrases") is True and checks["newsletter_no_banned_phrases"]:
                    checks["qc_no_filler_true_and_consistent"] = True

                # Concrete example present true and consistent with newsletter having a digit
                if qc_data.get("concrete_example_present") is True and checks["newsletter_has_digit"]:
                    checks["qc_concrete_example_true_and_consistent"] = True

                # Word count within ±20% of computed newsletter word count
                if isinstance(qc_data.get("word_count"), int):
                    news_wc = word_count(newsletter_text or "")
                    if news_wc > 0:
                        lower = int(news_wc * 0.8)
                        upper = int(news_wc * 1.2)
                        if lower <= qc_data["word_count"] <= upper:
                            checks["qc_word_count_within_20pct"] = True

            # Passive voice percent range 0-100 inclusive
            if checks["qc_valid_json_and_keys"]:
                pv = qc_data.get("passive_voice_estimate_percent")
                if isinstance(pv, (int, float)) and 0 <= pv <= 100:
                    checks["qc_passive_voice_percent_range"] = True

            # banned_words_found must be empty array
            if checks["qc_valid_json_and_keys"]:
                if isinstance(qc_data.get("banned_words_found"), list) and len(qc_data["banned_words_found"]) == 0:
                    checks["qc_banned_words_found_empty"] = True

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # No-op baseline: if all outputs missing or invalid, reward could be 0 already.
    # Ensure reward within [0,1]
    reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()