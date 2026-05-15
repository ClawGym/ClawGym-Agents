import json
import os
import sys
import re
import csv
from io import StringIO

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks as False (no-op baseline yields 0.0)
    checks = {
        "stats_ok": False,
        "search_ok": False,
        "timeline_ok": False,
        "export_ok": False,
        "report_ok": False,
    }

    # Helper functions
    def read_text(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return None

    def read_json(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def normalize_newlines(s):
        return s.replace("\r\n", "\n").replace("\r", "\n")

    # Ground truth computations
    chapters_rel = ["ch1.txt", "ch2.txt", "ch3.txt"]
    chapter_paths = {name: os.path.join(input_dir, "chapters", name) for name in chapters_rel}
    chapter_texts = {}
    for name, path in chapter_paths.items():
        txt = read_text(path)
        if txt is None:
            chapter_texts[name] = None
        else:
            chapter_texts[name] = txt

    def word_count(s):
        # Count tokens split on whitespace: any run of non-whitespace is a token
        return len(re.findall(r"\S+", s))

    def line_count(s):
        # Lines: count newline-separated lines; include final line even if no trailing newline
        if s == "":
            return 0
        return s.count("\n") + 1

    stats_expected = {}
    totals_words = 0
    totals_lines = 0
    chapters_available = True
    for name in chapters_rel:
        txt = chapter_texts.get(name)
        if txt is None:
            chapters_available = False
            break
        w = word_count(txt)
        l = line_count(txt)
        stats_expected[name] = {"words": w, "lines": l}
        totals_words += w
        totals_lines += l

    # Check 1: stats.json
    stats_path = os.path.join(output_dir, "stats.json")
    if chapters_available and os.path.isfile(stats_path):
        stats_out = read_json(stats_path)
        if isinstance(stats_out, dict) and "chapters" in stats_out and "totals" in stats_out:
            chapters_out = stats_out.get("chapters")
            totals_out = stats_out.get("totals")
            # Ensure chapters keys are exactly the expected set
            try:
                keys_ok = isinstance(chapters_out, dict) and set(chapters_out.keys()) == set(chapters_rel)
                values_ok = True
                if keys_ok:
                    for name in chapters_rel:
                        entry = chapters_out.get(name)
                        exp = stats_expected.get(name)
                        if not isinstance(entry, dict):
                            values_ok = False
                            break
                        if not (isinstance(entry.get("words"), int) and isinstance(entry.get("lines"), int)):
                            values_ok = False
                            break
                        if entry.get("words") != exp["words"] or entry.get("lines") != exp["lines"]:
                            values_ok = False
                            break
                totals_ok = isinstance(totals_out, dict) and isinstance(totals_out.get("words"), int) and isinstance(totals_out.get("lines"), int) and totals_out.get("words") == totals_words and totals_out.get("lines") == totals_lines
                if keys_ok and values_ok and totals_ok:
                    checks["stats_ok"] = True
            except Exception:
                pass

    # Prepare search term and expected search results
    search_term_path = os.path.join(input_dir, "search_term.txt")
    search_term = None
    term_content = read_text(search_term_path)
    if term_content is not None:
        search_term = term_content.strip()

    expected_search_lines = []
    if chapters_available and search_term is not None and search_term != "":
        # Iterate in filename order ch1, ch2, ch3
        term_lower = search_term.lower()
        for name in chapters_rel:
            txt = chapter_texts[name]
            # Split by '\n' to keep original line text without newline; CR may remain if present in file
            lines = txt.split("\n")
            for idx, line in enumerate(lines, start=1):
                # Case-insensitive search for substring
                if term_lower in line.lower():
                    # Preserve original line text exactly
                    expected_search_lines.append(f"{name}:{idx}:{line}")

    # Check 2: search_lantern.txt
    search_output_path = os.path.join(output_dir, "search_lantern.txt")
    if os.path.isfile(search_output_path):
        actual_search_content = read_text(search_output_path)
        if actual_search_content is not None:
            # Normalize and compare as list of lines (ignore trailing newline differences)
            actual_norm = normalize_newlines(actual_search_content)
            actual_lines = actual_norm.split("\n")
            # Remove possible trailing empty line caused by ending newline
            if len(actual_lines) > 0 and actual_lines[-1] == "":
                actual_lines = actual_lines[:-1]
            if actual_lines == expected_search_lines:
                checks["search_ok"] = True

    # Prepare expected timeline.csv content
    plots_csv_path = os.path.join(input_dir, "plots.csv")
    expected_timeline_content = None
    if os.path.isfile(plots_csv_path):
        try:
            with open(plots_csv_path, "r", encoding="utf-8", newline="") as f:
                raw = f.read()
            raw_norm = normalize_newlines(raw)
            f_io = StringIO(raw_norm)
            reader = csv.DictReader(f_io)
            fieldnames = reader.fieldnames
            rows = list(reader)
            # Sort by numeric order ascending
            def to_int_order(v):
                try:
                    return int(v)
                except Exception:
                    return float("inf")
            rows_sorted = sorted(rows, key=lambda r: to_int_order(r.get("order", "")))
            # Re-emit CSV with same header order
            out_io = StringIO()
            writer = csv.DictWriter(out_io, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            for r in rows_sorted:
                writer.writerow({k: r.get(k, "") for k in fieldnames})
            expected_timeline_content = out_io.getvalue()
        except Exception:
            expected_timeline_content = None

    # Check 3: timeline.csv
    timeline_path = os.path.join(output_dir, "timeline.csv")
    if expected_timeline_content is not None and os.path.isfile(timeline_path):
        actual_timeline = read_text(timeline_path)
        if actual_timeline is not None:
            if normalize_newlines(actual_timeline) == normalize_newlines(expected_timeline_content):
                checks["timeline_ok"] = True

    # Prepare character mentions ground truth
    characters_json_path = os.path.join(input_dir, "characters.json")
    characters_list = None
    chars_content = read_json(characters_json_path)
    if isinstance(chars_content, list):
        # Expect list of names (strings)
        try:
            characters_list = [str(x) for x in chars_content]
        except Exception:
            characters_list = None

    # Build combined chapter text for mentions
    combined_text = ""
    if chapters_available:
        combined_text = "\n".join(chapter_texts[name] for name in chapters_rel)

    mentions_expected = {}
    if characters_list is not None and chapters_available:
        for name in characters_list:
            # Case-insensitive whole-word match using word boundaries
            pattern = re.compile(r"\b" + re.escape(name) + r"\b", flags=re.IGNORECASE)
            count = len(list(pattern.finditer(combined_text)))
            mentions_expected[name] = count

    # Check 4: export.json
    export_path = os.path.join(output_dir, "export.json")
    if os.path.isfile(export_path) and characters_list is not None and chapters_available:
        export_out = read_json(export_path)
        if isinstance(export_out, list):
            try:
                # Validate chapter objects
                chapters_found = {n: False for n in chapters_rel}
                for obj in export_out:
                    if isinstance(obj, dict) and obj.get("type") == "chapter" and "filename" in obj:
                        fname = obj.get("filename")
                        if fname in chapters_found:
                            # Validate words and lines
                            words_ok = isinstance(obj.get("words"), int) and obj.get("words") == stats_expected[fname]["words"]
                            lines_ok = isinstance(obj.get("lines"), int) and obj.get("lines") == stats_expected[fname]["lines"]
                            if words_ok and lines_ok:
                                chapters_found[fname] = True
                chapters_ok = all(chapters_found.values())

                # Validate character objects
                characters_found = {n: False for n in characters_list}
                for obj in export_out:
                    if isinstance(obj, dict) and obj.get("type") == "character" and "name" in obj:
                        nm = obj.get("name")
                        if nm in characters_found:
                            mentions_ok = isinstance(obj.get("mentions"), int) and obj.get("mentions") == mentions_expected.get(nm, -1)
                            if mentions_ok:
                                characters_found[nm] = True
                characters_ok = all(characters_found.values())

                if chapters_ok and characters_ok:
                    checks["export_ok"] = True
            except Exception:
                pass

    # Check 5: report.md
    report_path = os.path.join(output_dir, "report.md")
    if os.path.isfile(report_path) and chapters_available and characters_list is not None:
        report_text = read_text(report_path)
        if isinstance(report_text, str):
            # Build expected substrings
            expected_substrings = []
            # Title
            expected_substrings.append("# Novel Report")
            # Totals
            expected_substrings.append(f"Total words: {totals_words}")
            expected_substrings.append(f"Total lines: {totals_lines}")
            # Character mentions (Avery, Blake, Casey) - ensure these three are checked specifically
            # We will compute mention counts from mentions_expected if present, default to 0 if missing
            for cname in ["Avery", "Blake", "Casey"]:
                cnt = mentions_expected.get(cname, 0)
                expected_substrings.append(f"{cname}: {cnt}")
            # Search summary
            total_matches = len(expected_search_lines)
            if search_term is None:
                # If missing term, expect zero matches with a generic pattern (but keep deterministic: require the exact formatting with empty term)
                # However, per task, there should be a term, so we handle gracefully
                expected_substrings.append(f'Search term "": {total_matches} matches')
            else:
                expected_substrings.append(f'Search term "{search_term}": {total_matches} matches')
            # Per-chapter summary lines
            for name in chapters_rel:
                w = stats_expected[name]["words"]
                l = stats_expected[name]["lines"]
                expected_substrings.append(f"{name} - words: {w}, lines: {l}")

            # Verify all substrings are present
            all_present = all(sub in report_text for sub in expected_substrings)
            if all_present:
                checks["report_ok"] = True

    # Compute reward as fraction of checks passed
    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    reward = passed / total if total > 0 else 0.0

    # Ensure reward in [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()