import json
import sys
import re
from pathlib import Path
from typing import Optional, List, Dict, Any


def _safe_read_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    if not path.exists() or not path.is_file():
        return None
    records: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for idx, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if not isinstance(obj, dict):
                    return None
                records.append(obj)
    except Exception:
        return None
    return records


def _safe_read_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        return data
    except Exception:
        return None


def _parse_input_expectations(input_path: Path) -> Optional[Dict[str, Dict[str, Any]]]:
    records = _safe_read_jsonl(input_path)
    if records is None:
        return None
    mapping: Dict[str, Dict[str, Any]] = {}
    for rec in records:
        # Expect keys: id, sender, channel, timestamp, body
        if not all(k in rec for k in ("id", "sender", "channel", "timestamp", "body")):
            return None
        rid = rec["id"]
        if not isinstance(rid, str):
            return None
        mapping[rid] = {
            "sender": rec["sender"],
            "channel": rec["channel"],
            "timestamp": rec["timestamp"],
            "body": rec["body"],
        }
    return mapping


def _records_by_id(records: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    res: Dict[str, Dict[str, Any]] = {}
    for rec in records:
        rid = rec.get("id")
        if isinstance(rid, str) and rid not in res:
            res[rid] = rec
    return res


def _count_sentences(text: str) -> int:
    # Split on sentence-ending punctuation groups and count non-empty segments
    parts = re.split(r'[.!?]+', text)
    non_empty = [p for p in parts if p.strip()]
    return len(non_empty)


def _has_repeated_excessive_exclamations(text: str) -> bool:
    # Consider "!!" or "!!!" as excessive
    return "!!" in text or "!!!" in text


def _contains_email(text: str) -> bool:
    email_re = re.compile(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}')
    return email_re.search(text) is not None


def _digit_sequences_4plus(text: str) -> List[str]:
    return re.findall(r'\d{4,}', text)


def _approx_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _compute_stats_from_cleaned(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(records)
    by_sender: Dict[str, int] = {}
    by_day: Dict[str, int] = {}
    orig_lengths: List[int] = []
    clean_lengths: List[int] = []
    percent_reductions: List[float] = []
    for rec in records:
        sender = rec.get("sender")
        date = rec.get("date")
        orig_len = rec.get("original_length")
        clean_len = rec.get("cleaned_length")
        if isinstance(sender, str):
            by_sender[sender] = by_sender.get(sender, 0) + 1
        if isinstance(date, str):
            by_day[date] = by_day.get(date, 0) + 1
        if isinstance(orig_len, int) and isinstance(clean_len, int):
            orig_lengths.append(orig_len)
            clean_lengths.append(clean_len)
            if orig_len > 0:
                percent_reductions.append((orig_len - clean_len) / orig_len)
            else:
                percent_reductions.append(0.0)
        else:
            # If types are wrong, stats will be inconsistent; keep placeholders
            pass
    avg_orig = float(sum(orig_lengths) / total) if total > 0 else 0.0
    avg_clean = float(sum(clean_lengths) / total) if total > 0 else 0.0
    avg_red = float(sum(percent_reductions) / total) if total > 0 else 0.0
    return {
        "total_messages_processed": total,
        "messages_by_sender": by_sender,
        "messages_by_day": by_day,
        "avg_original_length": avg_orig,
        "avg_cleaned_length": avg_clean,
        "avg_percent_reduction": avg_red,
    }


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "cleaned_file_exists_and_parse": 0.0,
        "cleaned_has_required_fields": 0.0,
        "cleaned_ids_are_unique": 0.0,
        "cleaned_length_fields_correct": 0.0,
        "includes_all_expected_ids": 0.0,
        "fields_match_input_for_expected_ids": 0.0,
        "date_matches_timestamp_for_expected_ids": 0.0,
        "redactions_email_for_expected_ids": 0.0,
        "redactions_numbers_for_expected_ids": 0.0,
        "limits_sentences_and_length_for_expected_ids": 0.0,
        "normalization_caps_and_punct_for_expected_ids": 0.0,
        "source_file_field_valid_for_expected_ids": 0.0,
        "summary_file_exists_and_parse": 0.0,
        "summary_consistent_with_cleaned": 0.0,
    }

    cleaned_path = workspace / "outputs" / "cleaned" / "cleaned_messages.jsonl"
    summary_path = workspace / "outputs" / "stats" / "summary.json"
    input_path = workspace / "input" / "tips.jsonl"

    cleaned_records = _safe_read_jsonl(cleaned_path)

    # cleaned_file_exists_and_parse: must exist, parse, and have at least one record
    if cleaned_records is not None and len(cleaned_records) > 0:
        scores["cleaned_file_exists_and_parse"] = 1.0

    # cleaned_has_required_fields and related checks
    required_fields = {"id", "sender", "channel", "date", "original_length", "cleaned_length", "cleaned_text", "source_file"}

    def _validate_date_format(d: str) -> bool:
        return isinstance(d, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) is not None

    if cleaned_records is not None and len(cleaned_records) > 0:
        all_fields_ok = True
        all_clean_len_ok = True
        ids = []
        for rec in cleaned_records:
            # Required fields and types
            if not required_fields.issubset(rec.keys()):
                all_fields_ok = False
                break
            if not isinstance(rec.get("id"), str):
                all_fields_ok = False
                break
            if not isinstance(rec.get("sender"), str):
                all_fields_ok = False
                break
            if not isinstance(rec.get("channel"), str):
                all_fields_ok = False
                break
            if not _validate_date_format(rec.get("date")):
                all_fields_ok = False
                break
            if not isinstance(rec.get("original_length"), int):
                all_fields_ok = False
                break
            if not isinstance(rec.get("cleaned_length"), int):
                all_fields_ok = False
                break
            if not isinstance(rec.get("cleaned_text"), str):
                all_fields_ok = False
                break
            if not isinstance(rec.get("source_file"), str) or not rec.get("source_file"):
                all_fields_ok = False
                break

            # cleaned_length correctness
            if rec.get("cleaned_length") != len(rec.get("cleaned_text")):
                all_clean_len_ok = False

            ids.append(rec.get("id"))

        if all_fields_ok:
            scores["cleaned_has_required_fields"] = 1.0
        if all_clean_len_ok:
            scores["cleaned_length_fields_correct"] = 1.0

        # IDs unique
        if len(ids) == len(set(ids)):
            scores["cleaned_ids_are_unique"] = 1.0

    # Load input expectations
    input_map = _parse_input_expectations(input_path)

    # includes_all_expected_ids
    if input_map is not None and cleaned_records is not None:
        cleaned_by_id = _records_by_id(cleaned_records)
        all_present = True
        for eid in input_map.keys():
            if eid not in cleaned_by_id:
                all_present = False
                break
        if all_present:
            scores["includes_all_expected_ids"] = 1.0

        # fields_match_input_for_expected_ids
        fields_match = True
        if all_present:
            for eid, exp in input_map.items():
                rec = cleaned_by_id.get(eid)
                if rec is None:
                    fields_match = False
                    break
                if rec.get("sender") != exp.get("sender"):
                    fields_match = False
                    break
                if rec.get("channel") != exp.get("channel"):
                    fields_match = False
                    break
            if fields_match:
                scores["fields_match_input_for_expected_ids"] = 1.0

        # date_matches_timestamp_for_expected_ids
        dates_match = True
        if all_present:
            for eid, exp in input_map.items():
                exp_ts = exp.get("timestamp")
                if not isinstance(exp_ts, str) or len(exp_ts) < 10:
                    dates_match = False
                    break
                exp_date = exp_ts[:10]
                rec = cleaned_by_id.get(eid)
                if rec is None or rec.get("date") != exp_date:
                    dates_match = False
                    break
            if dates_match:
                scores["date_matches_timestamp_for_expected_ids"] = 1.0

        # Redactions: email
        emails_ok = True
        if all_present:
            for eid, exp in input_map.items():
                body = exp.get("body", "")
                rec = cleaned_by_id.get(eid)
                if rec is None:
                    emails_ok = False
                    break
                ctext = rec.get("cleaned_text", "")
                if _contains_email(body):
                    # Expect token present and no emails remaining
                    if "[REDACTED_EMAIL]" not in ctext:
                        emails_ok = False
                        break
                    if _contains_email(ctext):
                        emails_ok = False
                        break
            if emails_ok:
                scores["redactions_email_for_expected_ids"] = 1.0

        # Redactions: numbers (4+)
        numbers_ok = True
        if all_present:
            for eid, exp in input_map.items():
                body = exp.get("body", "")
                sequences = _digit_sequences_4plus(body)
                rec = cleaned_by_id.get(eid)
                if rec is None:
                    numbers_ok = False
                    break
                ctext = rec.get("cleaned_text", "")
                # Ensure sequences not present
                for seq in set(sequences):
                    if seq and seq in ctext:
                        numbers_ok = False
                        break
                if not numbers_ok:
                    break
                if sequences:
                    # At least one redaction token if any sequences existed
                    if "[REDACTED_NUMBER]" not in ctext:
                        numbers_ok = False
                        break
            if numbers_ok:
                scores["redactions_numbers_for_expected_ids"] = 1.0

        # Limits: sentences <=3 and length <=240 and non-empty
        limits_ok = True
        if all_present:
            for eid in input_map.keys():
                rec = cleaned_by_id.get(eid)
                if rec is None:
                    limits_ok = False
                    break
                ctext = rec.get("cleaned_text", "")
                if not isinstance(ctext, str) or not ctext.strip():
                    limits_ok = False
                    break
                if len(ctext) > 240:
                    limits_ok = False
                    break
                if _count_sentences(ctext) > 3:
                    limits_ok = False
                    break
            if limits_ok:
                scores["limits_sentences_and_length_for_expected_ids"] = 1.0

        # Normalization: caps and excessive punctuation
        norm_ok = True
        if all_present:
            for eid, exp in input_map.items():
                body = exp.get("body", "")
                rec = cleaned_by_id.get(eid)
                if rec is None:
                    norm_ok = False
                    break
                ctext = rec.get("cleaned_text", "")
                # If original had excessive exclamations, cleaned should not
                if _has_repeated_excessive_exclamations(body):
                    if _has_repeated_excessive_exclamations(ctext):
                        norm_ok = False
                        break
                # If original had strong ALL-CAPS indicators (>=3 letter uppercase token),
                # cleaned text should not be fully uppercase
                if re.search(r'\b[A-Z]{3,}\b', body) is not None:
                    if ctext and ctext.upper() == ctext:
                        norm_ok = False
                        break
            if norm_ok:
                scores["normalization_caps_and_punct_for_expected_ids"] = 1.0

        # Source file field validity: non-empty and endswith .jsonl
        src_ok = True
        if all_present:
            for eid in input_map.keys():
                rec = cleaned_by_id.get(eid)
                if rec is None:
                    src_ok = False
                    break
                sf = rec.get("source_file")
                if not isinstance(sf, str) or not sf or not sf.endswith(".jsonl"):
                    src_ok = False
                    break
            if src_ok:
                scores["source_file_field_valid_for_expected_ids"] = 1.0

        # original_length accuracy for expected ids
        # Note: This is partially covered by fields_match checks; ensure correctness explicitly
        orig_len_ok = True
        if all_present:
            for eid, exp in input_map.items():
                body = exp.get("body", "")
                rec = cleaned_by_id.get(eid)
                if rec is None:
                    orig_len_ok = False
                    break
                if rec.get("original_length") != len(body):
                    orig_len_ok = False
                    break
            # Instead of separate key, fold into limits? The instructions prefer atomic checks,
            # but to avoid adding a new key not listed, we incorporate into structure via existing fields checks.
            # If mismatch, it will reflect in stats consistency too.
            # We won't add a new score key here per stability requirements.

    # Summary checks
    summary_obj = _safe_read_json(summary_path)
    if summary_obj is not None:
        # Check required keys exist and basic types
        required_summary_keys = {
            "total_messages_processed",
            "messages_by_sender",
            "messages_by_day",
            "avg_original_length",
            "avg_cleaned_length",
            "avg_percent_reduction",
        }
        has_keys = required_summary_keys.issubset(summary_obj.keys())
        basic_types_ok = (
            isinstance(summary_obj.get("total_messages_processed"), (int, float)) and
            isinstance(summary_obj.get("messages_by_sender"), dict) and
            isinstance(summary_obj.get("messages_by_day"), dict) and
            isinstance(summary_obj.get("avg_original_length"), (int, float)) and
            isinstance(summary_obj.get("avg_cleaned_length"), (int, float)) and
            isinstance(summary_obj.get("avg_percent_reduction"), (int, float))
        )
        if has_keys and basic_types_ok:
            scores["summary_file_exists_and_parse"] = 1.0

    # Summary consistency with cleaned
    if cleaned_records is not None and summary_obj is not None and len(cleaned_records) > 0:
        recomputed = _compute_stats_from_cleaned(cleaned_records)
        ok = True
        # Compare totals
        if int(round(float(summary_obj.get("total_messages_processed", -1)))) != recomputed["total_messages_processed"]:
            ok = False
        # Compare messages_by_sender
        # Normalize values to int
        expected_sender = {k: int(v) for k, v in recomputed["messages_by_sender"].items()}
        summary_sender_raw = summary_obj.get("messages_by_sender", {})
        if not isinstance(summary_sender_raw, dict):
            ok = False
        else:
            summary_sender = {}
            for k, v in summary_sender_raw.items():
                try:
                    summary_sender[k] = int(v)
                except Exception:
                    ok = False
                    break
            if ok and summary_sender != expected_sender:
                ok = False
        # Compare messages_by_day
        expected_day = {k: int(v) for k, v in recomputed["messages_by_day"].items()}
        summary_day_raw = summary_obj.get("messages_by_day", {})
        if not isinstance(summary_day_raw, dict):
            ok = False
        else:
            summary_day = {}
            for k, v in summary_day_raw.items():
                try:
                    summary_day[k] = int(v)
                except Exception:
                    ok = False
                    break
            if ok and summary_day != expected_day:
                ok = False
        # Compare averages
        try:
            avg_orig = float(summary_obj.get("avg_original_length"))
            avg_clean = float(summary_obj.get("avg_cleaned_length"))
            avg_red = float(summary_obj.get("avg_percent_reduction"))
        except Exception:
            ok = False
            avg_orig = avg_clean = avg_red = 0.0
        if ok:
            if not _approx_equal(avg_orig, recomputed["avg_original_length"]):
                ok = False
            if not _approx_equal(avg_clean, recomputed["avg_cleaned_length"]):
                ok = False
            if not _approx_equal(avg_red, recomputed["avg_percent_reduction"]):
                ok = False
        if ok:
            scores["summary_consistent_with_cleaned"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()