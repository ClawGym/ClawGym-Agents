import json
import os
import re
import sys
from typing import List, Dict, Any

def load_allowed_quotes(input_dir: str) -> List[str]:
    # Try to read allowed quotes from input/quotes.json with flexible structures.
    quotes_path = os.path.join(input_dir, "quotes.json")
    quotes: List[str] = []
    try:
        with open(quotes_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # if data is a list of strings
        if isinstance(data, list):
            for item in data:
                if isinstance(item, str):
                    quotes.append(item)
                elif isinstance(item, dict):
                    for key in ("quote", "text", "content", "value"):
                        if isinstance(item.get(key), str):
                            quotes.append(item[key])
                            break
        elif isinstance(data, dict):
            for key in ("quotes", "allowed", "items"):
                v = data.get(key)
                if isinstance(v, list):
                    for item in v:
                        if isinstance(item, str):
                            quotes.append(item)
                        elif isinstance(item, dict):
                            for kk in ("quote", "text", "content", "value"):
                                if isinstance(item.get(kk), str):
                                    quotes.append(item[kk])
                                    break
    except Exception:
        quotes = []

    if quotes:
        # Deduplicate while preserving order
        seen = set()
        out = []
        for q in quotes:
            qs = q.strip()
            if qs and qs not in seen:
                seen.add(qs)
                out.append(qs)
        return out

    # Fallback hardcoded allowed quotes (recognized Kobe Bryant quotes), ASCII double quotes will wrap these in the document.
    fallback = [
        "I can't relate to lazy people. We don't speak the same language. I don't understand you. I don't want to understand you.",
        "The most important thing is to try and inspire people so that they can be great in whatever they want to do.",
        "I'll do whatever it takes to win games, whether it's sitting on a bench waving a towel, handing a cup of water to a teammate, or hitting the game-winning shot.",
        "Heroes come and go, but legends are forever.",
        "Once you know what failure feels like, determination chases success.",
        "I don't want to be the next Michael Jordan, I only want to be Kobe Bryant.",
        "The beauty in being blessed with talent is rising above doubters to create something beautiful.",
        "Rest at the end, not in the middle.",
        "Job's not finished.",
        "Mamba out."
    ]
    return fallback

def read_text_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def count_words(text: str) -> int:
    # Count tokens that look like words, including hyphenated and apostrophized words.
    tokens = re.findall(r"\b[\w'-]+\b", text)
    return len(tokens)

def extract_double_quoted_strings(text: str) -> List[str]:
    # Find all substrings enclosed in double quotes "
    # This does not handle escaped quotes, but is sufficient for the task.
    return re.findall(r'"([^"]+)"', text)

def find_takeaways_bullets(text: str) -> int:
    # Find "## Takeaways" section and count bullet lines starting with "- " (allow leading spaces)
    lines = text.splitlines()
    idx = -1
    for i, line in enumerate(lines):
        if line.strip() == "## Takeaways":
            idx = i
            break
    if idx == -1:
        return -1  # section not found
    # Determine section end: next heading line starting with '#'
    end = len(lines)
    for j in range(idx + 1, len(lines)):
        if re.match(r"^\s*#{1,6}\s+", lines[j]):
            end = j
            break
    bullet_count = 0
    for k in range(idx + 1, end):
        if re.match(r"^\s*-\s+", lines[k]):
            bullet_count += 1
    return bullet_count

def validate_reference_json(obj: Any) -> Dict[str, bool]:
    checks = {
        "ref_has_required_keys": False,
        "ref_principles_len5_shape": False,
        "ref_iconic_moments_len5_shape": False,
        "ref_championships_len5_years": False,
        "ref_championships_2009_2010_correct": False,
        "ref_jersey_numbers_shape": False,
        "ref_career_totals_exact": False,
    }
    if not isinstance(obj, dict):
        return checks

    required_top = ["principles", "iconic_moments", "championships", "jersey_numbers", "career_totals"]
    if all(k in obj for k in required_top):
        checks["ref_has_required_keys"] = True

    # principles
    principles = obj.get("principles")
    if isinstance(principles, list) and len(principles) == 5:
        ok = True
        for p in principles:
            if not isinstance(p, dict):
                ok = False
                break
            name = p.get("name")
            one = p.get("one_sentence")
            if not (isinstance(name, str) and name.strip() and isinstance(one, str) and one.strip()):
                ok = False
                break
        checks["ref_principles_len5_shape"] = ok

    # iconic_moments
    iconic = obj.get("iconic_moments")
    if isinstance(iconic, list) and len(iconic) == 5:
        ok = True
        for m in iconic:
            if not isinstance(m, dict):
                ok = False
                break
            name = m.get("name")
            date = m.get("date")
            summary = m.get("summary")
            if not (isinstance(name, str) and name.strip() and isinstance(date, str) and date.strip() and isinstance(summary, str) and summary.strip()):
                ok = False
                break
        checks["ref_iconic_moments_len5_shape"] = ok

    # championships
    champs = obj.get("championships")
    years_required = {2000, 2001, 2002, 2009, 2010}
    if isinstance(champs, list) and len(champs) == 5:
        years_seen = set()
        ok_shape = True
        ok_09_10 = False
        opp09 = None
        mvp09 = None
        opp10 = None
        mvp10 = None
        for c in champs:
            if not isinstance(c, dict):
                ok_shape = False
                break
            year = c.get("year")
            opp = c.get("opponent")
            res = c.get("result")
            mvp = c.get("finals_mvp")
            if not (isinstance(year, int) and isinstance(opp, str) and opp.strip() and isinstance(res, str) and res.strip() and isinstance(mvp, str) and mvp.strip()):
                ok_shape = False
                break
            years_seen.add(year)
            if year == 2009:
                opp09 = opp
                mvp09 = mvp
            if year == 2010:
                opp10 = opp
                mvp10 = mvp
        if ok_shape and years_seen == years_required:
            checks["ref_championships_len5_years"] = True
        if (opp09 == "Orlando Magic" and mvp09 == "Kobe Bryant") and (opp10 == "Boston Celtics" and mvp10 == "Kobe Bryant"):
            ok_09_10 = True
        checks["ref_championships_2009_2010_correct"] = ok_09_10

    # jersey_numbers
    jerseys = obj.get("jersey_numbers")
    if isinstance(jerseys, dict) and "8" in jerseys and "24" in jerseys:
        ok = True
        for key in ["8", "24"]:
            val = jerseys.get(key)
            if not isinstance(val, dict):
                ok = False
                break
            era = val.get("era")
            highlights = val.get("highlights")
            if not (isinstance(era, str) and era.strip() and isinstance(highlights, str) and highlights.strip()):
                ok = False
                break
        checks["ref_jersey_numbers_shape"] = ok

    # career_totals exact
    totals = obj.get("career_totals")
    if isinstance(totals, dict) and set(totals.keys()) == {"points", "games", "ppg"}:
        pts = totals.get("points")
        gms = totals.get("games")
        ppg = totals.get("ppg")
        pts_ok = (pts == 33643)
        gms_ok = (gms == 1346)
        # Accept numeric 25.0 exactly; also accept int 25 equivalently
        ppg_ok = False
        if isinstance(ppg, (int, float)):
            ppg_ok = (float(ppg) == 25.0)
        checks["ref_career_totals_exact"] = bool(pts_ok and gms_ok and ppg_ok)

    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir = os.path.join(workspace_root, "reward")  # not used but reserved

    guide_path = os.path.join(output_dir, "guide.md")
    reference_path = os.path.join(output_dir, "reference.json")
    checklist_path = os.path.join(output_dir, "checklist.txt")

    checks: Dict[str, bool] = {}

    # Existence checks
    guide_exists = os.path.isfile(guide_path)
    reference_exists = os.path.isfile(reference_path)
    checklist_exists = os.path.isfile(checklist_path)
    checks["exists_guide_md"] = guide_exists
    checks["exists_reference_json"] = reference_exists
    checks["exists_checklist_txt"] = checklist_exists
    checks["exists_all_required"] = guide_exists and reference_exists and checklist_exists

    # Initialize other checks to False
    checks.update({
        "title_contains_required": False,
        "word_count_900_1200": False,
        "takeaways_section_present": False,
        "takeaways_5_to_7_bullets": False,
        "quotes_exactly_three_allowed": False,
        "mentions_2009_orlando": False,
        "mentions_2010_celtics": False,
        "mentions_81_raptors_date": False,
        "mentions_achilles_free_throw": False,
        "mentions_60_point_and_farewell_or_final": False,
        "mentions_jersey_8_and_24": False,
        "checklist_lists_quotes_and_wordcount": False,
        # reference subchecks will be populated from validator
        "ref_has_required_keys": False,
        "ref_principles_len5_shape": False,
        "ref_iconic_moments_len5_shape": False,
        "ref_championships_len5_years": False,
        "ref_championships_2009_2010_correct": False,
        "ref_jersey_numbers_shape": False,
        "ref_career_totals_exact": False,
    })

    allowed_quotes = load_allowed_quotes(input_dir)

    guide_text = ""
    guide_word_count = 0
    used_allowed_quotes: List[str] = []
    if guide_exists:
        guide_text = read_text_file(guide_path)
        # Title check: first non-empty line must contain required phrase
        first_nonempty = ""
        for line in guide_text.splitlines():
            if line.strip():
                first_nonempty = line.strip()
                break
        if "Kobe Bryant: Mamba Mentality in Practice" in first_nonempty:
            checks["title_contains_required"] = True

        # Word count
        guide_word_count = count_words(guide_text)
        if 900 <= guide_word_count <= 1200:
            checks["word_count_900_1200"] = True

        # Takeaways
        bullets = find_takeaways_bullets(guide_text)
        if bullets != -1:
            checks["takeaways_section_present"] = True
            if 5 <= bullets <= 7:
                checks["takeaways_5_to_7_bullets"] = True

        # Quotes
        quoted_strings = extract_double_quoted_strings(guide_text)
        allowed_matches = [s.strip() for s in quoted_strings if s.strip() in allowed_quotes]
        used_allowed_quotes = allowed_matches[:]  # occurrences as used
        if len(allowed_matches) == 3:
            checks["quotes_exactly_three_allowed"] = True

        # Required mentions
        low = guide_text.lower()
        if ("orlando magic" in low) and ("2009" in low):
            checks["mentions_2009_orlando"] = True
        if ("boston celtics" in low) and ("2010" in low):
            checks["mentions_2010_celtics"] = True
        if ("81-point" in low) and ("toronto raptors" in low) and ("january 22, 2006" in low):
            checks["mentions_81_raptors_date"] = True
        if ("achilles" in low) and ("free throw" in low):
            checks["mentions_achilles_free_throw"] = True
        if ("60-point" in low) and (("farewell" in low) or ("final" in low)):
            checks["mentions_60_point_and_farewell_or_final"] = True
        if "#8" in guide_text and "#24" in guide_text:
            checks["mentions_jersey_8_and_24"] = True

    # Reference JSON validation
    if reference_exists:
        try:
            with open(reference_path, "r", encoding="utf-8") as f:
                ref_obj = json.load(f)
            ref_checks = validate_reference_json(ref_obj)
            checks.update(ref_checks)
        except Exception:
            pass

    # Checklist checks: list the three quotes used and word count
    if checklist_exists and guide_exists:
        checklist_text = read_text_file(checklist_path)
        # Verify each used allowed quote string appears enclosed in double quotes in checklist
        quotes_ok = True
        if len(used_allowed_quotes) == 3:
            for q in used_allowed_quotes:
                # must appear as "quote"
                if f"\"{q}\"" not in checklist_text:
                    quotes_ok = False
                    break
        else:
            quotes_ok = False
        # Verify final word count appears in checklist
        wc_ok = False
        if guide_word_count > 0:
            # Search for the exact number presence
            if re.search(rf"\b{guide_word_count}\b", checklist_text):
                wc_ok = True
        checks["checklist_lists_quotes_and_wordcount"] = bool(quotes_ok and wc_ok)

    # Compute reward as average of booleans, but if any required file missing, reward is 0.0
    # Gather only the validation checks (exclude existence of individual files but include exists_all_required)
    check_keys = [
        "exists_all_required",
        "title_contains_required",
        "word_count_900_1200",
        "takeaways_section_present",
        "takeaways_5_to_7_bullets",
        "quotes_exactly_three_allowed",
        "mentions_2009_orlando",
        "mentions_2010_celtics",
        "mentions_81_raptors_date",
        "mentions_achilles_free_throw",
        "mentions_60_point_and_farewell_or_final",
        "mentions_jersey_8_and_24",
        "ref_has_required_keys",
        "ref_principles_len5_shape",
        "ref_iconic_moments_len5_shape",
        "ref_championships_len5_years",
        "ref_championships_2009_2010_correct",
        "ref_jersey_numbers_shape",
        "ref_career_totals_exact",
        "checklist_lists_quotes_and_wordcount",
    ]
    total = len(check_keys)
    passed = sum(1 for k in check_keys if checks.get(k, False))

    if not checks["exists_all_required"]:
        reward = 0.0
    else:
        reward = passed / total if total > 0 else 0.0

    # Print JSON result
    result = {"reward": reward}
    # Also include all checks in output
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()