import json
import csv
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_jsonl(path: Path) -> Optional[List[dict]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None
    records = []
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                records.append(obj)
            else:
                # Only dict objects are valid
                return None
        except Exception:
            return None
    return records


def _parse_comments_csv(path: Path) -> Optional[List[dict]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            required = {"id", "timestamp", "source", "text"}
            if set(reader.fieldnames or []) != required:
                # Require exact column set and order not mandated, but enforce exact fields
                if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
                    return None
            rows = []
            for row in reader:
                # Validate required fields presence per row
                if not all(k in row for k in required):
                    return None
                rows.append({
                    "id": str(row.get("id", "")).strip(),
                    "timestamp": row.get("timestamp", ""),
                    "source": row.get("source", ""),
                    "text": row.get("text", ""),
                })
            return rows
    except Exception:
        return None


def _parse_polls_md(path: Path) -> Optional[Tuple[Dict[str, int], int]]:
    text = _read_text(path)
    if text is None:
        return None
    # Lines format: "- Label: Count"
    label_map = {
        "quiet luxury": "quiet luxury",
        "dark academia": "dark academia",
        "liminal spaces": "liminal spaces",
        "ai co-authorship": "AI co-authors",
        "typewriters": "typewriter(s)",
        "hidden identity/pseudonym": "pseudonym(s)",
    }
    counts: Dict[str, int] = {k: 0 for k in [
        "quiet luxury", "dark academia", "liminal spaces", "AI co-authors", "typewriter(s)", "pseudonym(s)"
    ]}
    mapped_lines = 0
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("-"):
            continue
        # Remove leading dash and spaces
        entry = line[1:].strip()
        # Expect "Label: Count"
        if ":" not in entry:
            continue
        label, cnt = entry.split(":", 1)
        label = label.strip().lower()
        cnt_str = cnt.strip()
        try:
            val = int(cnt_str)
        except ValueError:
            continue
        if label in label_map:
            canonical = label_map[label]
            counts[canonical] += val
            mapped_lines += 1
    return counts, mapped_lines


def _alias_patterns() -> Dict[str, List[re.Pattern]]:
    # Build case-insensitive regex patterns for each canonical phrase
    patterns: Dict[str, List[re.Pattern]] = {}
    patterns["quiet luxury"] = [re.compile(r"\bquiet luxury\b", re.IGNORECASE)]
    patterns["dark academia"] = [re.compile(r"\bdark academia\b", re.IGNORECASE)]
    # liminal spaces also counts "liminal space"
    patterns["liminal spaces"] = [re.compile(r"\bliminal space(s)?\b", re.IGNORECASE)]
    # AI co-authors variants:
    patterns["AI co-authors"] = [
        re.compile(r"\bai co[- ]?author(s)?\b", re.IGNORECASE),
        re.compile(r"\bai co[- ]?authorship\b", re.IGNORECASE),
    ]
    # typewriter(s)
    patterns["typewriter(s)"] = [re.compile(r"\btypewriter(s)?\b", re.IGNORECASE)]
    # pseudonym(s)
    patterns["pseudonym(s)"] = [re.compile(r"\bpseudonym(s)?\b", re.IGNORECASE)]
    return patterns


def _count_occurrences(text: str, phrase: str, pats: Dict[str, List[re.Pattern]]) -> int:
    total = 0
    for rx in pats.get(phrase, []):
        total += len(rx.findall(text))
    return total


def _compute_expected(workspace: Path) -> dict:
    # Discover inputs
    inbox = workspace / "input" / "inbox"
    notes = workspace / "input" / "notes"
    comments_files = sorted(inbox.glob("comments_*.csv"))
    replies_file = inbox / "newsletter_replies.jsonl"
    polls_file = notes / "reader_polls.md"

    pats = _alias_patterns()
    phrases = ["quiet luxury", "dark academia", "liminal spaces", "AI co-authors", "typewriter(s)", "pseudonym(s)"]

    # Sources list expected
    sources_expected = []
    comments_records_all: List[dict] = []
    # For verifying snippets: maps
    comments_by_id: Dict[str, str] = {}
    replies_by_email: Dict[str, str] = {}

    # Comments CSVs
    for cfile in comments_files:
        rows = _parse_comments_csv(cfile)
        if rows is None:
            # Treat malformed file as zero records for counting; but still include in sources if exists?
            # We'll include it with records_count 0, and it will cause further checks to fail as appropriate.
            rc = 0
            rows = []
        else:
            rc = len(rows)
            comments_records_all.extend(rows)
            for r in rows:
                comments_by_id[str(r["id"])] = r["text"]
        sources_expected.append({
            "path": str(cfile.as_posix()),
            "type": "comments_csv",
            "records_count": rc,
        })

    # Replies JSONL
    replies_records: List[dict] = []
    if replies_file.exists():
        recs = _parse_jsonl(replies_file)
        if recs is None:
            rc = 0
            recs = []
        else:
            rc = len(recs)
            for r in recs:
                email = str(r.get("email", "")).strip()
                body = str(r.get("body", ""))
                replies_by_email[email] = body
            replies_records = recs
        sources_expected.append({
            "path": str(replies_file.as_posix()),
            "type": "replies_jsonl",
            "records_count": rc,
        })

    # Polls MD
    polls_counts: Dict[str, int] = {k: 0 for k in phrases}
    if polls_file.exists():
        parsed = _parse_polls_md(polls_file)
        if parsed is None:
            mapped_lines = 0
        else:
            polls_counts, mapped_lines = parsed
        sources_expected.append({
            "path": str(polls_file.as_posix()),
            "type": "polls_md",
            "records_count": mapped_lines,
        })

    # Compute counts by source
    by_source_counts: Dict[str, Dict[str, int]] = {p: {"comments": 0, "replies": 0, "polls": 0} for p in phrases}

    # Comments counts and snippet candidates
    comments_hits: Dict[str, List[str]] = {p: [] for p in phrases}  # phrase -> list of comment ids with hits
    for r in comments_records_all:
        text = str(r["text"])
        cid = str(r["id"])
        for p in phrases:
            cnt = _count_occurrences(text, p, pats)
            if cnt > 0:
                by_source_counts[p]["comments"] += cnt
                comments_hits[p].append(cid)

    # Replies counts and snippet candidates
    replies_hits: Dict[str, List[str]] = {p: [] for p in phrases}  # phrase -> list of emails with hits
    for r in replies_records:
        body = str(r.get("body", ""))
        email = str(r.get("email", "")).strip()
        for p in phrases:
            cnt = _count_occurrences(body, p, pats)
            if cnt > 0:
                by_source_counts[p]["replies"] += cnt
                replies_hits[p].append(email)

    # Polls counts added
    for p in phrases:
        by_source_counts[p]["polls"] += int(polls_counts.get(p, 0))

    # Totals and top order
    totals: Dict[str, int] = {p: by_source_counts[p]["comments"] + by_source_counts[p]["replies"] + by_source_counts[p]["polls"] for p in phrases}
    top_sorted = sorted(phrases, key=lambda x: (-totals[x], x))

    return {
        "phrases": phrases,
        "patterns": pats,
        "sources_expected": sources_expected,
        "by_source_counts": by_source_counts,
        "totals": totals,
        "top_sorted": top_sorted,
        "comments_by_id": comments_by_id,
        "replies_by_email": replies_by_email,
    }


def _load_weekly_trends(path: Path) -> Optional[dict]:
    data = _load_json(path)
    if not isinstance(data, dict):
        return None
    return data


def _normalize_phrase_stats(ps: object) -> Optional[Dict[str, dict]]:
    # Accept list of objects with 'phrase' field or dict mapping
    if isinstance(ps, dict):
        # Values should be dicts and keys phrases
        out: Dict[str, dict] = {}
        for k, v in ps.items():
            if isinstance(v, dict):
                # Inject phrase field if missing
                if "phrase" not in v:
                    v = dict(v)
                    v["phrase"] = k
                out[k] = v
            else:
                return None
        return out
    elif isinstance(ps, list):
        out = {}
        for item in ps:
            if not isinstance(item, dict) or "phrase" not in item:
                return None
            out[str(item["phrase"])] = item
        return out
    else:
        return None


def _validate_sources_list(produced: List[dict], expected: List[dict]) -> float:
    # Compare ignoring order; require exact same set of (path, type, records_count)
    def keyify(lst: List[dict]) -> set:
        s = set()
        for x in lst:
            path = x.get("path")
            typ = x.get("type")
            rc = x.get("records_count")
            if isinstance(path, str) and isinstance(typ, str) and isinstance(rc, int):
                s.add((path, typ, rc))
        return s

    prod_set = keyify(produced or [])
    exp_set = keyify(expected or [])
    if not exp_set:
        # If there are no expected sources (no inputs present), then require that produced is an empty set.
        return 1.0 if not prod_set else 0.0
    return 1.0 if prod_set == exp_set else 0.0


def _validate_phrase_counts(phrase_stats_map: Dict[str, dict], expected_counts: Dict[str, Dict[str, int]]) -> float:
    # Return fraction of phrases that exactly match counts and totals
    phrases = list(expected_counts.keys())
    correct = 0
    for p in phrases:
        obj = phrase_stats_map.get(p)
        if not isinstance(obj, dict):
            continue
        by_source = obj.get("by_source")
        total = obj.get("total_occurrences")
        if not isinstance(by_source, dict) or not isinstance(total, int):
            continue
        try:
            c = int(by_source.get("comments", None))
            r = int(by_source.get("replies", None))
            po = int(by_source.get("polls", None))
        except Exception:
            continue
        exp_c = expected_counts[p]["comments"]
        exp_r = expected_counts[p]["replies"]
        exp_po = expected_counts[p]["polls"]
        exp_total = exp_c + exp_r + exp_po
        if c == exp_c and r == exp_r and po == exp_po and total == exp_total:
            correct += 1
    return correct / max(1, len(phrases))


def _validate_snippets(phrase_stats_map: Dict[str, dict],
                       pats: Dict[str, List[re.Pattern]],
                       comments_by_id: Dict[str, str],
                       replies_by_email: Dict[str, str]) -> float:
    # For each phrase, validate snippet schema, limits, and textual grounding.
    phrases = list(phrase_stats_map.keys())
    if not phrases:
        return 0.0
    ok_count = 0
    for p, obj in phrase_stats_map.items():
        if not isinstance(obj, dict):
            continue
        snippets = obj.get("example_snippets", [])
        if snippets is None:
            snippets = []
        if not isinstance(snippets, list):
            continue
        # Enforce limits: up to 2 from comments and up to 2 from replies
        comm_ct = sum(1 for s in snippets if isinstance(s, dict) and s.get("source_type") == "comment")
        repl_ct = sum(1 for s in snippets if isinstance(s, dict) and s.get("source_type") == "reply")
        if comm_ct > 2 or repl_ct > 2:
            continue
        # Validate each snippet refers to a real source and excerpt matches
        valid_all = True
        for s in snippets:
            if not isinstance(s, dict):
                valid_all = False
                break
            st = s.get("source_type")
            excerpt = s.get("text_excerpt")
            if st not in ("comment", "reply") or not isinstance(excerpt, str) or not excerpt:
                valid_all = False
                break
            excerpt_low = excerpt.lower()
            # Require that excerpt contains a matched alias for phrase p
            alias_match = any(rx.search(excerpt) for rx in pats.get(p, []))
            if not alias_match:
                valid_all = False
                break
            if st == "comment":
                sid = s.get("source_id")
                if sid is None:
                    valid_all = False
                    break
                sid_str = str(sid)
                orig = comments_by_id.get(sid_str)
                if orig is None or excerpt_low not in orig.lower():
                    valid_all = False
                    break
            elif st == "reply":
                email = s.get("email")
                if email is None:
                    valid_all = False
                    break
                email_str = str(email).strip()
                orig = replies_by_email.get(email_str)
                if orig is None or excerpt_low not in orig.lower():
                    valid_all = False
                    break
        if valid_all:
            ok_count += 1
    return ok_count / max(1, len(phrases))


def _validate_top_sorted(produced: List[str], expected: List[str]) -> float:
    if not isinstance(produced, list):
        return 0.0
    produced_norm = [str(x) for x in produced]
    return 1.0 if produced_norm == expected else 0.0


def _extract_paragraphs_and_bullets(lines: List[str]) -> Tuple[List[str], List[str], Optional[str]]:
    # Returns paragraphs (joined per paragraph), bullets, subject_line
    subject_line = None
    # Find first non-empty line and treat as Subject
    for i, line in enumerate(lines):
        if line.strip():
            subject_line = line.strip()
            start_idx = i + 1
            break
    else:
        return [], [], None
    # Collect paragraphs until a bullet list begins
    paragraphs: List[str] = []
    current_para: List[str] = []
    bullets: List[str] = []
    bullet_started = False
    for line in lines[start_idx:]:
        if line.strip().startswith(("- ", "* ")):
            bullet_started = True
            bullets.append(line.strip())
            continue
        if bullet_started:
            # after bullets start, keep collecting bullets only if the line is another bullet
            if line.strip().startswith(("- ", "* ")):
                bullets.append(line.strip())
            else:
                # ignore non-bullet content after bullet list for grading simplicity
                pass
        else:
            # paragraph building
            if line.strip() == "":
                if current_para:
                    paragraphs.append(" ".join([x.strip() for x in current_para if x.strip()]))
                    current_para = []
            else:
                current_para.append(line)
    if current_para:
        paragraphs.append(" ".join([x.strip() for x in current_para if x.strip()]))
    return paragraphs, bullets, subject_line


def _editor_pitch_checks(text: str, top3: List[str], totals: Dict[str, int]) -> Dict[str, float]:
    lines = text.splitlines()
    paragraphs, bullets, subject = _extract_paragraphs_and_bullets(lines)

    # Subject must mention top 3 phrases (case-insensitive)
    subj_ok = 0.0
    if subject is not None and subject.lower().startswith("subject:"):
        subj_low = subject.lower()
        if all(p.lower() in subj_low for p in top3):
            subj_ok = 1.0

    # 1-2 paragraphs and mentions ancestral/"mysterious author" muse idea
    paras_ok = 0.0
    if 1 <= len(paragraphs) <= 2:
        joined = " ".join(paragraphs).lower()
        if ("ancestral" in joined) or ("mysterious author" in joined):
            paras_ok = 1.0

    # Bullets: at least 3; must summarize top 3 with counts and source type mention
    bullets_ok = 0.0
    if len(bullets) >= 3:
        phrase_hit = 0
        for p in top3:
            expected_count = str(totals.get(p, 0))
            found_line = None
            for b in bullets:
                b_low = b.lower()
                if p.lower() in b_low and expected_count in b and (("comment" in b_low) or ("reply" in b_low)):
                    found_line = b
                    break
            if found_line:
                phrase_hit += 1
        if phrase_hit == 3:
            bullets_ok = 1.0

    return {
        "editor_pitch_subject_mentions_top3": subj_ok,
        "editor_pitch_paragraphs_and_muse_reference": paras_ok,
        "editor_pitch_bullets_top3_with_counts_and_source": bullets_ok,
    }


def _subscriber_note_checks(text: str, top2: List[str]) -> Dict[str, float]:
    low = text.lower()
    # Warm opening referencing the ancestral muse idea
    muse_ok = 1.0 if ("ancestral" in low or "mysterious author" in low or "muse" in low) else 0.0
    # Summary of top 2 phrases
    top2_ok = 1.0 if all(p.lower() in low for p in top2) else 0.0
    # Call to action inviting replies on which theme readers want next week
    cta_ok = 1.0 if (("reply" in low or "replies" in low) and ("next week" in low) and ("theme" in low)) else 0.0
    return {
        "subscriber_note_muse_reference_and_top2": (muse_ok + top2_ok) / 2.0,
        "subscriber_note_call_to_action": cta_ok,
    }


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "weekly_trends_exists_and_parseable": 0.0,
        "sources_list_correct": 0.0,
        "phrase_counts_correct": 0.0,
        "snippets_valid_and_limited": 0.0,
        "top_phrases_sorted_correct": 0.0,
        "editor_pitch_subject_mentions_top3": 0.0,
        "editor_pitch_paragraphs_and_muse_reference": 0.0,
        "editor_pitch_bullets_top3_with_counts_and_source": 0.0,
        "subscriber_note_muse_reference_and_top2": 0.0,
        "subscriber_note_call_to_action": 0.0,
    }

    expected = _compute_expected(workspace)
    weekly_path = workspace / "output" / "trends" / "weekly_trends.json"
    editor_path = workspace / "output" / "drafts" / "editor_pitch.txt"
    subscriber_path = workspace / "output" / "drafts" / "subscriber_note.txt"

    weekly = _load_weekly_trends(weekly_path)
    if weekly is None:
        return scores
    scores["weekly_trends_exists_and_parseable"] = 1.0

    # Validate sources
    produced_sources = weekly.get("sources")
    if isinstance(produced_sources, list):
        scores["sources_list_correct"] = _validate_sources_list(produced_sources, expected["sources_expected"])
    else:
        scores["sources_list_correct"] = 0.0

    # Validate phrase_stats
    phrase_stats = weekly.get("phrase_stats")
    ps_map = _normalize_phrase_stats(phrase_stats)
    if ps_map is None:
        scores["phrase_counts_correct"] = 0.0
        scores["snippets_valid_and_limited"] = 0.0
    else:
        scores["phrase_counts_correct"] = _validate_phrase_counts(ps_map, expected["by_source_counts"])
        scores["snippets_valid_and_limited"] = _validate_snippets(
            ps_map, expected["patterns"], expected["comments_by_id"], expected["replies_by_email"]
        )

    # Validate top_phrases_by_total
    top_prod = weekly.get("top_phrases_by_total")
    scores["top_phrases_sorted_correct"] = _validate_top_sorted(top_prod, expected["top_sorted"])

    # Load editor pitch
    editor_text = _read_text(editor_path) or ""
    editor_checks = _editor_pitch_checks(editor_text, expected["top_sorted"][:3], expected["totals"])
    scores.update(editor_checks)

    # Load subscriber note
    subscriber_text = _read_text(subscriber_path) or ""
    sub_checks = _subscriber_note_checks(subscriber_text, expected["top_sorted"][:2])
    scores.update(sub_checks)

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()