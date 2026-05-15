import json
import csv
import hashlib
import re
from datetime import datetime
from pathlib import Path
import sys


def read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None


def read_json_file(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_afinn_lexicon(path: Path):
    if not path.exists():
        return None
    try:
        mapping = {}
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # AFINN-111 is tab-separated: token<TAB>score
                parts = line.split("\t")
                if len(parts) != 2:
                    # try whitespace split as fallback
                    parts = line.split()
                    if len(parts) != 2:
                        return None
                token = parts[0].strip().lower()
                try:
                    score = int(parts[1].strip())
                except Exception:
                    return None
                if token:
                    mapping[token] = score
        if not mapping:
            return None
        return mapping
    except Exception:
        return None


def tokenize_regex_alpha(text: str):
    # case-insensitive tokens: sequences of letters and apostrophes
    return re.findall(r"[A-Za-z']+", text.lower())


def tokenize_whitespace_alpha(text: str):
    # Replace non-letters with space, split on whitespace
    cleaned = re.sub(r"[^A-Za-z']+", " ", text.lower())
    tokens = [t for t in cleaned.split() if t]
    return tokens


def parse_story_header(text: str):
    # Expect exactly three header lines:
    # Title: <movie title>
    # Year: <4-digit year>
    # ---
    # followed by body
    if text is None:
        return None
    lines = text.splitlines()
    if len(lines) < 4:
        return None
    title_line = lines[0].strip()
    year_line = lines[1].strip()
    sep_line = lines[2].strip()
    if not title_line.startswith("Title: "):
        return None
    if not year_line.startswith("Year: "):
        return None
    if sep_line != "---":
        return None
    title = title_line[len("Title: "):].strip()
    year_str = year_line[len("Year: "):].strip()
    if not re.fullmatch(r"\d{4}", year_str):
        return None
    try:
        year = int(year_str)
    except Exception:
        return None
    body = "\n".join(lines[3:])
    return {"title": title, "year": year, "body": body}


def is_iso8601(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    try:
        s2 = s
        if s2.endswith("Z"):
            s2 = s2[:-1] + "+00:00"
        datetime.fromisoformat(s2)
        return True
    except Exception:
        return False


def sha256_of_file(path: Path) -> str:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def load_processed_registry(path: Path):
    if not path.exists():
        return None
    try:
        entries = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                entries.append(obj)
        return entries
    except Exception:
        return None


def load_index_csv(path: Path):
    if not path.exists():
        return None, None
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, None
        header = rows[0]
        data_rows = rows[1:]
        return header, data_rows
    except Exception:
        return None, None


def compute_afinn_metrics(body: str, lexicon: dict):
    # Compute metrics with two tokenization strategies and return both
    tokens_a = tokenize_regex_alpha(body)
    tokens_b = tokenize_whitespace_alpha(body)

    def stats(tokens):
        word_count = len(tokens)
        score = 0
        freqs = {}
        for t in tokens:
            if t in lexicon:
                score += lexicon[t]
            freqs[t] = freqs.get(t, 0) + 1
        return word_count, score, freqs

    wc_a, score_a, freqs_a = stats(tokens_a)
    wc_b, score_b, freqs_b = stats(tokens_b)
    return (wc_a, score_a, freqs_a), (wc_b, score_b, freqs_b)


def validate_top_list(selected_list, freqs, lexicon, positive=True):
    # Validate:
    # - list length <= 10
    # - all strings and unique
    # - ordered by non-increasing frequency
    # - all tokens in lexicon with correct sign
    # - "topness": all tokens with freq strictly greater than last included freq are included
    if selected_list is None:
        return False
    if not isinstance(selected_list, list):
        return False
    if len(selected_list) > 10:
        return False
    seen = set()
    prev_freq = None
    # determine threshold frequency (freq of last included token)
    if len(selected_list) > 0:
        last_freq = freqs.get(selected_list[-1], 0)
    else:
        last_freq = float("inf")  # empty list is vacuously valid; no topness requirement
    for w in selected_list:
        if not isinstance(w, str):
            return False
        if w in seen:
            return False
        seen.add(w)
        # check lexicon and sign
        if w not in lexicon:
            return False
        if positive and lexicon[w] <= 0:
            return False
        if (not positive) and lexicon[w] >= 0:
            return False
        # check monotonicity
        fw = freqs.get(w, 0)
        if prev_freq is None:
            prev_freq = fw
        else:
            if fw > prev_freq:
                return False
            prev_freq = fw
    # Topness: ensure all tokens with strictly greater freq than the last included are included
    if len(selected_list) > 0:
        for w, f in freqs.items():
            if w in lexicon and ((positive and lexicon[w] > 0) or ((not positive) and lexicon[w] < 0)):
                if f > last_freq and w not in seen:
                    return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "lexicon_file_present": 0.0,
        "lexicon_file_parses": 0.0,
        "processed_summary_present": 0.0,
        "summary_core_fields_match_header": 0.0,
        "word_count_plausible_and_correct": 0.0,
        "afinn_score_correct": 0.0,
        "top_positive_words_valid": 0.0,
        "top_negative_words_valid": 0.0,
        "validation_and_warnings_valid": 0.0,
        "lexicon_metadata_fields_correct": 0.0,
        "processed_registry_entry_present_and_correct": 0.0,
        "index_csv_row_present_and_correct": 0.0,
    }

    # Load filmography
    filmography_path = workspace / "input" / "filmography.json"
    filmography = read_json_file(filmography_path)
    film_set = set()
    if isinstance(filmography, dict) and isinstance(filmography.get("filmography"), list):
        for item in filmography["filmography"]:
            title = item.get("title")
            year = item.get("year")
            if isinstance(title, str) and isinstance(year, int):
                film_set.add((title, year))
    else:
        filmography = None

    # Find input stories
    inbox_dir = workspace / "input" / "stories" / "inbox"
    input_story_files = []
    if inbox_dir.exists() and inbox_dir.is_dir():
        for p in sorted(inbox_dir.glob("*.txt")):
            input_story_files.append(p)

    # Load AFINN lexicon cache
    lexicon_cached_rel = Path("cache/lexicons/afinn/AFINN-111.txt")
    lexicon_cached_path = workspace / lexicon_cached_rel
    if lexicon_cached_path.exists() and lexicon_cached_path.is_file():
        scores["lexicon_file_present"] = 1.0
    lexicon = load_afinn_lexicon(lexicon_cached_path)
    if lexicon is not None:
        scores["lexicon_file_parses"] = 1.0

    # Aggregate checks across all input files
    if not input_story_files:
        # Nothing to evaluate beyond lexicon presence/parse
        return scores

    all_summaries_present = True
    all_core_fields_match = True
    all_word_counts_ok = True
    all_afinn_scores_ok = True
    all_top_pos_ok = True
    all_top_neg_ok = True
    all_validation_ok = True
    all_lexicon_meta_ok = True
    all_registry_ok = True
    all_index_ok = True

    # Load registry and index once
    registry_path = workspace / "state" / "processed.jsonl"
    registry_entries = load_processed_registry(registry_path)
    index_path = workspace / "output" / "stories" / "index.csv"
    index_header, index_rows = load_index_csv(index_path)

    for story_path in input_story_files:
        story_rel = story_path.as_posix()
        story_content = read_text_file(story_path)
        header = parse_story_header(story_content)
        basename = story_path.stem
        summary_path = workspace / "output" / "stories" / "processed" / f"{basename}_summary.json"
        summary_obj = read_json_file(summary_path)

        if summary_obj is None:
            all_summaries_present = False
            all_core_fields_match = False
            all_word_counts_ok = False
            all_afinn_scores_ok = False
            all_top_pos_ok = False
            all_top_neg_ok = False
            all_validation_ok = False
            all_lexicon_meta_ok = False
            all_registry_ok = False
            all_index_ok = False
            continue

        # Check summary core fields
        input_file_in_summary = summary_obj.get("input_file")
        title_in_summary = summary_obj.get("title")
        year_in_summary = summary_obj.get("year")

        if header is None:
            all_core_fields_match = False
        else:
            expected_rel = Path("input") / "stories" / "inbox" / story_path.name
            if input_file_in_summary != expected_rel.as_posix():
                all_core_fields_match = False
            if title_in_summary != header["title"]:
                all_core_fields_match = False
            if year_in_summary != header["year"]:
                all_core_fields_match = False

        # Word count check (plausible variants)
        body = header["body"] if header else ""
        wc_summary = summary_obj.get("word_count")
        if not isinstance(wc_summary, int):
            all_word_counts_ok = False
        else:
            # compute plausible counts (two tokenization strategies and a whitespace-only split)
            tokens_a = tokenize_regex_alpha(body)
            tokens_b = tokenize_whitespace_alpha(body)
            tokens_ws = [t for t in body.strip().split() if t]
            plausible_counts = {len(tokens_a), len(tokens_b), len(tokens_ws)}
            if wc_summary not in plausible_counts:
                all_word_counts_ok = False

        # AFINN score check
        afinn_score_summary = summary_obj.get("afinn_sentiment_score")
        if lexicon is None or header is None:
            all_afinn_scores_ok = False
        else:
            metrics_a, metrics_b = compute_afinn_metrics(body, lexicon)
            score_a = metrics_a[1]
            score_b = metrics_b[1]
            try:
                # Accept int or float equal to computed
                if isinstance(afinn_score_summary, (int, float)):
                    if float(afinn_score_summary) != float(score_a) and float(afinn_score_summary) != float(score_b):
                        all_afinn_scores_ok = False
                else:
                    all_afinn_scores_ok = False
            except Exception:
                all_afinn_scores_ok = False

        # Top positive/negative words validation
        top_pos = summary_obj.get("top_positive_words")
        top_neg = summary_obj.get("top_negative_words")
        if lexicon is None or header is None:
            all_top_pos_ok = False
            all_top_neg_ok = False
        else:
            freqs_a = compute_afinn_metrics(body, lexicon)[0][2]
            freqs_b = compute_afinn_metrics(body, lexicon)[1][2]

            valid_pos = validate_top_list(top_pos, freqs_a, lexicon, positive=True) or validate_top_list(top_pos, freqs_b, lexicon, positive=True)
            valid_neg = validate_top_list(top_neg, freqs_a, lexicon, positive=False) or validate_top_list(top_neg, freqs_b, lexicon, positive=False)
            if not valid_pos:
                all_top_pos_ok = False
            if not valid_neg:
                all_top_neg_ok = False

        # Validation and warnings
        validation_flag = summary_obj.get("validation")
        warnings_list = summary_obj.get("warnings")
        if header is None or filmography is None:
            all_validation_ok = False
        else:
            should_validate = (header["title"], header["year"]) in film_set
            if validation_flag is not should_validate:
                all_validation_ok = False
            else:
                if should_validate:
                    # warnings should be empty
                    if not isinstance(warnings_list, list) or len(warnings_list) != 0:
                        all_validation_ok = False
                else:
                    if not isinstance(warnings_list, list) or len(warnings_list) == 0:
                        all_validation_ok = False

        # Lexicon metadata fields
        lexicon_source = summary_obj.get("lexicon_source")
        lexicon_cached_path_field = summary_obj.get("lexicon_cached_path")
        time_processed = summary_obj.get("time_processed")
        meta_ok = True
        if lexicon_source != "AFINN-111 (fnielsen/afinn)":
            meta_ok = False
        if not isinstance(lexicon_cached_path_field, str) or Path(lexicon_cached_path_field).as_posix() != lexicon_cached_rel.as_posix():
            meta_ok = False
        # time_processed ISO 8601
        if not is_iso8601(time_processed):
            meta_ok = False
        # ensure cached path exists
        if not (workspace / Path(lexicon_cached_path_field)).exists():
            meta_ok = False
        if not meta_ok:
            all_lexicon_meta_ok = False

        # Processed registry check
        if registry_entries is None:
            all_registry_ok = False
        else:
            # Must contain an entry with input_file, sha256 of story file, and ISO time.
            sha = sha256_of_file(story_path)
            found = False
            for entry in registry_entries:
                if not isinstance(entry, dict):
                    all_registry_ok = False
                    found = False
                    break
                if entry.get("input_file") == (Path("input") / "stories" / "inbox" / story_path.name).as_posix() and entry.get("sha256") == sha:
                    if is_iso8601(entry.get("time_processed", "")):
                        found = True
                        break
            if not found:
                all_registry_ok = False

        # Index CSV check
        if index_header is None or index_rows is None:
            all_index_ok = False
        else:
            expected_header = ["input_file", "title", "year", "word_count", "afinn_sentiment_score", "time_processed"]
            if index_header != expected_header:
                all_index_ok = False
            else:
                # find row for this input_file
                input_rel_expected = (Path("input") / "stories" / "inbox" / story_path.name).as_posix()
                matched = False
                for row in index_rows:
                    if len(row) != len(expected_header):
                        all_index_ok = False
                        matched = True  # prevent double-failing
                        break
                    if row[0] == input_rel_expected:
                        # Compare with summary fields
                        try:
                            title_csv = row[1]
                            year_csv = int(row[2])
                            wc_csv = int(row[3])
                            afinn_csv = float(row[4])
                            time_csv = row[5]
                            # Title, year
                            if header:
                                if title_csv != header["title"]:
                                    all_index_ok = False
                                if year_csv != header["year"]:
                                    all_index_ok = False
                            # word_count (allow plausible variants)
                            body_local = header["body"] if header else ""
                            tokens_a = tokenize_regex_alpha(body_local)
                            tokens_b = tokenize_whitespace_alpha(body_local)
                            tokens_ws = [t for t in body_local.strip().split() if t]
                            plausible_counts = {len(tokens_a), len(tokens_b), len(tokens_ws)}
                            if wc_csv not in plausible_counts:
                                all_index_ok = False
                            # afinn score
                            if lexicon is not None and header is not None:
                                metrics_a, metrics_b = compute_afinn_metrics(body_local, lexicon)
                                score_a = float(metrics_a[1])
                                score_b = float(metrics_b[1])
                                if abs(afinn_csv - score_a) > 1e-9 and abs(afinn_csv - score_b) > 1e-9:
                                    all_index_ok = False
                            else:
                                # If lexicon missing, cannot verify scored value; mark as fail
                                all_index_ok = False
                            # time processed ISO
                            if not is_iso8601(time_csv):
                                all_index_ok = False
                            matched = True
                        except Exception:
                            all_index_ok = False
                            matched = True
                        break
                if not matched:
                    all_index_ok = False

    # Assign scores based on aggregate booleans
    scores["processed_summary_present"] = 1.0 if all_summaries_present else 0.0
    scores["summary_core_fields_match_header"] = 1.0 if all_core_fields_match else 0.0
    scores["word_count_plausible_and_correct"] = 1.0 if all_word_counts_ok else 0.0
    scores["afinn_score_correct"] = 1.0 if all_afinn_scores_ok else 0.0
    scores["top_positive_words_valid"] = 1.0 if all_top_pos_ok else 0.0
    scores["top_negative_words_valid"] = 1.0 if all_top_neg_ok else 0.0
    scores["validation_and_warnings_valid"] = 1.0 if all_validation_ok else 0.0
    scores["lexicon_metadata_fields_correct"] = 1.0 if all_lexicon_meta_ok else 0.0
    scores["processed_registry_entry_present_and_correct"] = 1.0 if all_registry_ok else 0.0
    scores["index_csv_row_present_and_correct"] = 1.0 if all_index_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=None, separators=(",", ":")))


if __name__ == "__main__":
    main()