import json
import csv
import sys
import re
from pathlib import Path
from typing import Dict, List, Tuple, Set, Any
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP


PUNCT_STRIP = " \t\r\n,.!?:;\"'()[]{}<>/\\|-_`~"


def _read_text(path: Path) -> List[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []


def _load_jsonl(path: Path) -> Tuple[bool, List[dict]]:
    data = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        data.append(obj)
                    else:
                        return False, []
                except Exception:
                    return False, []
        return True, data
    except Exception:
        return False, []


def _load_csv_dicts(path: Path) -> Tuple[bool, List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                if not isinstance(row, dict):
                    return False, []
                rows.append({k: (v if v is not None else "") for k, v in row.items()})
        return True, rows
    except Exception:
        return False, []


def _parse_simple_topics_yaml(path: Path) -> Tuple[bool, Dict[str, Set[str]]]:
    """
    Very simple YAML parser for the expected structure:
    canonical:
      topic1:
        - synonym1
        - synonym2
      topic2:
        - synonym
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return False, {}
    in_canonical = False
    current_topic = None
    mapping: Dict[str, Set[str]] = {}
    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            continue
        if not in_canonical:
            if line.strip() == "canonical:":
                in_canonical = True
            continue
        m_topic = re.match(r"^\s{2}([A-Za-z0-9_\-]+):\s*$", line)
        if m_topic:
            current_topic = m_topic.group(1)
            if current_topic not in mapping:
                mapping[current_topic] = set()
            mapping[current_topic].add(current_topic.lower())
            continue
        m_syn = re.match(r"^\s{4}-\s*(.+?)\s*$", line)
        if m_syn and current_topic:
            syn = m_syn.group(1)
            mapping[current_topic].add(syn.lower())
            continue
    if not in_canonical or not mapping:
        return False, {}
    return True, mapping


def _strip_tag_token(s: str) -> str:
    return s.strip(PUNCT_STRIP).lower()


def _build_synonym_to_canonical(topics_map: Dict[str, Set[str]]) -> Dict[str, str]:
    syn_to_canon: Dict[str, str] = {}
    for canon, syns in topics_map.items():
        for syn in syns:
            syn_norm = _strip_tag_token(syn)
            if syn_norm:
                syn_to_canon[syn_norm] = canon
        syn_to_canon[_strip_tag_token(canon)] = canon
    return syn_to_canon


def _canonicalize_tags(raw_tags: List[str], syn_to_canon: Dict[str, str]) -> Set[str]:
    result: Set[str] = set()
    for t in raw_tags:
        t_norm = _strip_tag_token(t)
        if not t_norm:
            continue
        if t_norm in syn_to_canon:
            result.add(syn_to_canon[t_norm])
    return result


def _round_half_up(n: float) -> int:
    d = Decimal(str(n)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(d)


def _scan_items(workspace: Path, syn_to_canon: Dict[str, str]) -> Tuple[bool, List[Dict[str, Any]]]:
    items: List[Dict[str, Any]] = []
    parse_ok = True

    def process_dir(subdir: str, pattern_prefix: str, source_name: str):
        nonlocal parse_ok
        base = workspace / "input" / subdir
        if not base.exists():
            return
        for p in sorted(base.rglob("*.txt")):
            name = p.name
            if not name.startswith(pattern_prefix + "-"):
                continue
            m = re.match(rf"^{re.escape(pattern_prefix)}-(\d{{4}}-\d{{2}}-\d{{2}})-.*\.txt$", name)
            if not m:
                continue
            date_str = m.group(1)
            try:
                datetime.strptime(date_str, "%Y-%m-%d")
            except Exception:
                parse_ok = False
                continue
            lines = _read_text(p)
            if len(lines) < 2:
                parse_ok = False
                continue
            title_line = lines[0]
            tags_line = lines[1]
            if not title_line.startswith("Title:") or not tags_line.startswith("Tags:"):
                parse_ok = False
                continue
            title = title_line[len("Title:"):].strip()
            tags_str = tags_line[len("Tags:"):].strip()
            raw_tags = [t.strip() for t in tags_str.split(",")]
            canon_tags = _canonicalize_tags(raw_tags, syn_to_canon)
            body_lines = lines[2:]
            body_text = "\n".join(body_lines)
            word_count = len(body_text.split())
            items.append({
                "title": title,
                "date": date_str,
                "source": source_name,
                "topics": canon_tags,
                "word_count": word_count,
                "path": str(p),
            })

    process_dir("opeds", "op", "opeds")
    process_dir("monologues", "mono", "monologues")
    return parse_ok, items


def _compute_expected_knowledge(items: List[Dict[str, Any]],
                                topics_map: Dict[str, Set[str]],
                                quotes_by_topic: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Dict[str, int]]:
    expected: Dict[str, Dict[str, int]] = {}
    for topic in sorted(topics_map.keys()):
        topic_items = [it for it in items if topic in it["topics"]]
        item_count = len(topic_items)
        oped_count = sum(1 for it in topic_items if it["source"] == "opeds")
        mono_count = sum(1 for it in topic_items if it["source"] == "monologues")
        quote_count = len(quotes_by_topic.get(topic, []))
        if item_count > 0:
            avg = sum(it["word_count"] for it in topic_items) / item_count
            avg_rounded = _round_half_up(avg)
        else:
            avg_rounded = 0
        expected[topic] = {
            "item_count": item_count,
            "oped_count": oped_count,
            "monologue_count": mono_count,
            "quote_count": quote_count,
            "avg_body_word_count": avg_rounded,
        }
    return expected


def _compute_expected_source_overview(items: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    res = {}
    for source in ["opeds", "monologues"]:
        src_items = [it for it in items if it["source"] == source]
        res[source] = {
            "item_count": len(src_items),
            "total_words": sum(it["word_count"] for it in src_items),
        }
    return res


def _load_quotes_by_topic(workspace: Path, syn_to_canon: Dict[str, str]) -> Tuple[bool, Dict[str, List[Dict[str, Any]]]]:
    ok, data = _load_jsonl(workspace / "input" / "quotes.jsonl")
    if not ok:
        return False, {}
    by_topic: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for obj in data:
        quote = obj.get("quote")
        author = obj.get("author")
        tags = obj.get("tags")
        if not isinstance(quote, str) or not isinstance(author, str) or not isinstance(tags, list):
            return False, {}
        canon_tags = _canonicalize_tags([str(t) for t in tags], syn_to_canon)
        for t in canon_tags:
            by_topic[t].append({"quote": quote, "author": author})
    return True, by_topic


def _load_pun_seeds(workspace: Path) -> Tuple[bool, Dict[str, str]]:
    ok, rows = _load_csv_dicts(workspace / "input" / "pun_seeds.csv")
    if not ok:
        return False, {}
    seeds = {}
    for row in rows:
        topic = (row.get("topic") or "").strip()
        seed = (row.get("pun_seed") or "").strip()
        if not topic:
            return False, {}
        seeds[topic] = seed
    return True, seeds


def _parse_csv_file(path: Path) -> Tuple[bool, List[str], List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return False, [], []
            rows = []
            for row in reader:
                rows.append({k: (v if v is not None else "") for k, v in row.items()})
            return True, headers, rows
    except Exception:
        return False, [], []


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "knowledge_summary_exists": 0.0,
        "knowledge_summary_headers": 0.0,
        "knowledge_summary_rows_correct": 0.0,
        "source_overview_exists": 0.0,
        "source_overview_headers": 0.0,
        "source_overview_rows_correct": 0.0,
        "meeting_notes_exists": 0.0,
        "meeting_notes_sections_present": 0.0,
        "agenda_representative_items_present": 0.0,
        "action_items_review_pun_present": 0.0,
        "action_items_quote_present": 0.0,
    }

    topics_ok, topics_map = _parse_simple_topics_yaml(workspace / "input" / "topics.yaml")
    syn_to_canon = _build_synonym_to_canonical(topics_map) if topics_ok else {}

    items_ok, items = _scan_items(workspace, syn_to_canon) if topics_ok else (False, [])

    quotes_ok, quotes_by_topic = _load_quotes_by_topic(workspace, syn_to_canon) if topics_ok else (False, {})

    pun_ok, pun_seeds = _load_pun_seeds(workspace)

    if topics_ok and items_ok and quotes_ok:
        expected_knowledge = _compute_expected_knowledge(items, topics_map, quotes_by_topic)
    else:
        expected_knowledge = {}

    if items_ok:
        expected_source = _compute_expected_source_overview(items)
    else:
        expected_source = {}

    ks_path = workspace / "outputs" / "knowledge_summary.csv"
    if ks_path.exists():
        scores["knowledge_summary_exists"] = 1.0
        ok, headers, rows = _parse_csv_file(ks_path)
        if ok and headers == ["topic", "item_count", "oped_count", "monologue_count", "quote_count", "avg_body_word_count"]:
            scores["knowledge_summary_headers"] = 1.0
            if expected_knowledge:
                actual_map: Dict[str, Dict[str, int]] = {}
                try:
                    for r in rows:
                        topic = (r.get("topic") or "").strip()
                        if not topic:
                            raise ValueError("missing topic")
                        vals = {
                            "item_count": int((r.get("item_count") or "").strip()),
                            "oped_count": int((r.get("oped_count") or "").strip()),
                            "monologue_count": int((r.get("monologue_count") or "").strip()),
                            "quote_count": int((r.get("quote_count") or "").strip()),
                            "avg_body_word_count": int((r.get("avg_body_word_count") or "").strip()),
                        }
                        actual_map[topic] = vals
                    if set(actual_map.keys()) == set(expected_knowledge.keys()):
                        all_match = True
                        for t in expected_knowledge:
                            if actual_map.get(t) != expected_knowledge.get(t):
                                all_match = False
                                break
                        if all_match:
                            scores["knowledge_summary_rows_correct"] = 1.0
                    else:
                        scores["knowledge_summary_rows_correct"] = 0.0
                except Exception:
                    scores["knowledge_summary_rows_correct"] = 0.0
            else:
                scores["knowledge_summary_rows_correct"] = 0.0
        else:
            scores["knowledge_summary_headers"] = 0.0
            scores["knowledge_summary_rows_correct"] = 0.0

    so_path = workspace / "outputs" / "source_overview.csv"
    if so_path.exists():
        scores["source_overview_exists"] = 1.0
        ok, headers, rows = _parse_csv_file(so_path)
        if ok and headers == ["source", "item_count", "total_words"]:
            scores["source_overview_headers"] = 1.0
            if expected_source:
                try:
                    actual_map: Dict[str, Dict[str, int]] = {}
                    for r in rows:
                        source = (r.get("source") or "").strip()
                        if not source:
                            raise ValueError("missing source")
                        vals = {
                            "item_count": int((r.get("item_count") or "").strip()),
                            "total_words": int((r.get("total_words") or "").strip()),
                        }
                        actual_map[source] = vals
                    if set(actual_map.keys()) == {"opeds", "monologues"}:
                        all_match = True
                        for s in ["opeds", "monologues"]:
                            if actual_map.get(s) != expected_source.get(s):
                                all_match = False
                                break
                        if all_match:
                            scores["source_overview_rows_correct"] = 1.0
                    else:
                        scores["source_overview_rows_correct"] = 0.0
                except Exception:
                    scores["source_overview_rows_correct"] = 0.0
            else:
                scores["source_overview_rows_correct"] = 0.0
        else:
            scores["source_overview_headers"] = 0.0
            scores["source_overview_rows_correct"] = 0.0

    mn_path = workspace / "outputs" / "meeting_notes.md"
    if mn_path.exists():
        scores["meeting_notes_exists"] = 1.0
        try:
            mn_text = mn_path.read_text(encoding="utf-8")
        except Exception:
            mn_text = ""
        if ("A. Agenda" in mn_text) and ("B. Action Items" in mn_text):
            scores["meeting_notes_sections_present"] = 1.0
        else:
            scores["meeting_notes_sections_present"] = 0.0

        if expected_knowledge and items_ok and topics_ok and quotes_ok:
            sorted_topics = sorted(
                expected_knowledge.items(),
                key=lambda kv: (-kv[1]["item_count"], kv[0])
            )
            top3 = [t for t, _ in sorted_topics[:3]]
            expected_item_lines: List[str] = []
            items_by_topic: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
            for it in items:
                for t in it["topics"]:
                    items_by_topic[t].append(it)
            for t in top3:
                topic_items = items_by_topic.get(t, [])
                topic_items_sorted = sorted(
                    topic_items,
                    key=lambda it: (it["date"], it["title"]),
                    reverse=True
                )
                for it in topic_items_sorted[:2]:
                    expected_item_lines.append(f"[{it['date']}] {it['source']} - {it['title']}")
            if expected_item_lines:
                present = 0
                for line in expected_item_lines:
                    if line in mn_text:
                        present += 1
                scores["agenda_representative_items_present"] = present / float(len(expected_item_lines))
            else:
                scores["agenda_representative_items_present"] = 1.0

            total_review_pun = 0
            found_review_pun = 0
            for t in top3:
                icount = expected_knowledge[t]["item_count"]
                review_line = f"Review {t} files: {icount} files"
                total_review_pun += 1
                if review_line in mn_text:
                    found_review_pun += 1
                seed_val = (pun_seeds.get(t) if pun_ok else None)
                pun_text = seed_val if seed_val else "N/A"
                pun_line = f"Pick pun seed: {pun_text}"
                total_review_pun += 1
                if pun_line in mn_text:
                    found_review_pun += 1
            if total_review_pun > 0:
                scores["action_items_review_pun_present"] = found_review_pun / float(total_review_pun)
            else:
                scores["action_items_review_pun_present"] = 0.0

            total_quotes = 0
            found_quotes = 0
            for t in top3:
                qlist = quotes_by_topic.get(t, [])
                if not qlist:
                    expected_author = "N/A"
                    expected_quote = "N/A"
                else:
                    sorted_q = sorted(qlist, key=lambda q: (len(q["quote"]), q["quote"], q["author"]))
                    chosen = sorted_q[0]
                    expected_author = chosen["author"]
                    qtext = chosen["quote"]
                    if len(qtext) > 80:
                        qtext = qtext[:80]
                    expected_quote = qtext
                quote_line = f'Select quote: {expected_author} — "{expected_quote}"'
                total_quotes += 1
                if quote_line in mn_text:
                    found_quotes += 1
            if total_quotes > 0:
                scores["action_items_quote_present"] = found_quotes / float(total_quotes)
            else:
                scores["action_items_quote_present"] = 0.0
        else:
            scores["agenda_representative_items_present"] = 0.0
            scores["action_items_review_pun_present"] = 0.0
            scores["action_items_quote_present"] = 0.0

    for k, v in list(scores.items()):
        try:
            val = float(v)
        except Exception:
            val = 0.0
        if val < 0.0:
            val = 0.0
        if val > 1.0:
            val = 1.0
        scores[k] = val

    return scores


def main() -> None:
    workspace_path = "."
    if len(sys.argv) >= 2:
        workspace_path = sys.argv[1]
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()