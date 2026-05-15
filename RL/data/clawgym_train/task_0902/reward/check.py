import json
import csv
import re
import sys
import ast
from pathlib import Path
from html.parser import HTMLParser
from typing import List, Dict, Optional, Tuple, Any


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_load_json(path: Path) -> Optional[Any]:
    try:
        txt = read_text(path)
        if txt is None:
            return None
        return json.loads(txt)
    except Exception:
        return None


def safe_read_jsonl(path: Path) -> Optional[List[dict]]:
    try:
        lines = []
        with path.open("r", encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    obj = json.loads(ln)
                except Exception:
                    return None
                if not isinstance(obj, dict):
                    return None
                lines.append(obj)
        return lines
    except Exception:
        return None


def safe_read_csv(path: Path) -> Optional[Tuple[List[str], List[List[str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
            if not rows:
                return None
            header = rows[0]
            data = rows[1:]
            return header, data
    except Exception:
        return None


def parse_topics_yaml(path: Path) -> Optional[dict]:
    text = read_text(path)
    if text is None:
        return None

    lines = text.splitlines()
    state = None  # 'topics', 'rules', 'thresholds'
    topics_order: List[Tuple[str, List[str]]] = []
    rules: Dict[str, Any] = {}
    thresholds: Dict[str, Any] = {}
    current_topic = None

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            continue
        if re.match(r'^\s*#', line):
            continue
        if re.match(r'^topics:\s*$', line):
            state = 'topics'
            current_topic = None
            continue
        if re.match(r'^rules:\s*$', line):
            state = 'rules'
            current_topic = None
            continue
        if re.match(r'^trend_thresholds:\s*$', line):
            state = 'thresholds'
            current_topic = None
            continue

        if state == 'topics':
            m_topic = re.match(r'^\s{2}([a-zA-Z0-9_]+):\s*$', line)
            if m_topic:
                current_topic = m_topic.group(1)
                topics_order.append((current_topic, []))
                continue
            m_kw = re.match(r'^\s{4}keywords:\s*(\[.*\])\s*$', line)
            if m_kw and current_topic is not None:
                list_text = m_kw.group(1)
                try:
                    keywords = ast.literal_eval(list_text)
                    if isinstance(keywords, list):
                        keywords = [str(k) for k in keywords]
                        topics_order[-1] = (current_topic, keywords)
                    else:
                        return None
                except Exception:
                    return None
                continue
            continue

        if state == 'rules':
            m_scope = re.match(r'^\s{2}match_scope:\s*"?([^"]+)"?\s*$', line)
            if m_scope:
                rules['match_scope'] = m_scope.group(1).strip()
                continue
            m_case = re.match(r'^\s{2}case_insensitive:\s*(true|false)\s*$', line, flags=re.IGNORECASE)
            if m_case:
                rules['case_insensitive'] = m_case.group(1).lower() == 'true'
                continue
            continue

        if state == 'thresholds':
            m_min_mentions = re.match(r'^\s{2}min_monthly_mentions:\s*([0-9]+)\s*$', line)
            if m_min_mentions:
                thresholds['min_monthly_mentions'] = int(m_min_mentions.group(1))
                continue
            m_min_growth = re.match(r'^\s{2}min_growth_pct:\s*([0-9]+)\s*$', line)
            if m_min_growth:
                thresholds['min_growth_pct'] = int(m_min_growth.group(1))
                continue
            continue

    if not topics_order or 'match_scope' not in rules or 'case_insensitive' not in rules or 'min_monthly_mentions' not in thresholds or 'min_growth_pct' not in thresholds:
        return None

    return {
        'topics': topics_order,
        'rules': rules,
        'trend_thresholds': thresholds,
    }


class ArticleHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_article = False
        self.in_title = False
        self.in_tags = False
        self.current = {}
        self.articles: List[dict] = []
        self._title_accum: List[str] = []
        self._tags_accum: List[str] = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == 'article':
            self.in_article = True
            self.current = {'title': '', 'date': '', 'tags': ''}
            self._title_accum = []
            self._tags_accum = []
        if not self.in_article:
            return
        if tag == 'h2' and attrs_dict.get('class') == 'title':
            self.in_title = True
        elif tag == 'time':
            dt = attrs_dict.get('datetime')
            if isinstance(dt, str):
                self.current['date'] = dt.strip()
        elif tag == 'span' and attrs_dict.get('class') == 'tags':
            self.in_tags = True

    def handle_endtag(self, tag):
        if tag == 'article' and self.in_article:
            self.current['title'] = ''.join(self._title_accum).strip()
            self.current['tags'] = ''.join(self._tags_accum).strip()
            self.articles.append(self.current)
            self.in_article = False
            self.in_title = False
            self.in_tags = False
            self.current = {}
            self._title_accum = []
            self._tags_accum = []
        elif tag == 'h2' and self.in_title:
            self.in_title = False
        elif tag == 'span' and self.in_tags:
            self.in_tags = False

    def handle_data(self, data):
        if not self.in_article:
            return
        if self.in_title:
            self._title_accum.append(data)
        if self.in_tags:
            self._tags_accum.append(data)


def parse_html_file(path: Path) -> List[dict]:
    parser = ArticleHTMLParser()
    text = read_text(path)
    if text is None:
        return []
    parser.feed(text)
    results = []
    for art in parser.articles:
        date = art.get('date', '').strip()
        title = art.get('title', '').strip()
        tags_text = art.get('tags', '')
        tags = []
        if tags_text:
            parts = [p.strip() for p in tags_text.split(',')]
            tags = [p.lower() for p in parts if p]
        results.append({
            'date': date,
            'title': title,
            'tags': tags,
            'source_file': str(path.as_posix()),
            'month': date[:7] if re.match(r'^\d{4}-\d{2}-\d{2}$', date) else ''
        })
    return results


def compute_topic_for_article(article: dict, topics_order: List[Tuple[str, List[str]]], rules: dict) -> Optional[str]:
    title = article.get('title') or ''
    tags_list = article.get('tags') or []
    case_insensitive = bool(rules.get('case_insensitive', False))
    scope = rules.get('match_scope', 'title_or_tags')
    title_cmp = title
    tags_cmp = tags_list[:]
    if case_insensitive:
        title_cmp = title.lower()
        tags_cmp = [t.lower() for t in tags_list]
    for topic, keywords in topics_order:
        for kw in keywords:
            kw_cmp = kw.lower() if case_insensitive else kw
            in_title = kw_cmp in title_cmp
            in_tags = any(kw_cmp in t for t in tags_cmp)
            if scope == 'title_or_tags':
                if in_title or in_tags:
                    return topic
            elif scope == 'title':
                if in_title:
                    return topic
            elif scope == 'tags':
                if in_tags:
                    return topic
    return None


def group_counts(records: List[dict]) -> Dict[Tuple[str, str], int]:
    counts: Dict[Tuple[str, str], int] = {}
    for rec in records:
        topic = rec.get('topic')
        month = rec.get('month')
        if not topic or not month:
            continue
        key = (month, topic)
        counts[key] = counts.get(key, 0) + 1
    return counts


def group_counts_from_articles(articles: List[dict], topics_order: List[Tuple[str, List[str]]], rules: dict) -> Dict[Tuple[str, str], int]:
    counts: Dict[Tuple[str, str], int] = {}
    for art in articles:
        topic = compute_topic_for_article(art, topics_order, rules)
        month = art.get('month', '')
        if not topic or not month:
            continue
        key = (month, topic)
        counts[key] = counts.get(key, 0) + 1
    return counts


def month_prev(month: str) -> Optional[str]:
    m = re.match(r'^(\d{4})-(\d{2})$', month)
    if not m:
        return None
    y = int(m.group(1))
    mo = int(m.group(2))
    mo_prev = mo - 1
    y_prev = y
    if mo_prev == 0:
        y_prev = y - 1
        mo_prev = 12
    return f"{y_prev:04d}-{mo_prev:02d}"


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "debug_extracted_present_and_valid_json": 0.0,
        "extractor_schema_and_fields_valid": 0.0,
        "extracted_records_match_html": 0.0,
        "topic_assignment_correct": 0.0,
        "monthly_counts_csv_present_and_parsable": 0.0,
        "monthly_counts_match_expected_html": 0.0,
        "cross_validation_counts_consistent": 0.0,
        "trending_report_present_and_parsable": 0.0,
        "trending_report_values_correct": 0.0,
    }

    config_path = workspace / "config" / "topics.yml"
    cfg = parse_topics_yaml(config_path)
    if not cfg:
        topics_order = []
        rules = {}
        thresholds = {}
    else:
        topics_order = cfg['topics']
        rules = cfg['rules']
        thresholds = cfg['trend_thresholds']

    data_dir = workspace / "data"
    html_files = sorted([p for p in data_dir.glob("*.html") if p.is_file()])
    expected_articles: List[dict] = []
    for hf in html_files:
        articles = parse_html_file(hf)
        for art in articles:
            # Normalize to relative path as specified: data/...
            try:
                rel = hf.relative_to(workspace).as_posix()
            except Exception:
                # Fallback: best-effort relative path
                rel = ("data/" + hf.name)
            art['source_file'] = rel
        expected_articles.extend(articles)

    expected_count = len(expected_articles)

    debug_path = workspace / "output" / "debug_extracted.jsonl"
    debug_records = safe_read_jsonl(debug_path)
    if debug_records is not None:
        scores["debug_extracted_present_and_valid_json"] = 1.0

    schema_ok = False
    if debug_records is not None and expected_count > 0:
        required_fields = {"id", "date", "month", "title", "tags", "source_file", "topic"}
        field_types_ok = True
        ids = set()
        tags_ok = True
        date_month_ok = True
        source_file_ok = True
        expected_keyset = set(
            (str(a['source_file']), a['title'].strip(), a['date'])
            for a in expected_articles
        )
        for rec in debug_records:
            if not isinstance(rec, dict):
                field_types_ok = False
                break
            if not required_fields.issubset(set(rec.keys())):
                field_types_ok = False
                break
            if not isinstance(rec.get('id'), str) or not rec.get('id'):
                field_types_ok = False
                break
            ids.add(rec['id'])
            if not isinstance(rec.get('date'), str) or not re.match(r'^\d{4}-\d{2}-\d{2}$', rec.get('date')):
                date_month_ok = False
            if not isinstance(rec.get('month'), str) or not re.match(r'^\d{4}-\d{2}$', rec.get('month')):
                date_month_ok = False
            else:
                if not rec['date'].startswith(rec['month']):
                    date_month_ok = False
            if not isinstance(rec.get('title'), str):
                field_types_ok = False
                break
            tags = rec.get('tags')
            if not isinstance(tags, list):
                tags_ok = False
            else:
                for t in tags:
                    if not isinstance(t, str):
                        tags_ok = False
                        break
                    if t != t.lower():
                        tags_ok = False
                        break
                    if t.strip() != t:
                        tags_ok = False
                        break
            sf = rec.get('source_file')
            if not isinstance(sf, str):
                source_file_ok = False
            else:
                key = (sf, rec.get('title', '').strip(), rec.get('date'))
                if key not in expected_keyset:
                    source_file_ok = False
            topic = rec.get('topic', None)
            if topic is not None and topics_order:
                allowed_topics = [t for (t, _) in topics_order]
                if topic not in allowed_topics:
                    field_types_ok = False
                    break
        if field_types_ok and tags_ok and date_month_ok and source_file_ok and len(ids) == len(debug_records):
            schema_ok = True

    if schema_ok:
        scores["extractor_schema_and_fields_valid"] = 1.0

    match_html_ok = False
    if debug_records is not None and expected_articles:
        expected_set = set(
            (str(a['source_file']), a['title'].strip(), a['date'])
            for a in expected_articles
        )
        actual_set = set(
            (str(r.get('source_file')), (r.get('title') or '').strip(), r.get('date'))
            for r in debug_records
            if isinstance(r, dict) and 'source_file' in r and 'title' in r and 'date' in r
        )
        if len(debug_records) == expected_count and actual_set == expected_set:
            match_html_ok = True

    if match_html_ok:
        scores["extracted_records_match_html"] = 1.0

    topic_ok = False
    if debug_records is not None and expected_articles and cfg:
        exp_map: Dict[Tuple[str, str, str], Optional[str]] = {}
        for art in expected_articles:
            exp_topic = compute_topic_for_article(art, topics_order, rules)
            key = (str(art['source_file']), art['title'].strip(), art['date'])
            exp_map[key] = exp_topic
        all_match = True
        for r in debug_records:
            key = (str(r.get('source_file')), (r.get('title') or '').strip(), r.get('date'))
            if key not in exp_map:
                all_match = False
                break
            rec_topic = r.get('topic')
            if exp_map[key] != rec_topic:
                all_match = False
                break
        if all_match:
            topic_ok = True
    if topic_ok:
        scores["topic_assignment_correct"] = 1.0

    counts_csv_path = workspace / "output" / "monthly_topic_counts.csv"
    counts_csv = safe_read_csv(counts_csv_path)
    if counts_csv is not None:
        header, rows = counts_csv
        if header == ["month", "topic", "mentions"]:
            scores["monthly_counts_csv_present_and_parsable"] = 1.0

    expected_counts_from_html: Dict[Tuple[str, str], int] = {}
    if cfg and expected_articles:
        expected_counts_from_html = group_counts_from_articles(expected_articles, topics_order, rules)

    counts_match_expected_ok = False
    if counts_csv is not None and expected_counts_from_html:
        header, rows = counts_csv
        if header == ["month", "topic", "mentions"]:
            csv_map: Dict[Tuple[str, str], int] = {}
            try:
                for r in rows:
                    if len(r) != 3:
                        raise ValueError("bad row length")
                    m, t, c = r
                    if not isinstance(m, str) or not isinstance(t, str):
                        raise ValueError("bad types")
                    if not m or not t:
                        raise ValueError("empty fields")
                    c_int = int(c)
                    if c_int < 0:
                        raise ValueError("negative")
                    csv_map[(m, t)] = c_int
                if csv_map == expected_counts_from_html:
                    counts_match_expected_ok = True
            except Exception:
                counts_match_expected_ok = False
    if counts_match_expected_ok:
        scores["monthly_counts_match_expected_html"] = 1.0

    cross_ok = False
    if counts_csv is not None and debug_records is not None:
        header, rows = counts_csv
        if header == ["month", "topic", "mentions"]:
            csv_map: Dict[Tuple[str, str], int] = {}
            try:
                for r in rows:
                    m, t, c = r
                    csv_map[(m, t)] = int(c)
                dbg_counts = group_counts(debug_records)
                if csv_map == dbg_counts:
                    cross_ok = True
            except Exception:
                cross_ok = False
    if cross_ok:
        scores["cross_validation_counts_consistent"] = 1.0

    tr_path = workspace / "output" / "trending_report.json"
    tr_json = safe_load_json(tr_path)
    parsed_tr = None
    if isinstance(tr_json, list) and all(isinstance(item, dict) for item in tr_json):
        scores["trending_report_present_and_parsable"] = 1.0
        parsed_tr = tr_json

    tr_values_ok = False
    if parsed_tr is not None and cfg and expected_articles:
        all_months = sorted({a['month'] for a in expected_articles if a.get('month')})
        prev_months = set(all_months[1:])
        expected_entries: Dict[Tuple[str, str], dict] = {}
        counts_by_mt = expected_counts_from_html
        min_mentions = thresholds.get('min_monthly_mentions', 0)
        min_growth = thresholds.get('min_growth_pct', 0)
        for (month, topic), cur_count in counts_by_mt.items():
            if month not in prev_months:
                continue
            prev_m = month_prev(month)
            prev_count = counts_by_mt.get((prev_m, topic), 0)
            if prev_count == 0:
                growth = None
            else:
                growth = round(((cur_count - prev_count) / prev_count) * 100.0, 1)
            trending = (cur_count >= min_mentions) or (growth is not None and growth >= min_growth)
            basis = None
            if trending:
                count_met = cur_count >= min_mentions
                growth_met = (growth is not None and growth >= min_growth)
                if count_met and growth_met:
                    basis = "both"
                elif count_met:
                    basis = "count"
                elif growth_met:
                    basis = "growth"
            expected_entries[(month, topic)] = {
                "month": month,
                "topic": topic,
                "mentions": cur_count,
                "prev_mentions": prev_count,
                "growth_pct": growth,
                "trending": trending,
                "basis": basis,
            }

        actual_entries: Dict[Tuple[str, str], dict] = {}
        try:
            for item in parsed_tr:
                month = item.get("month")
                topic = item.get("topic")
                if not isinstance(month, str) or not isinstance(topic, str):
                    raise ValueError("bad month/topic")
                actual_entries[(month, topic)] = item
        except Exception:
            actual_entries = {}

        if set(actual_entries.keys()) == set(expected_entries.keys()) and expected_entries:
            all_good = True
            for key, exp in expected_entries.items():
                act = actual_entries.get(key)
                if act is None:
                    all_good = False
                    break
                try:
                    if int(act.get("mentions")) != exp["mentions"]:
                        all_good = False
                        break
                    if int(act.get("prev_mentions")) != exp["prev_mentions"]:
                        all_good = False
                        break
                except Exception:
                    all_good = False
                    break
                gp_act = act.get("growth_pct", None)
                gp_exp = exp["growth_pct"]
                if gp_exp is None:
                    if gp_act is not None:
                        all_good = False
                        break
                else:
                    try:
                        gp_act_num = float(gp_act)
                        if abs(gp_act_num - gp_exp) > 0.05:
                            all_good = False
                            break
                    except Exception:
                        all_good = False
                        break
                if isinstance(act.get("trending"), bool):
                    if act["trending"] != exp["trending"]:
                        all_good = False
                        break
                else:
                    all_good = False
                    break
                basis_act = act.get("basis", None)
                if exp["trending"]:
                    if basis_act != exp["basis"]:
                        all_good = False
                        break
                else:
                    if "basis" not in act:
                        all_good = False
                        break
                if act.get("month") != exp["month"] or act.get("topic") != exp["topic"]:
                    all_good = False
                    break
            if all_good:
                tr_values_ok = True

    if tr_values_ok:
        scores["trending_report_values_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()