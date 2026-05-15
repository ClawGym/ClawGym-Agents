import csv
import json
import re
import sys
import subprocess
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from urllib.parse import urlparse


def _safe_read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path):
    try:
        text = _safe_read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _safe_load_csv(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = list(reader)
            return header, rows
    except Exception:
        return None, None


def _parse_allowed_domains_yaml(path: Path):
    text = _safe_read_text(path)
    if text is None:
        return None
    official = None
    endorsed = []
    in_endorsed = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if re.match(r"^official_domain\s*:", line):
            m = re.match(r"^official_domain\s*:\s*(.*)$", line)
            if m:
                val = m.group(1).strip()
                if val.startswith('"') and val.endswith('"'):
                    val = val[1:-1]
                elif val.startswith("'") and val.endswith("'"):
                    val = val[1:-1]
                official = val
            in_endorsed = False
        elif re.match(r"^endorsed_domains\s*:", line):
            in_endorsed = True
        elif in_endorsed:
            if line.startswith("-"):
                item = line[1:].strip()
                if item.startswith('"') and item.endswith('"'):
                    item = item[1:-1]
                elif item.startswith("'") and item.endswith("'"):
                    item = item[1:-1]
                if item:
                    endorsed.append(item)
            else:
                in_endorsed = False
        else:
            in_endorsed = False
    allowed = set()
    if official:
        allowed.add(official.strip().lower())
    for d in endorsed:
        if d:
            allowed.add(d.strip().lower())
    if not allowed:
        return None
    return allowed


def _extract_domain(url: str) -> str:
    try:
        parsed = urlparse(url.strip())
        host = parsed.netloc
        if not host and parsed.path and "://" not in url:
            parsed = urlparse("http://" + url.strip())
            host = parsed.netloc
        if not host:
            return ""
        if "@" in host:
            host = host.split("@", 1)[1]
        if ":" in host:
            host = host.split(":", 1)[0]
        host = host.lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def _domain_allowed(domain: str, allowed: set) -> bool:
    d = (domain or "").lower()
    if d in allowed:
        return True
    return any(d.endswith("." + a) for a in allowed)


def _is_yyyy_mm_dd(s: str) -> bool:
    if not isinstance(s, str):
        return False
    if s == "":
        return True
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return False
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except Exception:
        return False


def _is_iso8601_datetime(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    if "T" not in s and " " not in s:
        return False
    s2 = s.replace("Z", "+00:00")
    try:
        datetime.fromisoformat(s2)
        return True
    except Exception:
        return False


def _round_share(count: int, total: int) -> float:
    if total == 0:
        return 0.0
    q = (Decimal(count) / Decimal(total)).quantize(Decimal("0.000"), rounding=ROUND_HALF_UP)
    return float(q)


def _load_topics(path: Path):
    header, rows = _safe_load_csv(path)
    if header is None or rows is None:
        return None
    if "topic" not in header:
        return None
    topics = [r.get("topic", "").strip() for r in rows if r.get("topic", "").strip()]
    return topics


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "ci_sh_present": 0.0,
        "ci_sh_test_step_passes": 0.0,
        "raw_json_present": 0.0,
        "raw_json_structure_valid": 0.0,
        "references_csv_structure": 0.0,
        "references_found_at_isoformat": 0.0,
        "references_no_duplicate_rows": 0.0,
        "references_published_date_format": 0.0,
        "references_rows_allowed_domains": 0.0,
        "summary_counts_match": 0.0,
        "summary_json_structure": 0.0,
    }

    topics_path = workspace / "input" / "search_topics.csv"
    topics = _load_topics(topics_path)
    allowed_yaml_path = workspace / "input" / "config" / "party.yaml"
    allowed_domains = _parse_allowed_domains_yaml(allowed_yaml_path)

    ci_sh = workspace / "ci.sh"
    if ci_sh.exists() and ci_sh.is_file():
        scores["ci_sh_present"] = 1.0

    raw_dir = workspace / "out" / "raw_search"
    raw_present_ok = False
    raw_structure_ok = False
    if topics is not None:
        present_all = True
        structure_all = True
        if raw_dir.exists() and raw_dir.is_dir():
            for t in topics:
                f = raw_dir / f"{t}.json"
                if not f.exists() or not f.is_file():
                    present_all = False
                    structure_all = False
                    continue
                data = _safe_load_json(f)
                if data is None:
                    structure_all = False
                    continue
                results = None
                if isinstance(data, list):
                    results = data
                elif isinstance(data, dict) and "results" in data and isinstance(data["results"], list):
                    results = data["results"]
                else:
                    structure_all = False
                    continue
                for item in results:
                    if not isinstance(item, dict):
                        structure_all = False
                        break
                    title = item.get("title")
                    url = item.get("url")
                    if not isinstance(title, str) or not isinstance(url, str) or not title.strip() or not url.strip():
                        structure_all = False
                        break
                    if "published_date" in item and item["published_date"] is not None and not isinstance(item["published_date"], str):
                        structure_all = False
                        break
        else:
            present_all = False
            structure_all = False
        raw_present_ok = present_all
        raw_structure_ok = structure_all

    scores["raw_json_present"] = 1.0 if raw_present_ok else 0.0
    scores["raw_json_structure_valid"] = 1.0 if raw_structure_ok else 0.0

    references_csv = workspace / "out" / "references.csv"
    header, rows = _safe_load_csv(references_csv)
    expected_header = ["topic", "title", "url", "source_domain", "published_date", "found_at"]
    if header is not None and rows is not None and header == expected_header:
        scores["references_csv_structure"] = 1.0

        allowed_ok = True
        pub_date_ok = True
        found_at_ok = True
        no_dups_ok = True

        seen_rows = set()
        for r in rows:
            topic = (r.get("topic") or "").strip()
            title = (r.get("title") or "").strip()
            url = (r.get("url") or "").strip()
            src_domain = (r.get("source_domain") or "").strip().lower()
            pub_date = (r.get("published_date") or "")
            found_at = (r.get("found_at") or "")

            tup = (topic, title, url, src_domain, pub_date, found_at)
            if tup in seen_rows:
                no_dups_ok = False
            else:
                seen_rows.add(tup)

            if allowed_domains is None:
                allowed_ok = False
            else:
                extracted = _extract_domain(url)
                src_norm = src_domain[4:] if src_domain.startswith("www.") else src_domain
                ext_norm = extracted[4:] if extracted.startswith("www.") else extracted
                if src_norm != ext_norm:
                    allowed_ok = False
                if not _domain_allowed(src_domain, allowed_domains):
                    allowed_ok = False

            if not _is_yyyy_mm_dd(pub_date):
                pub_date_ok = False

            if not _is_iso8601_datetime(found_at):
                found_at_ok = False

        scores["references_rows_allowed_domains"] = 1.0 if allowed_ok else 0.0
        scores["references_published_date_format"] = 1.0 if pub_date_ok else 0.0
        scores["references_found_at_isoformat"] = 1.0 if found_at_ok else 0.0
        scores["references_no_duplicate_rows"] = 1.0 if no_dups_ok else 0.0

    summary_json = workspace / "out" / "stats" / "summary.json"
    summary = _safe_load_json(summary_json)
    structure_ok = False
    counts_match_ok = False
    if summary is not None and isinstance(summary, dict):
        keys = set(summary.keys())
        expected_keys = {"generated_at", "total_results_all", "by_domain", "by_topic"}
        if keys == expected_keys:
            ga = summary.get("generated_at")
            tra = summary.get("total_results_all")
            bd = summary.get("by_domain")
            bt = summary.get("by_topic")
            if isinstance(ga, str) and isinstance(tra, int) and isinstance(bd, list) and isinstance(bt, list):
                if _is_iso8601_datetime(ga):
                    bd_ok = True
                    for item in bd:
                        if not isinstance(item, dict):
                            bd_ok = False
                            break
                        if set(item.keys()) != {"domain", "count", "share"}:
                            bd_ok = False
                            break
                        if not isinstance(item.get("domain"), str) or not isinstance(item.get("count"), int):
                            bd_ok = False
                            break
                        if not isinstance(item.get("share"), (int, float)):
                            bd_ok = False
                            break
                    bt_ok = True
                    for item in bt:
                        if not isinstance(item, dict):
                            bt_ok = False
                            break
                        if set(item.keys()) != {"topic", "count", "top_domain"}:
                            bt_ok = False
                            break
                        if not isinstance(item.get("topic"), str) or not isinstance(item.get("count"), int) or not isinstance(item.get("top_domain"), str):
                            bt_ok = False
                            break
                    if bd_ok and bt_ok:
                        structure_ok = True

    scores["summary_json_structure"] = 1.0 if structure_ok else 0.0

    if structure_ok and header is not None and rows is not None and header == expected_header:
        total = len(rows)
        domain_counts = Counter()
        topic_domain_counts = defaultdict(Counter)
        topic_counts = Counter()

        for r in rows:
            src_domain = (r.get("source_domain") or "").strip().lower()
            topic = (r.get("topic") or "").strip()
            domain_counts[src_domain] += 1
            topic_counts[topic] += 1
            topic_domain_counts[topic][src_domain] += 1

        if summary.get("total_results_all") != total:
            counts_match_ok = False
        else:
            sj_by_domain = summary.get("by_domain", [])
            sj_bd_map = {}
            for item in sj_by_domain:
                sj_bd_map[item["domain"].lower()] = {"count": item["count"], "share": float(item["share"])}

            csv_domains = set(domain_counts.keys())
            sj_domains = set([d for d, v in sj_bd_map.items() if v["count"] > 0 or total == 0])
            if csv_domains != sj_domains:
                counts_match_ok = False
            else:
                ok_bd = True
                for d in csv_domains:
                    c = domain_counts[d]
                    item = sj_bd_map.get(d)
                    if item is None or item["count"] != c:
                        ok_bd = False
                        break
                    expected_share = _round_share(c, total)
                    if round(float(item["share"]), 3) != round(expected_share, 3):
                        ok_bd = False
                        break
                if not ok_bd:
                    counts_match_ok = False
                else:
                    sj_by_topic = summary.get("by_topic", [])
                    sj_bt_map = {item["topic"]: {"count": item["count"], "top_domain": item["top_domain"].lower()} for item in sj_by_topic}

                    ok_bt = True
                    for t, cnt in topic_counts.items():
                        item = sj_bt_map.get(t)
                        if item is None:
                            ok_bt = False
                            break
                        if item["count"] != cnt:
                            ok_bt = False
                            break
                        if cnt == 0:
                            expected_top = ""
                        else:
                            cd = topic_domain_counts[t]
                            max_count = max(cd.values()) if cd else 0
                            top_domains = sorted([d for d, v in cd.items() if v == max_count])
                            expected_top = top_domains[0] if top_domains else ""
                        if item["top_domain"] != expected_top:
                            ok_bt = False
                            break
                    counts_match_ok = ok_bt

    scores["summary_counts_match"] = 1.0 if counts_match_ok else 0.0

    if ci_sh.exists() and ci_sh.is_file():
        try:
            proc = subprocess.run(
                ["bash", "ci.sh", "test"],
                cwd=str(workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60,
                check=False,
            )
            if proc.returncode == 0:
                scores["ci_sh_test_step_passes"] = 1.0
        except Exception:
            scores["ci_sh_test_step_passes"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()