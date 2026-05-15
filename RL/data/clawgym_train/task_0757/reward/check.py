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

def split_words(text):
    # Tokenize by whitespace
    return text.split()

def count_sentences(text):
    # Count occurrences of sentence-ending punctuation . ? !
    # Treat one or more as a single sentence end
    return len(re.findall(r'[.!?]+', text))

def parse_story(story_text):
    """
    Returns a dict with:
    - title (str or None)
    - genre_line_ok (bool)
    - chapter_numbers (set of ints)
    - body_word_count (int)
    - motifs (set of strings)
    """
    result = {
        "title": None,
        "genre_line_ok": False,
        "chapter_numbers": set(),
        "body_word_count": 0,
        "motifs": set(),
        "title_line_ok": False,
    }
    if story_text is None:
        return result

    lines = story_text.splitlines()
    if len(lines) >= 1 and lines[0].startswith("Title: "):
        title = lines[0][len("Title: "):].strip()
        if title:
            result["title"] = title
            result["title_line_ok"] = True
    if len(lines) >= 2:
        result["genre_line_ok"] = (lines[1].strip() == "Genre: Magical Realism Mystery")

    # Body is lines after first two
    body_lines = lines[2:] if len(lines) > 2 else []
    body_text = "\n".join(body_lines)
    result["body_word_count"] = len(split_words(body_text))

    # Chapters: lines exactly matching "## Chapter X" where X is positive integer
    for line in lines:
        m = re.fullmatch(r"## Chapter (\d+)", line.strip())
        if m:
            try:
                num = int(m.group(1))
                if num > 0:
                    result["chapter_numbers"].add(num)
            except ValueError:
                pass

    # Motifs: [MOTIF: <text>]
    motif_matches = re.findall(r"\[MOTIF:\s*(.*?)\]", story_text)
    for motif in motif_matches:
        motif_clean = motif.strip()
        if motif_clean:
            result["motifs"].add(motif_clean)

    return result

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    story_path = os.path.join(output_dir, "story.md")
    outline_path = os.path.join(output_dir, "outline.md")
    synopsis_path = os.path.join(output_dir, "synopsis.txt")
    metadata_path = os.path.join(output_dir, "metadata.json")

    checks = {
        # Story checks
        "story_file_exists": False,
        "story_title_line_valid": False,
        "story_genre_line_valid": False,
        "story_has_min_chapters": False,
        "story_word_count_in_range": False,
        "story_has_min_distinct_motifs": False,

        # Outline checks
        "outline_file_exists": False,
        "outline_has_required_headers": False,
        "outline_mentions_all_characters": False,

        # Synopsis checks
        "synopsis_file_exists": False,
        "synopsis_word_count_in_range": False,

        # Metadata checks
        "metadata_file_exists": False,
        "metadata_valid_json": False,
        "metadata_title_matches": False,
        "metadata_genre_pov_tense_match": False,
        "metadata_chapters_match": False,
        "metadata_word_count_match": False,
        "metadata_motifs_match": False,
        "metadata_characters_valid": False,
        "metadata_style_notes_keywords": False,
        "metadata_outline_sections_valid": False,
    }

    # Load story and parse
    story_text = read_text(story_path)
    if story_text is not None:
        checks["story_file_exists"] = True
        story_info = parse_story(story_text)

        # Title line validity
        if story_info["title_line_ok"]:
            checks["story_title_line_valid"] = True

        # Genre line validity
        if story_info["genre_line_ok"]:
            checks["story_genre_line_valid"] = True

        # Chapters: at least 4 unique chapter numbers
        if len(story_info["chapter_numbers"]) >= 4:
            checks["story_has_min_chapters"] = True

        # Word count between 2400 and 3000 inclusive
        if 2400 <= story_info["body_word_count"] <= 3000:
            checks["story_word_count_in_range"] = True

        # Motifs: at least 5 distinct
        if len(story_info["motifs"]) >= 5:
            checks["story_has_min_distinct_motifs"] = True
    else:
        story_info = {
            "title": None,
            "genre_line_ok": False,
            "chapter_numbers": set(),
            "body_word_count": 0,
            "motifs": set(),
            "title_line_ok": False,
        }

    # Outline checks
    outline_text = read_text(outline_path)
    if outline_text is not None:
        checks["outline_file_exists"] = True
        outline_lines = [ln.strip() for ln in outline_text.splitlines()]
        required_headers = ["Logline:", "Themes:", "Act I", "Act II", "Act III"]
        has_all_headers = all(h in outline_lines for h in required_headers)
        if has_all_headers:
            checks["outline_has_required_headers"] = True

        outline_lower = outline_text
        # Character mentions
        names = ["Mara Ellison", "Jonah Pike", "Eloise Hart"]
        if all(name in outline_text for name in names):
            checks["outline_mentions_all_characters"] = True
    else:
        outline_lines = []
        required_headers = ["Logline:", "Themes:", "Act I", "Act II", "Act III"]

    # Synopsis checks
    synopsis_text = read_text(synopsis_path)
    if synopsis_text is not None:
        checks["synopsis_file_exists"] = True
        synopsis_wc = len(split_words(synopsis_text))
        if 150 <= synopsis_wc <= 250:
            checks["synopsis_word_count_in_range"] = True

    # Metadata checks
    metadata_text = read_text(metadata_path)
    metadata = None
    if metadata_text is not None:
        checks["metadata_file_exists"] = True
        try:
            metadata = json.loads(metadata_text)
            checks["metadata_valid_json"] = True
        except Exception:
            metadata = None

    # If metadata is valid JSON, perform field checks
    if metadata is not None and isinstance(metadata, dict):
        # Required keys
        required_keys = [
            "title", "genre", "pov", "tense", "chapters", "word_count",
            "characters", "motifs", "style_adherence_notes", "outline_sections"
        ]
        have_required_keys = all(k in metadata for k in required_keys)

        # title matches story title
        title_ok = False
        if have_required_keys and isinstance(metadata.get("title"), str) and story_info["title"]:
            title_ok = (metadata["title"] == story_info["title"])
        checks["metadata_title_matches"] = title_ok

        # genre, pov, tense exact matches
        gpt_ok = False
        if have_required_keys:
            gpt_ok = (
                metadata.get("genre") == "Magical Realism Mystery" and
                metadata.get("pov") == "third-person limited" and
                metadata.get("tense") == "past"
            )
        checks["metadata_genre_pov_tense_match"] = gpt_ok

        # chapters match count of headings
        chapters_ok = False
        if have_required_keys and isinstance(metadata.get("chapters"), int):
            chapters_ok = (metadata["chapters"] == len(story_info["chapter_numbers"]))
        checks["metadata_chapters_match"] = chapters_ok

        # word_count matches computed
        wc_ok = False
        if have_required_keys and isinstance(metadata.get("word_count"), int):
            wc_ok = (metadata["word_count"] == story_info["body_word_count"])
        checks["metadata_word_count_match"] = wc_ok

        # motifs match set of distinct motifs
        motifs_ok = False
        if have_required_keys and isinstance(metadata.get("motifs"), list):
            try:
                md_motifs_set = set([str(m).strip() for m in metadata["motifs"]])
                motifs_ok = (md_motifs_set == story_info["motifs"])
            except Exception:
                motifs_ok = False
        checks["metadata_motifs_match"] = motifs_ok

        # characters include required names with arc_summary 1-3 sentences each
        chars_ok = False
        if have_required_keys and isinstance(metadata.get("characters"), list):
            required_names = {"Mara Ellison", "Jonah Pike", "Eloise Hart"}
            present_names = set()
            per_item_ok = True
            for item in metadata["characters"]:
                if not isinstance(item, dict):
                    per_item_ok = False
                    break
                name = item.get("name")
                arc = item.get("arc_summary")
                if not isinstance(name, str) or not isinstance(arc, str):
                    per_item_ok = False
                    break
                arc_clean = arc.strip()
                if not arc_clean:
                    per_item_ok = False
                    break
                # Count sentences
                sentences = count_sentences(arc_clean)
                if not (1 <= sentences <= 3):
                    per_item_ok = False
                    break
                if name in required_names:
                    present_names.add(name)
            chars_ok = per_item_ok and (required_names.issubset(present_names))
        checks["metadata_characters_valid"] = chars_ok

        # style_adherence_notes include keywords
        notes_ok = False
        if have_required_keys and isinstance(metadata.get("style_adherence_notes"), list):
            combined = " ".join([str(s) for s in metadata["style_adherence_notes"]])
            lower_combined = combined.lower()
            needed = [
                "melancholic",
                "hopeful",
                "third-person limited",
                "past tense",
                "magical realism mystery",
            ]
            notes_ok = all(n in lower_combined for n in needed)
        checks["metadata_style_notes_keywords"] = notes_ok

        # outline_sections contains all of required sections (without colons for Logline/Themes)
        outline_sections_ok = False
        if have_required_keys and isinstance(metadata.get("outline_sections"), list):
            md_sections = set([str(s).strip() for s in metadata["outline_sections"]])
            required_sections = {"Logline", "Themes", "Act I", "Act II", "Act III"}
            outline_sections_ok = required_sections.issubset(md_sections)
        checks["metadata_outline_sections_valid"] = outline_sections_ok

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # No-op baseline: if output is missing or empty, ensure reward is 0.0
    output_exists = os.path.isdir(output_dir)
    has_any_output_file = False
    if output_exists:
        try:
            for name in os.listdir(output_dir):
                if os.path.isfile(os.path.join(output_dir, name)):
                    has_any_output_file = True
                    break
        except Exception:
            has_any_output_file = False
    if not has_any_output_file:
        reward = 0.0

    # Build result with reward first
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()