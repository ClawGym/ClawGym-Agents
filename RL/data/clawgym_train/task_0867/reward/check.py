import csv
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            rows = list(reader)
            return rows
    except Exception:
        return None


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def _parse_lesson_config_yaml(yaml_path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML parser for the expected structure.
    """
    text = _read_text(yaml_path)
    if text is None:
        return None
    site_name = None
    lesson_title = None
    story_title = None
    outputs_dir = None
    deploy_dir = None
    vocabulary: List[str] = []

    lines = text.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if "#" in line:
            before, _, _ = line.partition("#")
            line = before
        line = line.rstrip()
        if not line.strip():
            i += 1
            continue
        if ":" in line and not line.strip().startswith("-"):
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if key == "site_name":
                site_name = _strip_quotes(value)
            elif key == "lesson_title":
                lesson_title = _strip_quotes(value)
            elif key == "story_title":
                story_title = _strip_quotes(value)
            elif key == "outputs_dir":
                outputs_dir = _strip_quotes(value)
            elif key == "deploy_dir":
                deploy_dir = _strip_quotes(value)
            elif key == "vocabulary":
                i += 1
                while i < n:
                    l2 = lines[i]
                    if "#" in l2:
                        before2, _, _ = l2.partition("#")
                        l2 = before2
                    l2_clean = l2.strip()
                    if not l2_clean:
                        i += 1
                        continue
                    if not l2.lstrip().startswith("-"):
                        i -= 1
                        break
                    _, _, item = l2.partition("-")
                    item = _strip_quotes(item.strip())
                    if item:
                        vocabulary.append(item)
                    i += 1
        i += 1

    cfg: Dict[str, Any] = {
        "site_name": site_name,
        "lesson_title": lesson_title,
        "story_title": story_title,
        "outputs_dir": outputs_dir,
        "deploy_dir": deploy_dir,
        "vocabulary": vocabulary,
    }
    for k in ["site_name", "lesson_title", "story_title", "outputs_dir", "deploy_dir"]:
        if not isinstance(cfg.get(k), str) or not cfg.get(k):
            return None
    if not isinstance(cfg.get("vocabulary"), list) or not all(isinstance(x, str) and x for x in cfg["vocabulary"]):
        return None
    return cfg


def _compute_sha256(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _sentence_spans_in_line(line: str) -> List[Tuple[int, int]]:
    spans: List[Tuple[int, int]] = []
    start = 0
    i = 0
    L = len(line)
    while i < L:
        ch = line[i]
        if ch in ".!?":
            end_excl = i + 1
            spans.append((start, end_excl))
            start = end_excl
        i += 1
    if not spans:
        if L > 0:
            spans.append((0, L))
    else:
        if start < L:
            if line[start:].strip():
                spans.append((start, L))
    return spans


def _find_all_occurrences_ci(haystack: str, needle: str) -> List[int]:
    starts: List[int] = []
    if not needle:
        return starts
    hl = haystack.lower()
    nl = needle.lower()
    i = 0
    while True:
        idx = hl.find(nl, i)
        if idx == -1:
            break
        starts.append(idx)
        i = idx + max(1, len(nl))
    return starts


def _compute_expected_vocab_instances(cfg: Dict[str, Any], excerpt_path: Path) -> Optional[List[Dict[str, Any]]]:
    text = _read_text(excerpt_path)
    if text is None:
        return None
    lines = text.splitlines()
    vocab = cfg["vocabulary"]
    expected: List[Dict[str, Any]] = []
    for line_idx, line in enumerate(lines, start=1):
        sent_spans = _sentence_spans_in_line(line)
        for word in vocab:
            occs = _find_all_occurrences_ci(line, word)
            for start in occs:
                end = start + len(word)
                sentence_text = line
                if sent_spans:
                    for (s0, s1) in sent_spans:
                        if start >= s0 and start < s1:
                            sentence_text = line[s0:s1]
                            break
                sentence_text = sentence_text.strip()
                expected.append({
                    "word": word.lower(),
                    "line_number": line_idx,
                    "match_start": start,
                    "match_end": end,
                    "sentence": sentence_text,
                })
    expected.sort(key=lambda x: (x["word"], x["line_number"], x["match_start"], x["match_end"]))
    return expected


def _canonicalize_instances_for_compare(instances: Any) -> Optional[List[Dict[str, Any]]]:
    if not isinstance(instances, list):
        return None
    canon: List[Dict[str, Any]] = []
    for obj in instances:
        if not isinstance(obj, dict):
            return None
        required = ["word", "line_number", "match_start", "match_end", "sentence"]
        for k in required:
            if k not in obj:
                return None
        word = obj["word"]
        line_number = obj["line_number"]
        match_start = obj["match_start"]
        match_end = obj["match_end"]
        sentence = obj["sentence"]
        if not isinstance(word, str):
            return None
        if not isinstance(line_number, int):
            return None
        if not isinstance(match_start, int):
            return None
        if not isinstance(match_end, int):
            return None
        if not isinstance(sentence, str):
            return None
        canon.append({
            "word": word,
            "line_number": line_number,
            "match_start": match_start,
            "match_end": match_end,
            "sentence": sentence,
        })
    canon.sort(key=lambda x: (x["word"], x["line_number"], x["match_start"], x["match_end"]))
    return canon


def _aggregate_counts_from_instances(instances: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for obj in instances:
        w = obj["word"].lower()
        counts[w] = counts.get(w, 0) + 1
    return counts


def _parse_questions_md(md_path: Path) -> Optional[List[Dict[str, Any]]]:
    text = _read_text(md_path)
    if text is None:
        return None
    lines = text.splitlines()
    current_category: Optional[str] = None
    questions: List[Dict[str, Any]] = []
    per_cat_count: Dict[str, int] = {}
    for line in lines:
        if line.startswith("## "):
            current_category = line[3:].strip()
            if current_category not in per_cat_count:
                per_cat_count[current_category] = 0
            continue
        if current_category is not None:
            m = re.match(r'^\s*(\d+)\.\s+(.*\S)\s*$', line)
            if m:
                per_cat_count[current_category] += 1
                num_within = per_cat_count[current_category]
                text_q = m.group(2).strip()
                questions.append({
                    "category": current_category,
                    "number": num_within,
                    "text": text_q,
                })
    return questions


def _canonicalize_questions_json(objs: Any) -> Optional[List[Dict[str, Any]]]:
    if not isinstance(objs, list):
        return None
    canon: List[Dict[str, Any]] = []
    for obj in objs:
        if not isinstance(obj, dict):
            return None
        for k in ["category", "number", "text"]:
            if k not in obj:
                return None
        category = obj["category"]
        number = obj["number"]
        text_q = obj["text"]
        if not isinstance(category, str) or not isinstance(number, int) or not isinstance(text_q, str):
            return None
        canon.append({"category": category, "number": number, "text": text_q})
    return canon


def _number_present_as_token(html: str, number: int) -> bool:
    pattern = r'(?<!\d)' + re.escape(str(number)) + r'(?!\d)'
    return re.search(pattern, html) is not None


def _normalize_relpath(p: Path, workspace: Path) -> str:
    try:
        rel = p.relative_to(workspace)
    except Exception:
        rel = p
    return str(rel).replace("\\", "/")


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "vocab_instances_correct": 0.0,
        "vocab_summary_csv_correct": 0.0,
        "questions_json_correct": 0.0,
        "index_html_has_titles": 0.0,
        "index_html_has_counts": 0.0,
        "index_html_has_links": 0.0,
        "deployment_report_fields_valid": 0.0,
        "deployment_report_generated_files_listed": 0.0,
    }

    cfg_path = workspace / "config" / "lesson_config.yaml"
    cfg = _parse_lesson_config_yaml(cfg_path)
    if cfg is None:
        return scores

    outputs_dir_name = cfg["outputs_dir"]
    deploy_dir_name = cfg["deploy_dir"]
    outputs_dir = workspace / outputs_dir_name
    deploy_dir = workspace / deploy_dir_name

    excerpt_path = workspace / "input" / "charles_excerpt.txt"
    expected_instances = _compute_expected_vocab_instances(cfg, excerpt_path)
    expected_counts: Dict[str, int] = {}
    total_vocab_occurrences_expected = 0
    if expected_instances is not None:
        expected_counts = _aggregate_counts_from_instances(expected_instances)
        total_vocab_occurrences_expected = sum(expected_counts.values())

    vi_path = outputs_dir / "vocab_instances.json"
    vi = _load_json(vi_path)
    vi_canon = _canonicalize_instances_for_compare(vi) if vi is not None else None
    if expected_instances is not None and vi_canon is not None:
        if vi_canon == expected_instances:
            scores["vocab_instances_correct"] = 1.0

    vs_path = outputs_dir / "vocab_summary.csv"
    rows = _load_csv_dicts(vs_path)
    csv_ok = False
    if rows is not None and expected_instances is not None:
        try:
            with vs_path.open("r", encoding="utf-8", newline="") as f:
                header_line = f.readline().strip()
        except Exception:
            header_line = ""
        if header_line == "word,occurrences":
            counts_csv: Dict[str, int] = {}
            malformed = False
            for r in rows:
                if set(r.keys()) != {"word", "occurrences"}:
                    malformed = True
                    break
                w = (r["word"] or "").strip()
                try:
                    occ = int((r["occurrences"] or "").strip())
                except Exception:
                    malformed = True
                    break
                counts_csv[w.lower()] = occ
            if not malformed:
                vocab_lower_set = {w.lower() for w in cfg["vocabulary"]}
                if set(counts_csv.keys()) == vocab_lower_set:
                    if all(counts_csv.get(w.lower(), -1) == expected_counts.get(w.lower(), 0) for w in cfg["vocabulary"]):
                        if vi_canon is not None:
                            counts_from_vi = _aggregate_counts_from_instances(vi_canon)
                            if all(counts_csv.get(w.lower(), -1) == counts_from_vi.get(w.lower(), 0) for w in cfg["vocabulary"]):
                                csv_ok = True
                        else:
                            csv_ok = True
    if csv_ok:
        scores["vocab_summary_csv_correct"] = 1.0

    q_input_path = workspace / "input" / "questions.md"
    expected_questions = _parse_questions_md(q_input_path)
    q_out_path = outputs_dir / "questions.json"
    q_out = _load_json(q_out_path)
    q_out_canon = _canonicalize_questions_json(q_out) if q_out is not None else None
    if expected_questions is not None and q_out_canon is not None:
        if q_out_canon == expected_questions:
            scores["questions_json_correct"] = 1.0

    index_path = deploy_dir / "index.html"
    index_html = _read_text(index_path)
    if index_html is not None:
        if (cfg["site_name"] in index_html) and (cfg["lesson_title"] in index_html):
            scores["index_html_has_titles"] = 1.0
        total_vocab_words = len(cfg["vocabulary"])
        total_questions = len(expected_questions) if expected_questions is not None else None
        counts_ok = True
        if not _number_present_as_token(index_html, total_vocab_words):
            counts_ok = False
        if expected_instances is not None:
            if not _number_present_as_token(index_html, total_vocab_occurrences_expected):
                counts_ok = False
        else:
            counts_ok = False
        if total_questions is not None:
            if not _number_present_as_token(index_html, total_questions):
                counts_ok = False
        else:
            counts_ok = False
        if counts_ok:
            scores["index_html_has_counts"] = 1.0
        expected_links = [
            f"{outputs_dir_name}/vocab_summary.csv",
            f"{outputs_dir_name}/vocab_instances.json",
            f"{outputs_dir_name}/questions.json",
        ]
        links_ok = all(link in index_html for link in expected_links)
        if links_ok:
            scores["index_html_has_links"] = 1.0

    dep_report_path = deploy_dir / "deployment_report.json"
    dep = _load_json(dep_report_path)
    dep_fields_ok = False
    dep_genfiles_ok = False
    if isinstance(dep, dict):
        required_keys = ["site_name", "lesson_title", "story_title", "outputs_dir", "deploy_dir", "vocabulary", "counts", "excerpt_sha256", "generated_files"]
        has_all = all(k in dep for k in required_keys)
        if has_all and isinstance(dep.get("counts"), dict):
            try:
                site_ok = dep["site_name"] == cfg["site_name"]
                lesson_ok = dep["lesson_title"] == cfg["lesson_title"]
                story_ok = dep["story_title"] == cfg["story_title"]
                outputs_ok = dep["outputs_dir"] == cfg["outputs_dir"]
                deploy_ok = dep["deploy_dir"] == cfg["deploy_dir"]
                vocab_ok = isinstance(dep["vocabulary"], list) and dep["vocabulary"] == cfg["vocabulary"]
                counts = dep["counts"]
                counts_ok = False
                if expected_instances is not None and expected_questions is not None:
                    counts_ok = (
                        counts.get("vocabulary_words") == len(cfg["vocabulary"]) and
                        counts.get("vocabulary_occurrences") == sum(_aggregate_counts_from_instances(expected_instances).values()) and
                        counts.get("questions") == len(expected_questions)
                    )
                sha_expected = _compute_sha256(excerpt_path)
                sha_ok = (sha_expected is not None) and (dep.get("excerpt_sha256") == sha_expected)
                if site_ok and lesson_ok and story_ok and outputs_ok and deploy_ok and vocab_ok and counts_ok and sha_ok:
                    dep_fields_ok = True
            except Exception:
                dep_fields_ok = False

        gen = dep.get("generated_files")
        if isinstance(gen, list):
            expected_files = [
                outputs_dir / "vocab_summary.csv",
                outputs_dir / "vocab_instances.json",
                outputs_dir / "questions.json",
                deploy_dir / "index.html",
                deploy_dir / "deployment_report.json",
            ]
            rep_map: Dict[str, int] = {}
            try:
                for item in gen:
                    if isinstance(item, dict) and "path" in item and "size_bytes" in item:
                        p = str(item["path"]).replace("\\", "/")
                        try:
                            sz = int(item["size_bytes"])
                        except Exception:
                            continue
                        rep_map[p] = sz
            except Exception:
                rep_map = {}
            all_present = True
            for f in expected_files:
                if not f.exists():
                    all_present = False
                    break
                rel = _normalize_relpath(f, workspace)
                size_actual = f.stat().st_size
                size_reported = rep_map.get(rel)
                if size_reported != size_actual:
                    all_present = False
                    break
            if all_present:
                dep_genfiles_ok = True

    if dep_fields_ok:
        scores["deployment_report_fields_valid"] = 1.0
    if dep_genfiles_ok:
        scores["deployment_report_generated_files_listed"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()