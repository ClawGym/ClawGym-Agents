import sys
import json
import csv
from pathlib import Path
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_dicts_safe(path: Path) -> Tuple[Optional[List[dict]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            if fieldnames is None:
                return [], []
            rows = [row for row in reader]
            return rows, fieldnames
    except Exception:
        return None, None


def _load_proposals(workspace: Path) -> Tuple[Optional[List[dict]], Optional[Dict[str, dict]]]:
    proposals_path = workspace / "input" / "proposals.csv"
    rows, fieldnames = _read_csv_dicts_safe(proposals_path)
    if rows is None or fieldnames is None:
        return None, None
    # Validate required columns exist
    required_cols = {"proposal_id", "title", "neighborhood", "topic", "estimated_cost"}
    if not required_cols.issubset(set(fieldnames)):
        return None, None
    by_id = {}
    for r in rows:
        pid = r.get("proposal_id", "").strip()
        if pid == "":
            return None, None
        by_id[pid] = r
    return rows, by_id


class _StanceHTMLParser(HTMLParser):
    def __init__(self, allowed_ids: set, counts: Dict[str, Dict[str, int]]):
        super().__init__(convert_charrefs=True)
        self.allowed_ids = allowed_ids
        self.counts = counts
        # Stack of tuples: (is_allowed_article, pid_if_allowed_else_None)
        self.article_stack: List[Tuple[bool, Optional[str]]] = []

    def _current_active_pid(self) -> Optional[str]:
        for is_allowed, pid in reversed(self.article_stack):
            if is_allowed and pid is not None:
                return pid
        return None

    def handle_starttag(self, tag: str, attrs):
        attrd = {k.lower(): v for k, v in attrs}
        if tag.lower() == "article":
            pid = attrd.get("data-proposal-id")
            if pid in self.allowed_ids:
                self.article_stack.append((True, pid))
            else:
                self.article_stack.append((False, None))
            return
        if tag.lower() == "li":
            pid = self._current_active_pid()
            if pid is None:
                return
            # Must be class contains 'comment'
            cls = attrd.get("class", "")
            class_tokens = cls.split()
            if "comment" not in class_tokens:
                return
            stance = attrd.get("data-stance", "")
            if stance not in ("support", "neutral", "oppose"):
                return
            # Count
            self.counts[pid][f"{stance}_count"] += 1

    def handle_endtag(self, tag: str):
        if tag.lower() == "article":
            if self.article_stack:
                self.article_stack.pop()


def _parse_comment_counts(workspace: Path, allowed_ids: set) -> Optional[Dict[str, Dict[str, int]]]:
    html_paths = [
        workspace / "input" / "comments_page1.html",
        workspace / "input" / "comments_page2.html",
    ]
    texts = []
    for p in html_paths:
        t = _read_text_safe(p)
        if t is None:
            return None
        texts.append(t)
    counts = {pid: {"support_count": 0, "neutral_count": 0, "oppose_count": 0} for pid in allowed_ids}
    parser = _StanceHTMLParser(allowed_ids, counts)
    try:
        for t in texts:
            parser.feed(t)
        parser.close()
    except Exception:
        return None
    return counts


def _format_ratio(numer: int, denom: int) -> str:
    if denom == 0:
        return "0.000"
    return f"{(numer / denom):.3f}"


def _expected_aggregated(proposals_by_id: Dict[str, dict], counts: Dict[str, Dict[str, int]]) -> Dict[str, dict]:
    exp = {}
    for pid, prow in proposals_by_id.items():
        s = counts.get(pid, {}).get("support_count", 0)
        n = counts.get(pid, {}).get("neutral_count", 0)
        o = counts.get(pid, {}).get("oppose_count", 0)
        total = s + n + o
        ratio = _format_ratio(s, total)
        exp_row = {
            "proposal_id": pid,
            "title": prow.get("title", "").strip(),
            "neighborhood": prow.get("neighborhood", "").strip(),
            "topic": prow.get("topic", "").strip(),
            "estimated_cost": prow.get("estimated_cost", "").strip(),
            "support_count": str(s),
            "neutral_count": str(n),
            "oppose_count": str(o),
            "total_comments": str(total),
            "support_ratio": ratio,
        }
        exp[pid] = exp_row
    return exp


def _to_float_number(s: str) -> Optional[float]:
    try:
        return float(s.strip())
    except Exception:
        return None


def _expected_prioritized(exp_agg: Dict[str, dict]) -> List[dict]:
    # Filter total_comments >= 3
    items = []
    for pid, r in exp_agg.items():
        try:
            total = int(r["total_comments"])
        except Exception:
            total = -1
        if total >= 3:
            # Parse support_ratio numeric for tie-breaker
            sr = _to_float_number(r["support_ratio"])
            if sr is None:
                sr = -1.0
            cost = _to_float_number(r["estimated_cost"])
            if cost is None:
                cost = float("inf")
            items.append((pid, total, sr, cost, r))
    # Sort by total desc, ratio desc, cost asc
    items.sort(key=lambda x: (-x[1], -x[2], x[3]))
    ranked = []
    rank = 1
    for pid, total, sr, cost, r in items:
        ranked.append({
            "rank": str(rank),
            "proposal_id": r["proposal_id"],
            "title": r["title"],
            "topic": r["topic"],
            "neighborhood": r["neighborhood"],
            "estimated_cost": r["estimated_cost"],
            "total_comments": r["total_comments"],
            "support_ratio": r["support_ratio"],
        })
        rank += 1
    return ranked


def _read_output_csv(path: Path) -> Tuple[Optional[List[dict]], Optional[List[str]]]:
    return _read_csv_dicts_safe(path)


def _normalize_str(v: str) -> str:
    return (v if isinstance(v, str) else str(v)).strip()


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "aggregated_feedback_header": 0.0,
        "aggregated_feedback_content": 0.0,
        "prioritized_agenda_header": 0.0,
        "prioritized_agenda_content": 0.0,
        "docs_overview_exists": 0.0,
        "docs_overview_content": 0.0,
    }

    # Load inputs
    proposals_rows, proposals_by_id = _load_proposals(workspace)
    if proposals_rows is None or proposals_by_id is None:
        # Cannot compute expectations; leave scores at 0.0 but still check docs existence
        pass
    else:
        allowed_ids = set(proposals_by_id.keys())
        counts = _parse_comment_counts(workspace, allowed_ids)
        if counts is None:
            # Cannot compute expectations
            pass
        else:
            expected_agg = _expected_aggregated(proposals_by_id, counts)
            expected_prioritized = _expected_prioritized(expected_agg)

            # Check aggregated_feedback.csv
            agg_path = workspace / "output" / "aggregated_feedback.csv"
            agg_rows, agg_fields = _read_output_csv(agg_path)
            expected_agg_header = [
                "proposal_id",
                "title",
                "neighborhood",
                "topic",
                "estimated_cost",
                "support_count",
                "neutral_count",
                "oppose_count",
                "total_comments",
                "support_ratio",
            ]
            if agg_rows is not None and agg_fields is not None and agg_fields == expected_agg_header:
                scores["aggregated_feedback_header"] = 1.0
            else:
                scores["aggregated_feedback_header"] = 0.0

            if agg_rows is not None and agg_fields is not None and agg_fields == expected_agg_header:
                # Build mapping by proposal_id, compare content ignoring row order
                got_map: Dict[str, dict] = {}
                valid = True
                for row in agg_rows:
                    pid = _normalize_str(row.get("proposal_id", ""))
                    if pid == "" or pid in got_map:
                        valid = False
                        break
                    # Normalize expected columns only
                    got_map[pid] = {k: _normalize_str(row.get(k, "")) for k in expected_agg_header}
                # Ensure all proposals present
                if valid and set(got_map.keys()) == set(expected_agg.keys()):
                    # Compare field-by-field
                    for pid, exp_row in expected_agg.items():
                        got_row = got_map.get(pid)
                        if got_row is None:
                            valid = False
                            break
                        for k in expected_agg_header:
                            if _normalize_str(got_row.get(k, "")) != _normalize_str(exp_row.get(k, "")):
                                valid = False
                                break
                        if not valid:
                            break
                else:
                    valid = False
                scores["aggregated_feedback_content"] = 1.0 if valid else 0.0
            else:
                scores["aggregated_feedback_content"] = 0.0

            # Check prioritized_agenda_overall.csv
            prio_path = workspace / "output" / "prioritized_agenda_overall.csv"
            prio_rows, prio_fields = _read_output_csv(prio_path)
            expected_prio_header = [
                "rank",
                "proposal_id",
                "title",
                "topic",
                "neighborhood",
                "estimated_cost",
                "total_comments",
                "support_ratio",
            ]
            if prio_rows is not None and prio_fields is not None and prio_fields == expected_prio_header:
                scores["prioritized_agenda_header"] = 1.0
            else:
                scores["prioritized_agenda_header"] = 0.0

            if prio_rows is not None and prio_fields is not None and prio_fields == expected_prio_header:
                # Compare exact row order and content
                valid = True
                # Normalize got
                got_list = [{k: _normalize_str(r.get(k, "")) for k in expected_prio_header} for r in prio_rows]
                # Compare length
                if len(got_list) != len(expected_prioritized):
                    valid = False
                else:
                    # Check ranks strictly incremental starting at 1 and content equality in order
                    for idx, (got, exp) in enumerate(zip(got_list, expected_prioritized), start=1):
                        # Rank must be idx as string
                        if got.get("rank") != str(idx):
                            valid = False
                            break
                        # Compare all fields
                        for k in expected_prio_header:
                            if got.get(k, "") != exp.get(k, ""):
                                valid = False
                                break
                        if not valid:
                            break
                scores["prioritized_agenda_content"] = 1.0 if valid else 0.0
            else:
                scores["prioritized_agenda_content"] = 0.0

    # Check docs/solution_overview.md
    docs_path = workspace / "docs" / "solution_overview.md"
    docs_text = _read_text_safe(docs_path)
    if docs_text is not None:
        scores["docs_overview_exists"] = 1.0
        text_lower = docs_text.lower()
        # Content checks:
        # Inputs mentioned
        has_inputs = all(s in docs_text for s in [
            "input/proposals.csv",
            "input/comments_page1.html",
            "input/comments_page2.html",
        ])
        # Parsing approach mentions
        mentions_parsing = all(token in text_lower for token in ["article", "data-proposal-id", "data-stance"]) and ("li" in text_lower and "comment" in text_lower)
        # Stance values mentioned explicitly
        mentions_stances = all(token in text_lower for token in ["support", "neutral", "oppose"])
        # Join/aggregation mentioned
        mentions_join = "proposal_id" in text_lower and ("join" in text_lower or "merge" in text_lower)
        # Derived fields and filtering logic
        mentions_fields = ("total_comments" in text_lower) and ("support_ratio" in text_lower)
        mentions_filter = ("total_comments" in text_lower) and (">= 3" in docs_text or ">=3" in docs_text or "at least 3" in text_lower)
        # Ranking logic with directions
        mentions_ranking_fields = all(token in text_lower for token in ["total_comments", "support_ratio", "estimated_cost"])
        mentions_directions = ("descending" in text_lower and "ascending" in text_lower)
        # Assumptions and rerun instructions
        mentions_assumptions = ("assumption" in text_lower or "assumptions" in text_lower)
        mentions_rerun = ("run" in text_lower or "execute" in text_lower or "python" in text_lower)
        docs_ok = (has_inputs and mentions_parsing and mentions_stances and mentions_join and
                   mentions_fields and mentions_filter and mentions_ranking_fields and mentions_directions and
                   mentions_assumptions and mentions_rerun)
        scores["docs_overview_content"] = 1.0 if docs_ok else 0.0
    else:
        scores["docs_overview_exists"] = 0.0
        scores["docs_overview_content"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()