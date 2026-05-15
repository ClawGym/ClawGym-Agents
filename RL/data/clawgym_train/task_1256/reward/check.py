import json
import os
import sys

def read_text_utf8(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def count_lines(text):
    # Logical lines (ignores trailing empty line)
    return len(text.splitlines())

def file_exists_nonempty_utf8(path):
    text = read_text_utf8(path)
    if text is None:
        return False, None
    if len(text) == 0:
        return False, ""
    return True, text

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    in_cyr = os.path.join(input_dir, "press_release_cyrillic.txt")
    in_ara = os.path.join(input_dir, "diaspora_messages_arabic.txt")

    out_arabic = os.path.join(output_dir, "press_release_arabic.txt")
    out_cyrillic = os.path.join(output_dir, "diaspora_messages_cyrillic.txt")

    align_c2a = os.path.join(output_dir, "cyr_to_arabic_alignment.tsv")
    align_a2c = os.path.join(output_dir, "arabic_to_cyrillic_alignment.tsv")

    report_path = os.path.join(output_dir, "conversion_report.json")

    # Load inputs (used for expectations only; no credit for just reading)
    in_cyr_text = read_text_utf8(in_cyr)
    in_ara_text = read_text_utf8(in_ara)

    in_cyr_lines = count_lines(in_cyr_text) if in_cyr_text is not None else None
    in_ara_lines = count_lines(in_ara_text) if in_ara_text is not None else None

    checks = {
        "arabic_output_exists": False,
        "arabic_output_utf8_nonempty": False,
        "arabic_output_contains_expected_yw_yo": False,
        "arabic_output_contains_expected_special_letters": False,
        "arabic_output_punctuation_mapped": False,

        "cyrillic_output_exists": False,
        "cyrillic_output_utf8_nonempty": False,
        "cyrillic_output_contains_expected_yu_yo": False,
        "cyrillic_output_contains_expected_special_letters": False,
        "cyrillic_output_contains_expected_vowels": False,
        "cyrillic_output_punctuation_mapped": False,

        "alignment_cyr_to_arabic_exists": False,
        "alignment_cyr_to_arabic_line_count_match": False,
        "alignment_cyr_to_arabic_tab_separated": False,

        "alignment_arabic_to_cyrillic_exists": False,
        "alignment_arabic_to_cyrillic_line_count_match": False,
        "alignment_arabic_to_cyrillic_tab_separated": False,

        "report_exists_and_valid": False,
        "report_counts_match_inputs": False,
    }

    # Arabic output checks (Cyrillic -> Arabic)
    exists, arabic_text = file_exists_nonempty_utf8(out_arabic)
    if exists:
        checks["arabic_output_exists"] = True
        checks["arabic_output_utf8_nonempty"] = True if arabic_text and len(arabic_text.strip()) > 0 else False

        # Expected combinations based on input presence to avoid vacuous pass
        expected_combo_requirements = []
        if in_cyr_text:
            if "ю" in in_cyr_text:
                expected_combo_requirements.append(("يۋ", "yu_combo"))
            if "ё" in in_cyr_text:
                expected_combo_requirements.append(("يو", "yo_combo"))

        if expected_combo_requirements:
            combo_ok = all(token in arabic_text for token, _ in expected_combo_requirements)
            checks["arabic_output_contains_expected_yw_yo"] = combo_ok

        # Expected special letters based on input
        # Cyrillic -> Arabic: қ->ق, ң->ڭ, ғ->ع, у->ۋ, ұ/ү->ۇ (ү often as ءۇ includes و with hamza, but we check for 'ۇ')
        expected_specials = []
        if in_cyr_text:
            if "қ" in in_cyr_text:
                expected_specials.append("ق")
            if "ң" in in_cyr_text:
                expected_specials.append("ڭ")
            if "ғ" in in_cyr_text:
                expected_specials.append("ع")
            if any(ch in in_cyr_text for ch in ["у"]):
                expected_specials.append("ۋ")
            if any(ch in in_cyr_text for ch in ["ұ", "ү"]):
                expected_specials.append("ۇ")
        if expected_specials:
            checks["arabic_output_contains_expected_special_letters"] = all(sym in arabic_text for sym in expected_specials)

        # Punctuation mapping: ',', ';', '?' in input -> '،', '؛', '؟' in output
        if in_cyr_text:
            required_punct = []
            if "," in in_cyr_text:
                required_punct.append("،")
            if ";" in in_cyr_text:
                required_punct.append("؛")
            if "?" in in_cyr_text:
                required_punct.append("؟")
            if required_punct:
                checks["arabic_output_punctuation_mapped"] = all(p in arabic_text for p in required_punct)

    # Cyrillic output checks (Arabic -> Cyrillic)
    exists, cyrillic_text = file_exists_nonempty_utf8(out_cyrillic)
    if exists:
        checks["cyrillic_output_exists"] = True
        checks["cyrillic_output_utf8_nonempty"] = True if cyrillic_text and len(cyrillic_text.strip()) > 0 else False

        # Expected combinations based on Arabic input: يۋ -> ю, يو -> ё
        expected_combo_requirements_cyr = []
        if in_ara_text:
            if "يۋ" in in_ara_text:
                expected_combo_requirements_cyr.append(("ю", "yu"))
            if "يو" in in_ara_text:
                expected_combo_requirements_cyr.append(("ё", "yo"))
        if expected_combo_requirements_cyr:
            checks["cyrillic_output_contains_expected_yu_yo"] = all(token in cyrillic_text for token, _ in expected_combo_requirements_cyr)

        # Expected special letters: ق->қ, ڭ->ң, ھ->һ
        expected_specials_cyr = []
        if in_ara_text:
            if "ق" in in_ara_text:
                expected_specials_cyr.append("қ")
            if "ڭ" in in_ara_text:
                expected_specials_cyr.append("ң")
            if "ھ" in in_ara_text:
                expected_specials_cyr.append("һ")
        if expected_specials_cyr:
            checks["cyrillic_output_contains_expected_special_letters"] = all(sym in cyrillic_text for sym in expected_specials_cyr)

        # Expected vowels based on Arabic sequences: ءا->ә, ءى->і, ءۇ->ү, ءو->ө
        expected_vowels = []
        if in_ara_text:
            if "ءا" in in_ara_text:
                expected_vowels.append("ә")
            if "ءى" in in_ara_text:
                expected_vowels.append("і")
            if "ءۇ" in in_ara_text:
                expected_vowels.append("ү")
            if "ءو" in in_ara_text:
                expected_vowels.append("ө")
        if expected_vowels:
            checks["cyrillic_output_contains_expected_vowels"] = all(v in cyrillic_text for v in expected_vowels)

        # Punctuation mapping: '،', '؛', '؟' in input -> ',', ';', '?' in output
        if in_ara_text:
            required_punct_back = []
            if "،" in in_ara_text:
                required_punct_back.append(",")
            if "؛" in in_ara_text:
                required_punct_back.append(";")
            if "؟" in in_ara_text:
                required_punct_back.append("?")
            if required_punct_back:
                checks["cyrillic_output_punctuation_mapped"] = all(p in cyrillic_text for p in required_punct_back)

    # Alignment checks (Cyrillic -> Arabic)
    align_c2a_text = read_text_utf8(align_c2a)
    if align_c2a_text is not None:
        checks["alignment_cyr_to_arabic_exists"] = True
        lines = align_c2a_text.splitlines()
        if in_cyr_lines is not None and len(lines) == in_cyr_lines:
            checks["alignment_cyr_to_arabic_line_count_match"] = True
        # Each non-empty line must have exactly one tab
        if lines:
            tabs_ok = True
            for line in lines:
                if len(line) > 0:
                    if line.count("\t") != 1:
                        tabs_ok = False
                        break
            checks["alignment_cyr_to_arabic_tab_separated"] = tabs_ok

    # Alignment checks (Arabic -> Cyrillic)
    align_a2c_text = read_text_utf8(align_a2c)
    if align_a2c_text is not None:
        checks["alignment_arabic_to_cyrillic_exists"] = True
        lines = align_a2c_text.splitlines()
        if in_ara_lines is not None and len(lines) == in_ara_lines:
            checks["alignment_arabic_to_cyrillic_line_count_match"] = True
        # Each non-empty line must have exactly one tab
        if lines:
            tabs_ok = True
            for line in lines:
                if len(line) > 0:
                    if line.count("\t") != 1:
                        tabs_ok = False
                        break
            checks["alignment_arabic_to_cyrillic_tab_separated"] = tabs_ok

    # Report checks
    report_text = read_text_utf8(report_path)
    report_data = None
    if report_text is not None:
        try:
            report_data = json.loads(report_text)
            checks["report_exists_and_valid"] = True
            # Verify keys and line counts
            if isinstance(report_data, dict):
                c2a = report_data.get("cyr_to_arabic")
                a2c = report_data.get("arabic_to_cyrillic")
                c2a_ok = isinstance(c2a, dict) and isinstance(c2a.get("lines_converted"), int)
                a2c_ok = isinstance(a2c, dict) and isinstance(a2c.get("lines_converted"), int)
                counts_ok = False
                if c2a_ok and a2c_ok and in_cyr_lines is not None and in_ara_lines is not None:
                    counts_ok = (c2a["lines_converted"] == in_cyr_lines) and (a2c["lines_converted"] == in_ara_lines)
                if counts_ok:
                    checks["report_counts_match_inputs"] = True
        except Exception:
            pass

    # Determine applicable checks for scoring (only those that depended on output artifacts)
    # Exclude checks that could not be meaningfully evaluated due to missing expectations (to avoid penalizing when inputs lack those tokens)
    applicable = []

    # Mandatory existence/content checks are always applicable
    applicable += [
        "arabic_output_exists",
        "arabic_output_utf8_nonempty",
        "cyrillic_output_exists",
        "cyrillic_output_utf8_nonempty",
        "alignment_cyr_to_arabic_exists",
        "alignment_arabic_to_cyrillic_exists",
        "report_exists_and_valid",
    ]

    # Applicability of token/punctuation checks depends on inputs
    if in_cyr_text and ("ю" in in_cyr_text or "ё" in in_cyr_text):
        applicable.append("arabic_output_contains_expected_yw_yo")
    if in_cyr_text and ("," in in_cyr_text or ";" in in_cyr_text or "?" in in_cyr_text):
        applicable.append("arabic_output_punctuation_mapped")
    if in_cyr_text and any(ch in in_cyr_text for ch in ["қ", "ң", "ғ", "у", "ұ", "ү"]):
        applicable.append("arabic_output_contains_expected_special_letters")

    if in_ara_text and ("يۋ" in in_ara_text or "يو" in in_ara_text):
        applicable.append("cyrillic_output_contains_expected_yu_yo")
    if in_ara_text and ( "،" in in_ara_text or "؛" in in_ara_text or "؟" in in_ara_text ):
        applicable.append("cyrillic_output_punctuation_mapped")
    if in_ara_text and any(ch in in_ara_text for ch in ["ق", "ڭ", "ھ"]):
        applicable.append("cyrillic_output_contains_expected_special_letters")
    if in_ara_text and any(seq in in_ara_text for seq in ["ءا", "ءى", "ءۇ", "ءو"]):
        applicable.append("cyrillic_output_contains_expected_vowels")

    # Alignment detail checks applicable if inputs are known
    if in_cyr_lines is not None:
        applicable.append("alignment_cyr_to_arabic_line_count_match")
        applicable.append("alignment_cyr_to_arabic_tab_separated")
    if in_ara_lines is not None:
        applicable.append("alignment_arabic_to_cyrillic_line_count_match")
        applicable.append("alignment_arabic_to_cyrillic_tab_separated")

    # Report counts match if inputs are known
    if in_cyr_lines is not None and in_ara_lines is not None:
        applicable.append("report_counts_match_inputs")

    # Compute reward
    # No-op baseline: if both primary outputs are missing or empty, reward is 0.0
    arabic_ok_presence = checks["arabic_output_exists"] and checks["arabic_output_utf8_nonempty"]
    cyrillic_ok_presence = checks["cyrillic_output_exists"] and checks["cyrillic_output_utf8_nonempty"]
    if not arabic_ok_presence and not cyrillic_ok_presence:
        reward = 0.0
    else:
        if not applicable:
            reward = 0.0
        else:
            passed = sum(1 for k in applicable if checks.get(k, False))
            reward = passed / float(len(applicable))

    # Output single JSON line
    result = {"reward": float(round(reward, 6))}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()