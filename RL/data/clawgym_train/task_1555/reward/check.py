import csv
import json
import math
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _safe_read_csv(path: Path) -> Tuple[List[Dict[str, str]], Optional[List[str]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return rows, reader.fieldnames, None
    except Exception as e:
        return [], None, str(e)


def _safe_read_text(path: Path) -> Tuple[str, Optional[str]]:
    try:
        return path.read_text(encoding="utf-8"), None
    except Exception as e:
        return "", str(e)


def _parse_bool_str(v: str) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    if not isinstance(v, str):
        return None
    s = v.strip().lower()
    if s == "true":
        return True
    if s == "false":
        return False
    return None


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except Exception:
        return False


def _float_eq(a: float, b: float, tol: float = 1e-4) -> bool:
    return abs(a - b) <= tol


def _count_words(text: str) -> int:
    return len([w for w in text.split() if w])


def _contains_term(text: str, term: str) -> bool:
    if text is None:
        return False
    return term.lower() in text.lower()


def _terms_in_text(text: str, terms: List[str]) -> List[str]:
    present = []
    if text is None:
        return present
    lower_text = text.lower()
    for t in terms:
        if t.lower() in lower_text:
            present.append(t)
    return present


def _round4(x: float) -> float:
    # Emulate rounding to 4 decimals as required
    return round(x + 0.0000000001, 4)


def _header_equals(actual: Optional[List[str]], expected: List[str]) -> bool:
    if actual is None:
        return False
    return actual == expected


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "rewritten_messages_structure": 0.0,
        "original_message_match": 0.0,
        "rewritten_messages_jargon_and_flags_and_counts": 0.0,
        "rewritten_messages_content_constraints_sms": 0.0,
        "rewritten_messages_content_constraints_email_subject": 0.0,
        "rewritten_messages_content_constraints_email_body": 0.0,
        "stats_by_channel_correct": 0.0,
        "stats_by_neighborhood_correct": 0.0,
        "content_calendar_correct": 0.0,
    }

    # Load inputs
    msgs_in_path = workspace / "input" / "messages.csv"
    perf_in_path = workspace / "input" / "performance.csv"
    jargon_in_path = workspace / "input" / "jargon.txt"

    msgs_in_rows, msgs_in_header, _ = _safe_read_csv(msgs_in_path)
    perf_rows, perf_header, _ = _safe_read_csv(perf_in_path)
    jargon_text, _ = _safe_read_text(jargon_in_path)
    jargon_terms = [line.strip() for line in jargon_text.splitlines() if line.strip()]

    # Build maps from input messages
    msgs_by_id = {}
    input_channels = set()
    input_neighborhoods = set()
    if msgs_in_rows:
        for r in msgs_in_rows:
            msgs_by_id[r.get("id", "")] = r
            if "channel" in r and r["channel"]:
                input_channels.add(r["channel"])
            if "neighborhood" in r and r["neighborhood"]:
                input_neighborhoods.add(r["neighborhood"])

    # Compute expected stats from performance
    perf_by_channel = {}
    perf_by_neighborhood = {}
    channels_in_perf = set()
    neighborhoods_in_perf = set()
    perf_ok = True
    for r in perf_rows:
        try:
            nb = r["neighborhood"]
            ch = r["channel"]
            snt = float(r["sent"])
            opn = float(r["opened"])
            clk = float(r["clicked"])
        except Exception:
            perf_ok = False
            break
        if snt == 0:
            perf_ok = False
            break
        open_rate = opn / snt
        click_rate = clk / snt
        perf_by_channel.setdefault(ch, []).append((open_rate, click_rate))
        perf_by_neighborhood.setdefault(nb, []).append((ch, open_rate, click_rate))
        channels_in_perf.add(ch)
        neighborhoods_in_perf.add(nb)

    expected_stats_by_channel = {}
    if perf_ok and perf_by_channel:
        for ch, lst in perf_by_channel.items():
            if lst:
                avg_open = sum(x for x, _ in lst) / len(lst)
                avg_click = sum(y for _, y in lst) / len(lst)
                expected_stats_by_channel[ch] = (_round4(avg_open), _round4(avg_click))

    expected_stats_by_neighborhood = {}
    expected_top_channel_by_nb = {}
    if perf_ok and perf_by_neighborhood:
        for nb, lst in perf_by_neighborhood.items():
            if lst:
                avg_open = sum(x for _, x, _ in lst) / len(lst)
                avg_click = sum(y for _, _, y in lst) / len(lst)
                expected_stats_by_neighborhood[nb] = (_round4(avg_open), _round4(avg_click))
                # Determine top channel by click rate; ties go to Email
                # Build dict ch -> click_rate
                click_map = {ch: clk for (ch, _, clk) in lst}
                # There should be exactly two channels per neighborhood in given input
                sms_clk = click_map.get("SMS", -1.0)
                email_clk = click_map.get("Email", -1.0)
                top = "Email" if (email_clk >= sms_clk) else "SMS"
                expected_top_channel_by_nb[nb] = top

    # Load rewritten messages output
    rewritten_path = workspace / "output" / "rewritten_messages.csv"
    rewritten_rows, rewritten_header, _ = _safe_read_csv(rewritten_path)
    expected_rewritten_header = [
        "id",
        "neighborhood",
        "channel",
        "original_message",
        "rewritten_subject",
        "rewritten_message",
        "rewritten_char_count",
        "rewritten_word_count",
        "contains_business_name_placeholder",
        "contains_neighborhood_name",
        "jargon_terms_removed",
        "cta_present",
    ]

    # Structure checks: existence, header exact, row count equals input count
    structure_ok = False
    if rewritten_rows and _header_equals(rewritten_header, expected_rewritten_header) and msgs_in_rows:
        if len(rewritten_rows) == len(msgs_in_rows):
            # Ensure id sets match
            in_ids = set(r["id"] for r in msgs_in_rows if "id" in r)
            out_ids = set(r["id"] for r in rewritten_rows if "id" in r)
            if in_ids == out_ids:
                structure_ok = True
    scores["rewritten_messages_structure"] = 1.0 if structure_ok else 0.0

    # Validate original_message matches input and id/neighborhood/channel mapping
    original_ok = False
    if structure_ok:
        ok = True
        for r in rewritten_rows:
            rid = r["id"]
            inp = msgs_by_id.get(rid)
            if not inp:
                ok = False
                break
            if r.get("neighborhood") != inp.get("neighborhood"):
                ok = False
                break
            if r.get("channel") != inp.get("channel"):
                ok = False
                break
            if r.get("original_message") != inp.get("message"):
                ok = False
                break
        original_ok = ok
    scores["original_message_match"] = 1.0 if original_ok else 0.0

    # Validate jargon removed, counts, flags; and SMS/Email specific constraints
    jargon_and_counts_ok = False
    sms_ok = False
    email_subject_ok = False
    email_body_ok = False
    if structure_ok and original_ok:
        jc_ok = True
        sms_all_ok = True
        es_ok = True
        eb_ok = True
        for r in rewritten_rows:
            rid = r["id"]
            nb = r["neighborhood"]
            ch = r["channel"]
            orig = r["original_message"]
            rew_subject = r.get("rewritten_subject", "")
            rew_msg = r.get("rewritten_message", "")

            # Check counts
            # rewritten_char_count
            try:
                reported_char_count = int(r.get("rewritten_char_count", "").strip())
                reported_word_count = int(r.get("rewritten_word_count", "").strip())
            except Exception:
                jc_ok = False
                # don't break; continue to collect all failures
                reported_char_count = None
                reported_word_count = None
            actual_char_count = len(rew_msg)
            actual_word_count = _count_words(rew_msg)
            if reported_char_count is None or reported_char_count != actual_char_count:
                jc_ok = False
            if reported_word_count is None or reported_word_count != actual_word_count:
                jc_ok = False

            # Flags
            cta_present_field = r.get("cta_present", "")
            contains_nb_field = r.get("contains_neighborhood_name", "")
            contains_bn_field = r.get("contains_business_name_placeholder", "")
            cta_present_bool = _parse_bool_str(cta_present_field)
            contains_nb_bool = _parse_bool_str(contains_nb_field)
            contains_bn_bool = _parse_bool_str(contains_bn_field)
            if cta_present_bool is None or contains_nb_bool is None or contains_bn_bool is None:
                jc_ok = False

            actual_contains_nb = nb in (rew_msg or "")
            actual_contains_bn = "{BusinessName}" in (rew_msg or "")
            actual_cta_present = "CTA:" in (rew_msg or "")

            if contains_nb_bool is not None and contains_nb_bool != actual_contains_nb:
                jc_ok = False
            if contains_bn_bool is not None and contains_bn_bool != actual_contains_bn:
                jc_ok = False
            if cta_present_bool is not None and cta_present_bool != actual_cta_present:
                jc_ok = False

            # Jargon removal list and absence in subject/body
            expected_removed = _terms_in_text(orig or "", jargon_terms)
            # Join expected removed in the order of jargon_terms encountered (already done)
            expected_removed_str = ";".join(expected_removed)
            provided_removed_str = r.get("jargon_terms_removed", "")
            if (provided_removed_str or "") != expected_removed_str:
                jc_ok = False

            # Ensure none of jargon terms appear in rewritten subject or message
            for term in jargon_terms:
                if _contains_term(rew_msg or "", term) or _contains_term(rew_subject or "", term):
                    jc_ok = False
                    break

            # Channel-specific checks
            if ch == "SMS":
                # Subject should be empty
                if rew_subject.strip() != "":
                    sms_all_ok = False
                # Message <= 160 chars
                if len(rew_msg) > 160:
                    sms_all_ok = False
                # Must include {BusinessName} unchanged and neighborhood verbatim
                if "{BusinessName}" not in (rew_msg or ""):
                    sms_all_ok = False
                if nb not in (rew_msg or ""):
                    sms_all_ok = False
                # CTA exactly once and near the end (define near as starting in last 40% of chars)
                cta_count = (rew_msg or "").count("CTA:")
                if cta_count != 1:
                    sms_all_ok = False
                else:
                    start_idx = (rew_msg or "").find("CTA:")
                    if start_idx < 0:
                        sms_all_ok = False
                    else:
                        if len(rew_msg) > 0:
                            if start_idx < math.floor(0.6 * len(rew_msg)):
                                # Not near the end
                                sms_all_ok = False
                        # Ensure CTA has some actionable text following
                        after = (rew_msg or "")[start_idx + len("CTA:"):].strip()
                        if len(after) == 0 or not any(c.isalpha() for c in after):
                            sms_all_ok = False
            elif ch == "Email":
                # Subject constraints: non-empty, <=60 chars, includes neighborhood, no jargon
                if not rew_subject or len(rew_subject) > 60:
                    es_ok = False
                if nb not in (rew_subject or ""):
                    es_ok = False
                for term in jargon_terms:
                    if _contains_term(rew_subject or "", term):
                        es_ok = False
                        break
                # Body constraints: <=120 words, includes neighborhood and {BusinessName}
                if _count_words(rew_msg or "") > 120:
                    eb_ok = False
                if nb not in (rew_msg or ""):
                    eb_ok = False
                if "{BusinessName}" not in (rew_msg or ""):
                    eb_ok = False
                # Exactly one line starting with "CTA:" and exactly one "CTA:" occurrence
                lines = (rew_msg or "").splitlines()
                cta_line_count = sum(1 for ln in lines if ln.strip().startswith("CTA:"))
                total_cta_occ = (rew_msg or "").count("CTA:")
                if cta_line_count != 1 or total_cta_occ != 1:
                    eb_ok = False
            else:
                # Unknown channel present -> fail all related checks
                sms_all_ok = False
                es_ok = False
                eb_ok = False

        jargon_and_counts_ok = jc_ok
        sms_ok = sms_all_ok
        email_subject_ok = es_ok
        email_body_ok = eb_ok

    scores["rewritten_messages_jargon_and_flags_and_counts"] = 1.0 if jargon_and_counts_ok else 0.0
    scores["rewritten_messages_content_constraints_sms"] = 1.0 if sms_ok else 0.0
    scores["rewritten_messages_content_constraints_email_subject"] = 1.0 if email_subject_ok else 0.0
    scores["rewritten_messages_content_constraints_email_body"] = 1.0 if email_body_ok else 0.0

    # stats_by_channel.csv checks
    stats_ch_path = workspace / "output" / "stats_by_channel.csv"
    stats_ch_rows, stats_ch_header, _ = _safe_read_csv(stats_ch_path)
    expected_stats_ch_header = ["channel", "avg_open_rate", "avg_click_rate", "original_avg_char_count", "rewritten_avg_char_count"]

    stats_by_channel_ok = False
    if stats_ch_rows and _header_equals(stats_ch_header, expected_stats_ch_header) and msgs_in_rows and perf_ok and rewritten_rows:
        # Compute expected char counts
        # Original avg char count by channel (from input/messages.csv, message field)
        orig_char_counts = {}
        orig_counts = {}
        for r in msgs_in_rows:
            ch = r["channel"]
            msg = r["message"] or ""
            orig_char_counts[ch] = orig_char_counts.get(ch, 0) + len(msg)
            orig_counts[ch] = orig_counts.get(ch, 0) + 1
        orig_avg_char = {}
        for ch in orig_char_counts:
            if orig_counts.get(ch, 0) > 0:
                orig_avg_char[ch] = orig_char_counts[ch] / orig_counts[ch]

        # Rewritten avg char count by channel (from rewritten rows)
        rew_char_counts = {}
        rew_counts = {}
        for r in rewritten_rows:
            ch = r["channel"]
            msg = r.get("rewritten_message", "") or ""
            rew_char_counts[ch] = rew_char_counts.get(ch, 0) + len(msg)
            rew_counts[ch] = rew_counts.get(ch, 0) + 1
        rew_avg_char = {}
        for ch in rew_char_counts:
            if rew_counts.get(ch, 0) > 0:
                rew_avg_char[ch] = rew_char_counts[ch] / rew_counts[ch]

        # Validate each row
        ok = True
        # Build map from channel -> row
        out_map = {r["channel"]: r for r in stats_ch_rows if "channel" in r}
        # Expect channels in performance
        if set(out_map.keys()) != channels_in_perf:
            ok = False
        for ch in channels_in_perf:
            row = out_map.get(ch)
            if not row:
                ok = False
                break
            # avg_open_rate and avg_click_rate rounded to 4 decimals
            if not (_is_float(row.get("avg_open_rate", "")) and _is_float(row.get("avg_click_rate", ""))):
                ok = False
                break
            got_open = float(row["avg_open_rate"])
            got_click = float(row["avg_click_rate"])
            exp_open, exp_click = expected_stats_by_channel.get(ch, (None, None))
            if exp_open is None or exp_click is None:
                ok = False
                break
            if not _float_eq(got_open, exp_open, tol=1e-4) or not _float_eq(got_click, exp_click, tol=1e-4):
                ok = False
                break
            # char counts: allow small tolerance due to potential rounding variations
            if not _is_float(row.get("original_avg_char_count", "")) or not _is_float(row.get("rewritten_avg_char_count", "")):
                ok = False
                break
            got_oacc = float(row["original_avg_char_count"])
            got_racc = float(row["rewritten_avg_char_count"])
            exp_oacc = orig_avg_char.get(ch)
            exp_racc = rew_avg_char.get(ch)
            if exp_oacc is None or exp_racc is None:
                ok = False
                break
            # Accept within 0.5 chars tolerance
            if not _float_eq(got_oacc, exp_oacc, tol=0.5):
                ok = False
                break
            if not _float_eq(got_racc, exp_racc, tol=0.5):
                ok = False
                break
        stats_by_channel_ok = ok
    scores["stats_by_channel_correct"] = 1.0 if stats_by_channel_ok else 0.0

    # stats_by_neighborhood.csv checks
    stats_nb_path = workspace / "output" / "stats_by_neighborhood.csv"
    stats_nb_rows, stats_nb_header, _ = _safe_read_csv(stats_nb_path)
    expected_stats_nb_header = ["neighborhood", "avg_open_rate", "avg_click_rate", "top_channel_by_click_rate"]

    stats_by_neighborhood_ok = False
    if stats_nb_rows and _header_equals(stats_nb_header, expected_stats_nb_header) and perf_ok:
        ok = True
        out_map = {r["neighborhood"]: r for r in stats_nb_rows if "neighborhood" in r}
        if set(out_map.keys()) != neighborhoods_in_perf:
            ok = False
        else:
            for nb in neighborhoods_in_perf:
                row = out_map.get(nb)
                if not row:
                    ok = False
                    break
                if not (_is_float(row.get("avg_open_rate", "")) and _is_float(row.get("avg_click_rate", ""))):
                    ok = False
                    break
                got_open = float(row["avg_open_rate"])
                got_click = float(row["avg_click_rate"])
                exp_open, exp_click = expected_stats_by_neighborhood.get(nb, (None, None))
                if exp_open is None or exp_click is None:
                    ok = False
                    break
                if not _float_eq(got_open, exp_open, tol=1e-4) or not _float_eq(got_click, exp_click, tol=1e-4):
                    ok = False
                    break
                # top channel tie-breaking
                if row.get("top_channel_by_click_rate") != expected_top_channel_by_nb.get(nb):
                    ok = False
                    break
        stats_by_neighborhood_ok = ok
    scores["stats_by_neighborhood_correct"] = 1.0 if stats_by_neighborhood_ok else 0.0

    # content_calendar.csv checks
    calendar_path = workspace / "output" / "content_calendar.csv"
    cal_rows, cal_header, _ = _safe_read_csv(calendar_path)
    expected_cal_header = ["week_number", "neighborhood", "channel", "message_id", "subject_if_email", "scheduled_day_of_week"]

    calendar_ok = False
    if cal_rows and _header_equals(cal_header, expected_cal_header) and perf_ok and rewritten_rows:
        ok = True
        # Expected row count: 4 weeks * number of neighborhoods
        expected_rows = 4 * len(neighborhoods_in_perf) if neighborhoods_in_perf else 0
        if expected_rows == 0 or len(cal_rows) != expected_rows:
            ok = False
        else:
            # Build mapping of rewritten rows by (neighborhood, channel) preserving order
            rew_by_nb_ch: Dict[Tuple[str, str], List[Dict[str, str]]] = {}
            rew_by_id: Dict[str, Dict[str, str]] = {}
            for r in rewritten_rows:
                key = (r["neighborhood"], r["channel"])
                rew_by_nb_ch.setdefault(key, []).append(r)
                rew_by_id[r["id"]] = r

            # For deterministic order, keep the list as encountered
            # Validate each neighborhood has its top channel rows available
            for nb in neighborhoods_in_perf:
                top_ch = expected_top_channel_by_nb.get(nb)
                key = (nb, top_ch)
                msgs_for_combo = rew_by_nb_ch.get(key, [])
                if len(msgs_for_combo) == 0:
                    ok = False
                    break

            # Build expected schedule map: (week_number, neighborhood) -> expected (channel, message_id, subject_if_email)
            # Rotation over messages list in encountered order
            expected_entries = {}
            for nb in neighborhoods_in_perf:
                top_ch = expected_top_channel_by_nb.get(nb)
                msgs_for_combo = rew_by_nb_ch.get((nb, top_ch), [])
                msg_ids = [m["id"] for m in msgs_for_combo]
                for wk in range(1, 5):
                    idx = (wk - 1) % len(msg_ids)
                    mid = msg_ids[idx]
                    subj = rew_by_id[mid].get("rewritten_subject", "") if top_ch == "Email" else ""
                    expected_entries[(wk, nb)] = (top_ch, mid, subj)

            # Validate calendar rows content
            seen_keys = set()
            for r in cal_rows:
                # week_number must be 1..4, scheduled_day_of_week Monday
                wk_str = r.get("week_number", "")
                if not wk_str.isdigit():
                    ok = False
                    break
                wk = int(wk_str)
                if wk < 1 or wk > 4:
                    ok = False
                    break
                if r.get("scheduled_day_of_week") != "Monday":
                    ok = False
                    break
                nb = r.get("neighborhood", "")
                ch = r.get("channel", "")
                mid = r.get("message_id", "")
                subj = r.get("subject_if_email", "")
                key = (wk, nb)
                if key in seen_keys:
                    ok = False
                    break
                seen_keys.add(key)
                exp = expected_entries.get(key)
                if not exp:
                    ok = False
                    break
                exp_ch, exp_mid, exp_subj = exp
                if ch != exp_ch or mid != exp_mid:
                    ok = False
                    break
                # Validate subject_if_email population rule
                if ch == "Email":
                    if subj != exp_subj:
                        ok = False
                        break
                else:
                    if subj != "":
                        ok = False
                        break

            # Also ensure every (wk, nb) pair exists exactly once
            if ok:
                if seen_keys != set((wk, nb) for nb in neighborhoods_in_perf for wk in range(1, 5)):
                    ok = False

        calendar_ok = ok

    scores["content_calendar_correct"] = 1.0 if calendar_ok else 0.0

    return scores


def main() -> None:
        workspace = "."
        if len(sys.argv) >= 2 and sys.argv[1]:
            workspace = sys.argv[1]
        result = grade([], workspace)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()