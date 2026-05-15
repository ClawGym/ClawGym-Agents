import sys
import json
import csv
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Any


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return (reader.fieldnames or [], rows)
    except Exception:
        return None


def _normalize_bool_str(val: str) -> Optional[bool]:
    s = (val or "").strip().lower()
    if s in {"true", "t", "1", "yes"}:
        return True
    if s in {"false", "f", "0", "no"}:
        return False
    return None


def _parse_from_line(line: str) -> Tuple[str, str]:
    # Expected format: From: "Name" <email>
    # Fallbacks attempt to extract name and email if quotes absent
    m = re.match(r'^From:\s*"(.*?)"\s*<([^>]+)>', line)
    if m:
        return m.group(1), m.group(2)
    m = re.match(r"^From:\s*(.*?)\s*<([^>]+)>", line)
    if m:
        name = m.group(1).strip().strip('"')
        email = m.group(2).strip()
        return name, email
    return "", ""


def _parse_date_to_iso(s: str) -> Optional[str]:
    # s like: Date: 2026-05-11 14:05 -0500
    m = re.match(r"^Date:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\s+([0-9]{2}:[0-9]{2})\s+([+-][0-9]{4})", s.strip())
    if not m:
        return None
    dt_str = f"{m.group(1)} {m.group(2)} {m.group(3)}"
    try:
        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M %z")
        # Produce YYYY-MM-DDTHH:MM:SS±HH:MM (with colon in offset)
        basic = dt.strftime("%Y-%m-%dT%H:%M:%S%z")  # offset like -0500
        return basic[:-5] + basic[-5:-2] + ":" + basic[-2:]
    except Exception:
        return None


def _collapse_whitespace(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _extract_relationship(body: str) -> str:
    body_lower = body.lower()
    keywords = ["cousin", "nephew", "niece", "son", "daughter", "brother", "sister", "wife", "husband"]
    # Find earliest occurrence in text to choose deterministically if multiple present
    earliest = None
    which = ""
    for kw in keywords:
        for m in re.finditer(rf"\b{re.escape(kw)}\b", body_lower):
            idx = m.start()
            if earliest is None or idx < earliest:
                earliest = idx
                which = kw
            break
    return which


def _mentions_scott(subject: str, body: str) -> bool:
    text = (subject + " " + body).lower()
    phrases = [
        "william leslie kean scott jr",
        "william l. k. scott jr",
        "billy scott",
    ]
    return any(p in text for p in phrases)


def _classify_topic(subject: str, body: str) -> str:
    text = (subject + " " + body).lower()
    memorial = ("memorial" in text) or ("funeral" in text)
    reunion = "reunion" in text
    if memorial:
        return "memorial"
    if reunion:
        return "reunion"
    return "other"


def _message_has_both_topics(subject: str, body: str) -> bool:
    text = (subject + " " + body).lower()
    memorial = ("memorial" in text) or ("funeral" in text)
    reunion = "reunion" in text
    return memorial and reunion


def _parse_inbox_messages(inbox_text: str) -> List[Dict[str, str]]:
    # Returns list with keys: msg_id, from_name, from_email, date_iso, subject, body
    messages = []
    # Split by separator lines "----"
    parts = re.split(r"\n-+\n", inbox_text.strip(), flags=re.MULTILINE)
    for part in parts:
        lines = [ln.rstrip("\n") for ln in part.splitlines()]
        current = {
            "msg_id": "",
            "from_name": "",
            "from_email": "",
            "date_iso": "",
            "subject": "",
            "body": "",
        }
        i = 0
        body_lines = []
        in_body = False
        while i < len(lines):
            line = lines[i]
            if line.startswith("ID:"):
                current["msg_id"] = line.split(":", 1)[1].strip()
            elif line.startswith("From:"):
                name, email = _parse_from_line(line)
                current["from_name"] = name
                current["from_email"] = email
            elif line.startswith("Date:"):
                iso = _parse_date_to_iso(line)
                current["date_iso"] = iso or ""
            elif line.startswith("Subject:"):
                current["subject"] = line.split(":", 1)[1].strip()
            elif line.strip() == "Body:":
                in_body = True
            elif in_body:
                body_lines.append(line)
            i += 1
        # Trim trailing blank lines from body
        while body_lines and body_lines[-1].strip() == "":
            body_lines.pop()
        current["body"] = "\n".join(body_lines).strip()
        messages.append(current)
    return messages


def _load_roster(workspace: Path) -> Dict[str, str]:
    roster_path = workspace / "input" / "roster.csv"
    result: Dict[str, str] = {}
    try:
        with roster_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                email = (row.get("Email") or "").strip()
                platoon = (row.get("Platoon") or "").strip()
                if email:
                    result[email] = platoon
    except Exception:
        pass
    return result


def _expected_messages_structured(workspace: Path) -> Optional[List[Dict[str, str]]]:
    inbox_path = workspace / "input" / "inbox_may2026.txt"
    inbox_text = _safe_read_text(inbox_path)
    if inbox_text is None:
        return None
    roster = _load_roster(workspace)

    msgs = _parse_inbox_messages(inbox_text)
    structured = []
    for m in msgs:
        subject = m["subject"]
        body = m["body"]
        body_excerpt = _collapse_whitespace(body)[:120]
        mentions = _mentions_scott(subject, body)
        topic = _classify_topic(subject, body)
        email = m["from_email"]
        is_match = email in roster
        platoon = roster[email] if is_match else ""
        relationship = _extract_relationship(body)
        structured.append({
            "msg_id": m["msg_id"],
            "from_name": m["from_name"],
            "from_email": email,
            "date_iso": m["date_iso"],
            "subject": subject,
            "body_excerpt": body_excerpt,
            "mentions_scott": "true" if mentions else "false",
            "topic": topic,
            "is_roster_match": "true" if is_match else "false",
            "roster_platoon": platoon,
            "relationship_in_body": relationship,
        })
    return structured


def _expected_event_dates(workspace: Path) -> Optional[Dict[str, str]]:
    html_path = workspace / "input" / "newsletter.html"
    html = _safe_read_text(html_path)
    if html is None:
        return None

    def extract_articles(html_text: str) -> List[str]:
        # Extract opening <article ...> tag strings
        tags = []
        for m in re.finditer(r"<article\b[^>]*>", html_text, flags=re.IGNORECASE | re.DOTALL):
            tags.append(m.group(0))
        return tags

    memorial_date = None
    reunion_date = None
    for tag in extract_articles(html):
        tag_lower = tag.lower()
        # Reunion identified by data-type="reunion"
        if 'data-type="reunion"' in tag_lower:
            m = re.search(r'data-date="([0-9]{4}-[0-9]{2}-[0-9]{2})"', tag, flags=re.IGNORECASE)
            if m:
                reunion_date = m.group(1)
        # Memorial identified by class="memorial"
        if re.search(r'class="[^"]*\bmemorial\b[^"]*"', tag_lower):
            m = re.search(r'data-date="([0-9]{4}-[0-9]{2}-[0-9]{2})"', tag, flags=re.IGNORECASE)
            if m:
                memorial_date = m.group(1)
    if not memorial_date or not reunion_date:
        # Fallback: search anywhere for data with attributes
        if not reunion_date:
            m = re.search(r'<article[^>]*data-type="reunion"[^>]*data-date="([0-9]{4}-[0-9]{2}-[0-9]{2})"[^>]*>', html, flags=re.IGNORECASE | re.DOTALL)
            if m:
                reunion_date = m.group(1)
        if not memorial_date:
            m = re.search(r'<article[^>]*class="[^"]*\bmemorial\b[^"]*"[^>]*data-date="([0-9]{4}-[0-9]{2}-[0-9]{2})"[^>]*>', html, flags=re.IGNORECASE | re.DOTALL)
            if m:
                memorial_date = m.group(1)
    if not memorial_date or not reunion_date:
        return None
    return {"memorial_date": memorial_date, "reunion_date": reunion_date}


def _expected_top_ranking(workspace: Path, structured: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    # Filter mentions_scott == true
    items = []
    for row in structured:
        mentions = row["mentions_scott"] == "true"
        if not mentions:
            continue
        # Parse date
        try:
            dt = datetime.fromisoformat(row["date_iso"])
        except Exception:
            # Fallback parse potential non-colon offset (shouldn't happen with our expected set)
            dt = None
        items.append({
            "msg_id": row["msg_id"],
            "from_name": row["from_name"],
            "from_email": row["from_email"],
            "topic": row["topic"],
            "is_roster_match": row["is_roster_match"] == "true",
            "date_iso": row["date_iso"],
            "dt": dt,
        })

    # Topic priority mapping
    topic_priority = {"memorial": 2, "reunion": 1, "other": 0}

    def sort_key(x):
        return (
            0 if x["is_roster_match"] else 1,  # roster first
            -topic_priority.get(x["topic"], 0),  # memorial > reunion > other
            # Newer date first: sort uses ascending, so invert timestamp
            -(x["dt"].timestamp() if x["dt"] else float("-inf")),
            x["from_name"].lower(),
        )

    items_sorted = sorted(items, key=sort_key)
    top = items_sorted[:5]
    # Build ranking with simple explanation text (we won't enforce exact wording when grading)
    expected = []
    for idx, it in enumerate(top, start=1):
        explanation_parts = []
        explanation_parts.append("roster match" if it["is_roster_match"] else "non-roster")
        explanation_parts.append(f"topic={it['topic']}")
        explanation_parts.append("newer date prioritized")
        explanation = "; ".join(explanation_parts)
        expected.append({
            "msg_id": it["msg_id"],
            "rank": idx,
            "from_name": it["from_name"],
            "from_email": it["from_email"],
            "topic": it["topic"],
            "is_roster_match": it["is_roster_match"],
            "date_iso": it["date_iso"],
            "score_explanation": explanation,
        })
    return expected


def _compare_csv_rows(expected: List[Dict[str, str]], actual_rows: List[Dict[str, str]], keys: List[str]) -> bool:
    if len(expected) != len(actual_rows):
        return False
    # Create id -> row maps to avoid requiring order
    exp_map = {r["msg_id"]: r for r in expected}
    act_map = {r.get("msg_id", ""): r for r in actual_rows}
    if set(exp_map.keys()) != set(act_map.keys()):
        return False
    # Compare content for each
    for mid, exp in exp_map.items():
        act = act_map.get(mid, {})
        for k in keys:
            ev = exp.get(k, "")
            av = act.get(k, "")
            # Booleans:
            if k in {"mentions_scott", "is_roster_match"}:
                ev_bool = ev == "true"
                av_bool = _normalize_bool_str(av)
                if av_bool is None or av_bool != ev_bool:
                    return False
            elif k in {"topic"}:
                if (av or "").strip().lower() != (ev or "").strip().lower():
                    return False
            else:
                if (av or "") != (ev or ""):
                    return False
    return True


def _load_messages_structured_output(workspace: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    out_path = workspace / "outputs" / "messages_structured.csv"
    parsed = _safe_read_csv_dicts(out_path)
    return parsed


def _load_top_priority_ranking(workspace: Path) -> Optional[List[Dict[str, Any]]]:
    path = workspace / "outputs" / "top_priority_ranking.json"
    data = _safe_load_json(path)
    if not isinstance(data, list):
        return None
    return data


def _file_contains_line(content: str, line: str) -> bool:
    lines = [ln.rstrip("\r\n") for ln in content.splitlines()]
    return any(ln.strip() == line for ln in lines)


def _contains_ordered_substrings(text: str, first: str, second: str) -> bool:
    a = text.find(first)
    if a == -1:
        return False
    b = text.find(second, a + len(first))
    return b != -1


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "messages_structured_exists": 0.0,
        "messages_structured_columns": 0.0,
        "messages_structured_row_count": 0.0,
        "messages_structured_field_values": 0.0,
        "event_dates_json_correct": 0.0,
        "top_priority_ranking_exists_and_structure": 0.0,
        "top_priority_ranking_order_and_fields": 0.0,
        "drafts_three_files_exist": 0.0,
        "drafts_content_correct": 0.0,
    }

    # Expected derived data
    expected_structured = _expected_messages_structured(workspace)
    expected_event_dates = _expected_event_dates(workspace)

    # 1) messages_structured.csv checks
    parsed_out = _load_messages_structured_output(workspace)
    required_columns = [
        "msg_id",
        "from_name",
        "from_email",
        "date_iso",
        "subject",
        "body_excerpt",
        "mentions_scott",
        "topic",
        "is_roster_match",
        "roster_platoon",
        "relationship_in_body",
    ]
    if parsed_out is not None:
        scores["messages_structured_exists"] = 1.0
        out_cols, out_rows = parsed_out
        if out_cols == required_columns:
            scores["messages_structured_columns"] = 1.0
        # Row count
        if expected_structured is not None and isinstance(out_rows, list):
            if len(out_rows) == len(expected_structured):
                scores["messages_structured_row_count"] = 1.0
            # Field value comparison
            # Compare key fields strictly
            cmp_keys = required_columns
            if _compare_csv_rows(expected_structured, out_rows, cmp_keys):
                scores["messages_structured_field_values"] = 1.0
    else:
        # no file
        scores["messages_structured_exists"] = 0.0

    # 2) event_dates.json check
    event_dates_out_path = workspace / "outputs" / "event_dates.json"
    event_dates_out = _safe_load_json(event_dates_out_path)
    if expected_event_dates is not None and isinstance(event_dates_out, dict):
        if (
            event_dates_out.get("memorial_date") == expected_event_dates.get("memorial_date")
            and event_dates_out.get("reunion_date") == expected_event_dates.get("reunion_date")
        ):
            scores["event_dates_json_correct"] = 1.0

    # 3) top_priority_ranking.json checks
    ranking_out = _load_top_priority_ranking(workspace)
    if ranking_out is not None:
        # basic structure check
        basic_ok = True
        if not isinstance(ranking_out, list):
            basic_ok = False
        else:
            for item in ranking_out:
                if not isinstance(item, dict):
                    basic_ok = False
                    break
                needed = {"msg_id", "rank", "from_name", "from_email", "topic", "is_roster_match", "date_iso", "score_explanation"}
                if not needed.issubset(item.keys()):
                    basic_ok = False
                    break
                if not isinstance(item.get("score_explanation"), str) or not item.get("score_explanation").strip():
                    basic_ok = False
                    break
        if basic_ok:
            scores["top_priority_ranking_exists_and_structure"] = 1.0

        # content and ordering check
        if expected_structured is not None:
            expected_rank_list = _expected_top_ranking(workspace, expected_structured)
            # Must have up to 5 entries
            if len(ranking_out) == len(expected_rank_list):
                # Check order by msg_id and fields match except explanation
                order_ok = True
                for idx, exp in enumerate(expected_rank_list):
                    got = ranking_out[idx]
                    # Check rank matches position (1-indexed)
                    if got.get("rank") != (idx + 1):
                        order_ok = False
                        break
                    # Compare stable fields
                    if got.get("msg_id") != exp["msg_id"]:
                        order_ok = False
                        break
                    if got.get("from_name") != exp["from_name"]:
                        order_ok = False
                        break
                    if got.get("from_email") != exp["from_email"]:
                        order_ok = False
                        break
                    if (got.get("topic") or "").lower() != exp["topic"]:
                        order_ok = False
                        break
                    if bool(got.get("is_roster_match")) != bool(exp["is_roster_match"]):
                        order_ok = False
                        break
                    if got.get("date_iso") != exp["date_iso"]:
                        order_ok = False
                        break
                if order_ok:
                    scores["top_priority_ranking_order_and_fields"] = 1.0

    # 4) Draft replies for top 3 ranked messages
    drafts_exist = False
    drafts_content_ok = False
    if expected_structured is not None:
        expected_rank_list = _expected_top_ranking(workspace, expected_structured)
        top3 = expected_rank_list[:3]
        # Evaluate expected "both topics" per message from original subject/body
        inbox_text = _safe_read_text(workspace / "input" / "inbox_may2026.txt")
        msgs_full = _parse_inbox_messages(inbox_text or "")
        msg_by_id = {m["msg_id"]: m for m in msgs_full}

        # Gather event dates (either from outputs/event_dates.json or expected)
        # Prefer expected (from input) to avoid dependency on student's file
        event_dates = expected_event_dates

        all_exist = True
        content_all_ok = True
        for item in top3:
            msg_id = item["msg_id"]
            from_name = item["from_name"]
            platoon = ""
            # derive platoon from structured
            s_map = {r["msg_id"]: r for r in expected_structured}
            if msg_id in s_map:
                platoon = s_map[msg_id]["roster_platoon"]
            path = workspace / "outputs" / "drafts" / f"reply_{msg_id}.txt"
            text = _safe_read_text(path)
            if text is None:
                all_exist = False
                content_all_ok = False
                continue
            # Check greeting line
            lines = [ln.rstrip("\r\n") for ln in text.splitlines()]
            first_line = lines[0].strip() if lines else ""
            if first_line != f"Dear {from_name},":
                content_all_ok = False

            # Acknowledgement check
            body_text = text
            topic = item["topic"]
            ack_ok = False
            if topic == "memorial":
                if ("memorial" in body_text.lower()) and ("william leslie kean scott jr" in body_text.lower()):
                    ack_ok = True
            elif topic == "reunion":
                if "reunion" in body_text.lower():
                    ack_ok = True
            else:
                # For 'other', ensure a generic thanks is present
                if "thank" in body_text.lower():
                    ack_ok = True
            if not ack_ok:
                content_all_ok = False

            # Date sentences
            dates_ok = True
            if not event_dates:
                dates_ok = False
            else:
                mem_sent = f"The memorial service is on {event_dates['memorial_date']}."
                reu_sent = f"The annual reunion is on {event_dates['reunion_date']}."
                # Determine if both topics present in original message
                both_topics = False
                if msg_id in msg_by_id:
                    m = msg_by_id[msg_id]
                    both_topics = _message_has_both_topics(m["subject"], m["body"])
                if topic == "memorial":
                    if mem_sent not in body_text:
                        dates_ok = False
                    if both_topics and (reu_sent not in body_text):
                        dates_ok = False
                elif topic == "reunion":
                    if reu_sent not in body_text:
                        dates_ok = False
            if not dates_ok:
                content_all_ok = False

            # Roster/relationship line
            roster_line_ok = True
            # If roster match true, require the specific sentence
            if item["is_roster_match"] and platoon:
                # Accept both curly and straight apostrophes
                normalized = body_text.replace("’", "'")
                expected_line = f"It's good to hear from a fellow {platoon} platoon veteran."
                if expected_line not in normalized:
                    roster_line_ok = False
            else:
                # Else, if relationship exists in body, require the appreciation line
                rel = s_map.get(msg_id, {}).get("relationship_in_body", "")
                if rel:
                    expected_line = f"I appreciate {rel}s staying in touch."
                    if expected_line not in body_text:
                        roster_line_ok = False
            if not roster_line_ok:
                content_all_ok = False

            # Closing lines: Respectfully, then Lt. Col...
            closing_ok = False
            if _contains_ordered_substrings(text, "Respectfully,", "Lt. Col. (Ret.) Andrew R. Thompson"):
                closing_ok = True
            if not closing_ok:
                content_all_ok = False

        if all_exist:
            drafts_exist = True
        if content_all_ok and all_exist:
            drafts_content_ok = True

    scores["drafts_three_files_exist"] = 1.0 if drafts_exist else 0.0
    scores["drafts_content_correct"] = 1.0 if drafts_content_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()