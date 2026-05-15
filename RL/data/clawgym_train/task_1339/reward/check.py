import json
import os
import re
import sys

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def load_prompts_and_constraints(input_dir):
    """
    Expected shape (most likely):
    {
      "min_words": 150,
      "max_words": 220,
      "tagline_max_len": 90,
      "prompts": [
        {"genre": "ghost", "prompt": "..."}, ...
      ]
    }
    Fallbacks supported:
    - constraints nested under "constraints"
    - top-level is a list of prompt objects
    """
    path = os.path.join(input_dir, "prompts.json")
    data = read_json(path)
    prompts = []
    constraints = {"min_words": None, "max_words": None, "tagline_max_len": None}

    if data is None:
        return prompts, constraints

    # Extract constraints
    if isinstance(data, dict):
        # direct
        for key in ["min_words", "max_words", "tagline_max_len"]:
            if key in data and isinstance(data[key], (int, float)):
                constraints[key] = int(data[key])
        # nested constraints
        if "constraints" in data and isinstance(data["constraints"], dict):
            c = data["constraints"]
            for key in ["min_words", "max_words", "tagline_max_len"]:
                if key in c and isinstance(c[key], (int, float)) and constraints[key] is None:
                    constraints[key] = int(c[key])
        # prompts list under common keys
        for k in ["prompts", "items", "seeds", "data"]:
            if k in data and isinstance(data[k], list):
                prompts_raw = data[k]
                break
        else:
            prompts_raw = None
    elif isinstance(data, list):
        prompts_raw = data
    else:
        prompts_raw = None

    if isinstance(prompts_raw, list):
        for it in prompts_raw:
            if isinstance(it, dict):
                ptxt = it.get("prompt") or it.get("text")
                genre = it.get("genre")
                if isinstance(ptxt, str) and isinstance(genre, str):
                    g = genre.strip().lower()
                    if g in {"ghost", "sci-fi"}:
                        prompts.append({"prompt": ptxt, "genre": g})
            elif isinstance(it, str):
                # Cannot infer genre reliably; skip to avoid false positives
                continue

    return prompts, constraints

def slugify(title):
    s = title.lower()
    s = s.replace(" ", "-")
    # remove characters not a-z0-9- 
    s = re.sub(r"[^a-z0-9\-]", "", s)
    # collapse multiple hyphens
    s = re.sub(r"-{2,}", "-", s)
    # trim hyphens
    s = s.strip("-")
    return s

def split_word_count(text):
    # Deterministic spec: split on whitespace
    parts = text.strip().split()
    return len([p for p in parts if p.strip() != ""])

def parse_jsonl(path):
    items = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        non_empty_lines = [ln for ln in lines if ln.strip() != ""]
        for ln in non_empty_lines:
            obj = json.loads(ln)
            items.append(obj)
        return True, items, len(non_empty_lines)
    except Exception:
        return False, [], 0

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "tales_exists": False,
        "tales_valid_jsonl": False,
        "tales_line_count_matches_prompts": False,
        "all_required_keys_present": False,
        "titles_unique": False,
        "ids_slugified": False,
        "genres_match": False,
        "prompts_covered_exactly_once": False,
        "bodies_include_prompt": False,
        "word_counts_match_and_within_range": False,
        "taglines_valid": False,
        "genre_distribution_sufficient": False,
        "index_exists": False,
        "index_has_h1": False,
        "foreword_exists": False,
        "foreword_word_count_in_range": False,
        "foreword_references_at_least_two_titles": False,
        "toc_covers_all_stories": False,
        "qc_exists": False,
        "qc_valid_json": False,
        "qc_metrics_match": False,
    }

    # Load inputs
    prompts_list, constraints = load_prompts_and_constraints(input_dir)
    prompt_to_genre = {p["prompt"]: p["genre"] for p in prompts_list if "prompt" in p and "genre" in p}
    N = len(prompts_list)

    tales_path = os.path.join(output_dir, "tales.jsonl")
    if os.path.isfile(tales_path):
        checks["tales_exists"] = True

        valid_jsonl, stories, non_empty_lines = parse_jsonl(tales_path)
        if valid_jsonl:
            checks["tales_valid_jsonl"] = True

            # Check line count equals number of prompts
            if N > 0 and non_empty_lines == N:
                checks["tales_line_count_matches_prompts"] = True

            # Required keys presence
            required_keys = {"id", "title", "genre", "prompt", "tagline", "body", "word_count"}
            keys_ok = True
            for s in stories:
                if not isinstance(s, dict) or not required_keys.issubset(set(s.keys())):
                    keys_ok = False
                    break
                # types sanity
                if not isinstance(s.get("id"), str): keys_ok = False; break
                if not isinstance(s.get("title"), str): keys_ok = False; break
                if not isinstance(s.get("genre"), str): keys_ok = False; break
                if not isinstance(s.get("prompt"), str): keys_ok = False; break
                if not isinstance(s.get("tagline"), str): keys_ok = False; break
                if not isinstance(s.get("body"), str): keys_ok = False; break
                # word_count must be int
                if not isinstance(s.get("word_count"), int):
                    # allow float that is int-equivalent?
                    wc = s.get("word_count")
                    if isinstance(wc, float) and wc.is_integer():
                        s["word_count"] = int(wc)
                    else:
                        keys_ok = False
                        break
            if keys_ok:
                checks["all_required_keys_present"] = True

            # Titles unique
            if keys_ok:
                titles = [s["title"] for s in stories]
                if len(set(titles)) == len(titles) and len(titles) > 0:
                    checks["titles_unique"] = True

            # IDs slugified
            if keys_ok:
                ids_ok = True
                for s in stories:
                    expected = slugify(s["title"])
                    sid = s["id"]
                    # only allowed chars
                    if not re.fullmatch(r"[a-z0-9\-]+", sid or ""):
                        ids_ok = False
                        break
                    if sid != expected:
                        ids_ok = False
                        break
                    if sid.startswith("-") or sid.endswith("-"):
                        ids_ok = False
                        break
                if ids_ok:
                    checks["ids_slugified"] = True

            # Genres match prompt mapping and coverage
            if keys_ok and N > 0:
                genres_ok = True
                bodies_include_prompt_ok = True
                wc_ok = True
                tag_ok = True

                # Use constraints; if missing, default to typical values
                min_w = constraints["min_words"] if isinstance(constraints.get("min_words"), int) else None
                max_w = constraints["max_words"] if isinstance(constraints.get("max_words"), int) else None
                tag_len = constraints["tagline_max_len"] if isinstance(constraints.get("tagline_max_len"), int) else None

                # If constraints missing, set to None and relax those checks? Spec requires to honor constraints from input.
                # We'll only assert within range if both min and max are present.
                prompts_out = []
                by_genre_counts = {"ghost": 0, "sci-fi": 0}
                for s in stories:
                    pr = s["prompt"]
                    g = s["genre"].strip().lower() if isinstance(s.get("genre"), str) else ""
                    if pr not in prompt_to_genre:
                        genres_ok = False
                    else:
                        if g != prompt_to_genre[pr]:
                            genres_ok = False
                    prompts_out.append(pr)

                    # body includes prompt
                    body = s["body"]
                    if not isinstance(body, str) or pr not in body:
                        bodies_include_prompt_ok = False

                    # word count exact and within range
                    actual_wc = split_word_count(body)
                    if actual_wc != s["word_count"]:
                        wc_ok = False
                    if min_w is not None and max_w is not None:
                        if not (min_w <= actual_wc <= max_w):
                            wc_ok = False

                    # tagline constraints
                    tagline = s["tagline"]
                    if not isinstance(tagline, str):
                        tag_ok = False
                    else:
                        if "\n" in tagline or "\r" in tagline:
                            tag_ok = False
                        if tag_len is not None and len(tagline) > tag_len:
                            tag_ok = False

                    # genre count
                    if g in by_genre_counts:
                        by_genre_counts[g] += 1

                if genres_ok:
                    checks["genres_match"] = True

                # Coverage: prompts used exactly once and all present
                if N > 0:
                    if len(prompts_out) == N and set(prompts_out) == set(prompt_to_genre.keys()):
                        # also ensure each output prompt appears exactly once
                        counts = {}
                        for pr in prompts_out:
                            counts[pr] = counts.get(pr, 0) + 1
                        if all(v == 1 for v in counts.values()):
                            checks["prompts_covered_exactly_once"] = True

                if bodies_include_prompt_ok:
                    checks["bodies_include_prompt"] = True
                if wc_ok:
                    checks["word_counts_match_and_within_range"] = True
                if tag_ok:
                    checks["taglines_valid"] = True

                # Genre distribution
                if by_genre_counts.get("ghost", 0) >= 2 and by_genre_counts.get("sci-fi", 0) >= 2:
                    checks["genre_distribution_sufficient"] = True

            # Index.md checks
            index_path = os.path.join(output_dir, "index.md")
            if os.path.isfile(index_path):
                checks["index_exists"] = True
                try:
                    with open(index_path, "r", encoding="utf-8") as f:
                        index_text = f.read()
                    lines = index_text.splitlines()
                    # H1 presence
                    has_h1 = any(ln.strip().startswith("# ") for ln in lines)
                    if has_h1:
                        checks["index_has_h1"] = True

                    # Foreword detection
                    fw_idx = None
                    for i, ln in enumerate(lines):
                        if "Editor's Foreword" in ln:
                            fw_idx = i
                            break
                    if fw_idx is not None and fw_idx < len(lines) - 1:
                        checks["foreword_exists"] = True
                        # Collect text until next heading line starting with '#'
                        fw_lines = []
                        for j in range(fw_idx + 1, len(lines)):
                            if lines[j].strip().startswith("#"):
                                break
                            fw_lines.append(lines[j])
                        fw_text = "\n".join(fw_lines).strip()
                        fw_wc = len(fw_text.split())
                        if 120 <= fw_wc <= 200:
                            checks["foreword_word_count_in_range"] = True
                        # Reference at least two distinct titles
                        titles = [s.get("title") for s in stories if isinstance(s, dict)]
                        referenced = set()
                        for t in titles:
                            if isinstance(t, str) and t in fw_text:
                                referenced.add(t)
                        if len(referenced) >= 2:
                            checks["foreword_references_at_least_two_titles"] = True

                    # Table of contents coverage: each title with its genre and tagline on same line
                    toc_ok = True
                    for s in stories:
                        title = s.get("title", "")
                        genre = s.get("genre", "")
                        tagline = s.get("tagline", "")
                        found_line = False
                        for ln in lines:
                            if title in ln and genre in ln and tagline in ln:
                                found_line = True
                                break
                        if not found_line:
                            toc_ok = False
                            break
                    if toc_ok and len(stories) > 0:
                        checks["toc_covers_all_stories"] = True
                except Exception:
                    # leave index-related checks as False if parsing fails
                    pass

            # QC report checks
            qc_path = os.path.join(output_dir, "qc_report.json")
            if os.path.isfile(qc_path):
                checks["qc_exists"] = True
                qc = read_json(qc_path)
                if isinstance(qc, dict):
                    # Validate presence of keys
                    has_keys = (
                        "total" in qc and
                        "by_genre" in qc and isinstance(qc["by_genre"], dict) and
                        "ghost" in qc["by_genre"] and "sci-fi" in qc["by_genre"] and
                        "avg_word_count" in qc
                    )
                    if has_keys:
                        checks["qc_valid_json"] = True
                        # Recompute metrics
                        total = len(stories)
                        by_genre = {"ghost": 0, "sci-fi": 0}
                        wc_sum = 0
                        wc_count = 0
                        for s in stories:
                            g = s.get("genre", "").strip().lower()
                            if g in by_genre:
                                by_genre[g] += 1
                            wc = s.get("word_count")
                            if isinstance(wc, int):
                                wc_sum += wc
                                wc_count += 1
                        avg_wc = (wc_sum / wc_count) if wc_count > 0 else 0.0
                        try:
                            qc_total = int(qc["total"])
                            qc_ghost = int(qc["by_genre"]["ghost"])
                            qc_scifi = int(qc["by_genre"]["sci-fi"])
                            qc_avg = float(qc["avg_word_count"])
                            if (
                                qc_total == total and
                                qc_ghost == by_genre["ghost"] and
                                qc_scifi == by_genre["sci-fi"] and
                                abs(qc_avg - avg_wc) <= 1e-6
                            ):
                                checks["qc_metrics_match"] = True
                        except Exception:
                            pass

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # Ensure no-op baseline yields 0.0
    if not os.path.isdir(output_dir) or all(not checks[k] for k in checks):
        reward = 0.0
    else:
        reward = passed / total_checks if total_checks > 0 else 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()