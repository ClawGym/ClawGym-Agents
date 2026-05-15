import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def file_non_empty(path):
    return os.path.isfile(path) and os.path.getsize(path) > 0

def find_section(text, tag):
    # Returns the content of a section starting with [Tag] up to next [Something]
    # Case-sensitive tags as in requirements, but we handle case-insensitive search
    pattern = re.compile(r'\[' + re.escape(tag) + r'\]', re.IGNORECASE)
    m = pattern.search(text)
    if not m:
        return None
    start = m.end()
    # Find next [ ... ] after start
    next_tag = re.search(r'\n\s*\[.+?\]', text[start:], re.IGNORECASE)
    if next_tag:
        end = start + next_tag.start()
    else:
        end = len(text)
    return text[start:end]

def contains_roman_progression(line):
    # Detect roman numerals including flats and minors, with separators - or –
    roman = r'(?:b?(?:I{1,3}|IV|V|VI{1,2}|VII)|b?(?:i{1,3}|iv|v|vi{1,2}|vii)|ii|iii|II|III)'
    # progression like I - V - vi - IV or vi–IV–I–V
    prog = re.compile(rf'\b{roman}\b\s*(?:[-–]\s*\b{roman}\b\s*)+', re.IGNORECASE)
    return prog.search(line) is not None

def line_has_scheme_for_section(line, section):
    # Check if a line mentions the section and contains a known rhyme scheme code
    schemes = {'ABAB','ABCB','AABB','XAXA','ABBA','AABA','AXAX','AAAA'}
    if re.search(section, line, re.IGNORECASE):
        for s in schemes:
            if re.search(r'\b' + s + r'\b', line):
                return True
    return False

def has_key_and_bpm_near_top(text, top_lines=60):
    lines = text.splitlines()[:top_lines]
    key_ok = False
    bpm_ok = False
    key_re = re.compile(r'(?i)\bkey\s*:\s*([A-G][#b]?)(?:\s*(major|minor|maj|min))?')
    bpm_re1 = re.compile(r'(?i)\b(BPM|Tempo)\s*:\s*(\d{2,3})\b')
    bpm_re2 = re.compile(r'(?i)\b(\d{2,3})\s*BPM\b')
    for ln in lines:
        if not key_ok and key_re.search(ln):
            key_ok = True
        if not bpm_ok and (bpm_re1.search(ln) or bpm_re2.search(ln)):
            bpm_ok = True
        if key_ok and bpm_ok:
            break
    return key_ok, bpm_ok

def get_label_region(text, label, other_label=None):
    # Return the substring from label to next other_label or end
    low = text.lower()
    i = low.find(label.lower())
    if i < 0:
        return None
    if other_label:
        j = low.find(other_label.lower(), i + 1)
    else:
        j = -1
    if j < 0:
        return text[i:]
    return text[i:j]

def is_style_line(line):
    # Must include BPM with number, mention 'vocal', and at least one instrument term, and have >=6 commas
    if line.count(",") < 6:
        return False
    if not re.search(r'(?i)\b(\d{2,3})\s*BPM\b|\bBPM\s*[: ]\s*(\d{2,3})', line):
        return False
    if not re.search(r'(?i)\bvocal\b', line):
        return False
    instruments = ['guitar', 'piano', 'synth', 'strings', 'drums', 'bass', 'violin', 'cello', 'horn', 'brass', 'sax', 'trumpet', 'percussion']
    if not any(re.search(r'(?i)\b' + inst + r'\b', line) for inst in instruments):
        return False
    return True

def find_style_line_in_region(region_text):
    if region_text is None:
        return False
    for ln in region_text.splitlines():
        if is_style_line(ln.strip()):
            return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    output_dir = os.path.join(workspace_root, "output")
    # Base path
    base_path = os.path.join(output_dir, "songs", "drafting", "dawn-drive")
    v001_path = os.path.join(base_path, "versions", "v001.md")
    current_path = os.path.join(base_path, "current.md")
    notes_path = os.path.join(base_path, "notes.md")
    prompts_path = os.path.join(base_path, "prompts.md")

    checks = {
        "v001_exists": False,
        "current_exists": False,
        "notes_exists": False,
        "prompts_exists": False,
        "v001_non_empty": False,
        "current_non_empty": False,
        "notes_non_empty": False,
        "prompts_non_empty": False,
        "current_matches_v001": False,
        "v001_has_required_tags": False,
        "has_key_top": False,
        "has_bpm_top": False,
        "has_rhyme_scheme_verse": False,
        "has_rhyme_scheme_chorus": False,
        "has_harmony_section": False,
        "harmony_verse_progression": False,
        "harmony_chorus_progression": False,
        "harmony_bridge_progression": False,
        "theme_keywords_present": False,
        "chorus_contains_dawn_drive": False,
        "prompts_has_suno_label": False,
        "prompts_has_udio_label": False,
        "prompts_suno_style_line": False,
        "prompts_udio_style_line": False,
        "prompts_has_section_tags": False,
        "notes_has_required_sections": False,
        "notes_mentions_structure_name": False,
        "notes_mentions_bar_counts": False
    }

    # Existence and non-empty checks
    checks["v001_exists"] = os.path.isfile(v001_path)
    checks["current_exists"] = os.path.isfile(current_path)
    checks["notes_exists"] = os.path.isfile(notes_path)
    checks["prompts_exists"] = os.path.isfile(prompts_path)

    if checks["v001_exists"]:
        checks["v001_non_empty"] = file_non_empty(v001_path)
    if checks["current_exists"]:
        checks["current_non_empty"] = file_non_empty(current_path)
    if checks["notes_exists"]:
        checks["notes_non_empty"] = file_non_empty(notes_path)
    if checks["prompts_exists"]:
        checks["prompts_non_empty"] = file_non_empty(prompts_path)

    v001_text = read_text(v001_path) if checks["v001_non_empty"] else None
    current_text = read_text(current_path) if checks["current_non_empty"] else None
    notes_text = read_text(notes_path) if checks["notes_non_empty"] else None
    prompts_text = read_text(prompts_path) if checks["prompts_non_empty"] else None

    # current matches v001
    if v001_text is not None and current_text is not None:
        checks["current_matches_v001"] = (v001_text == current_text)

    # Section tags in v001/current
    if v001_text:
        required_tags = ["[Verse 1]", "[Chorus]", "[Verse 2]", "[Bridge]"]
        checks["v001_has_required_tags"] = all(tag.lower() in v001_text.lower() for tag in required_tags)

    # Key and BPM near top, rhyme schemes
    if v001_text:
        key_ok, bpm_ok = has_key_and_bpm_near_top(v001_text)
        checks["has_key_top"] = key_ok
        checks["has_bpm_top"] = bpm_ok

        # Rhyme scheme for Verse and Chorus
        verse_scheme = any(line_has_scheme_for_section(ln, "Verse") for ln in v001_text.splitlines())
        chorus_scheme = any(line_has_scheme_for_section(ln, "Chorus") for ln in v001_text.splitlines())
        checks["has_rhyme_scheme_verse"] = verse_scheme
        checks["has_rhyme_scheme_chorus"] = chorus_scheme

        # Harmony subsection after lyrics
        # Ensure 'Harmony' or 'Chords' exists after last lyrics tag occurrence
        last_lyrics_tag_pos = -1
        for m in re.finditer(r'\[(?:Verse 1|Verse 2|Chorus|Bridge|Pre-Chorus|Outro)\]', v001_text, re.IGNORECASE):
            last_lyrics_tag_pos = max(last_lyrics_tag_pos, m.start())
        harmony_match = re.search(r'(?i)^\s*(Harmony|Chords)\b', v001_text[last_lyrics_tag_pos+1:] if last_lyrics_tag_pos >= 0 else v001_text, re.MULTILINE)
        if harmony_match:
            checks["has_harmony_section"] = True
            # Analyze harmony section lines
            harmony_start_global = (last_lyrics_tag_pos + 1) + harmony_match.start() if last_lyrics_tag_pos >= 0 else harmony_match.start()
            harmony_text = v001_text[harmony_start_global:]
            lines = harmony_text.splitlines()
            for ln in lines:
                if re.search(r'(?i)\bVerse\b', ln) and contains_roman_progression(ln):
                    checks["harmony_verse_progression"] = True
                if re.search(r'(?i)\bChorus\b', ln) and contains_roman_progression(ln):
                    checks["harmony_chorus_progression"] = True
                if re.search(r'(?i)\bBridge\b', ln) and contains_roman_progression(ln):
                    checks["harmony_bridge_progression"] = True

        # Theme keywords
        if v001_text:
            words = ["dawn", "drive", "city", "coast"]
            present = set()
            low = v001_text.lower()
            for w in words:
                if re.search(r'\b' + re.escape(w) + r'\b', low):
                    present.add(w)
            checks["theme_keywords_present"] = (len(present) >= 3)

        # Chorus must contain phrase "dawn drive"
        chorus_section = find_section(v001_text, "Chorus")
        if chorus_section:
            checks["chorus_contains_dawn_drive"] = re.search(r'(?i)\bdawn drive\b', chorus_section) is not None

    # Prompts formatting
    if prompts_text:
        low = prompts_text.lower()
        checks["prompts_has_suno_label"] = ("suno" in low)
        checks["prompts_has_udio_label"] = ("udio" in low)
        # Regions for style lines
        suno_region = get_label_region(prompts_text, "Suno", "Udio")
        udio_region = get_label_region(prompts_text, "Udio", "Suno")
        checks["prompts_suno_style_line"] = find_style_line_in_region(suno_region)
        checks["prompts_udio_style_line"] = find_style_line_in_region(udio_region)
        # Lyrics tags presence
        checks["prompts_has_section_tags"] = ("[Verse 1]" in prompts_text) and ("[Chorus]" in prompts_text)

    # Notes coverage
    if notes_text:
        low = notes_text.lower()
        req_sections = all(s in low for s in ["discovery", "structure", "lyrics", "harmony"])
        checks["notes_has_required_sections"] = req_sections
        # Structure name
        structure_patterns = [
            r'\bABABCB\b',
            r'\bAABA\b',
            r'\bABAB\b',
            r'\bAAA\b',
            r'Verse\s*[-–—]\s*Chorus\s*[-–—]\s*Bridge',
            r'Verse\s*[-–—]\s*Pre-?Chorus\s*[-–—]\s*Chorus',
            r'APCABPCB'  # from reference
        ]
        checks["notes_mentions_structure_name"] = any(re.search(pat, notes_text, re.IGNORECASE) for pat in structure_patterns)
        # Bar counts or lengths mention
        checks["notes_mentions_bar_counts"] = bool(re.search(r'(?i)\bbars?\b', notes_text))

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # If no outputs at all, reward must be exactly 0.0
    if not any([checks["v001_exists"], checks["current_exists"], checks["notes_exists"], checks["prompts_exists"]]):
        reward = 0.0
    else:
        reward = passed / total_checks if total_checks > 0 else 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()