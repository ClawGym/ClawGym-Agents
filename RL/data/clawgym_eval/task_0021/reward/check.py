import json
import sys
import re
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        txt = _read_text(path)
        if txt is None:
            return None
        return json.loads(txt)
    except Exception:
        return None


def _read_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        lines: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if not isinstance(obj, dict):
                    return None
                lines.append(obj)
        return lines
    except Exception:
        return None


def _parse_iso_z(ts: str) -> Optional[datetime]:
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


def _compute_metrics(records: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    try:
        total = len(records)
        if total == 0:
            return {
                "total_tickets": 0,
                "tickets_by_severity": {},
                "avg_message_length_chars": 0.0,
                "avg_message_length_words": 0.0,
                "earliest_created_at": None,
                "latest_created_at": None,
                "unique_reporters": 0,
            }
        severities: Dict[str, int] = {}
        char_sum = 0
        word_sum = 0
        reporters = set()
        times: List[datetime] = []
        for r in records:
            sev = r.get("severity")
            msg = r.get("message")
            created = r.get("created_at")
            rep = r.get("reporter")
            if not isinstance(sev, str) or not isinstance(msg, str) or not isinstance(created, str) or not isinstance(rep, str):
                return None
            severities[sev] = severities.get(sev, 0) + 1
            char_sum += len(msg)
            word_sum += len(msg.split())
            reporters.add(rep)
            dt = _parse_iso_z(created)
            if dt is None:
                return None
            times.append(dt)
        times_sorted = sorted(times)
        earliest = times_sorted[0].strftime("%Y-%m-%dT%H:%M:%SZ")
        latest = times_sorted[-1].strftime("%Y-%m-%dT%H:%M:%SZ")
        avg_chars = char_sum / total
        avg_words = word_sum / total
        return {
            "total_tickets": total,
            "tickets_by_severity": severities,
            "avg_message_length_chars": avg_chars,
            "avg_message_length_words": avg_words,
            "earliest_created_at": earliest,
            "latest_created_at": latest,
            "unique_reporters": len(reporters),
        }
    except Exception:
        return None


def _float_equal(a: Any, b: Any, tol: float = 1e-9) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def _validate_rewrites_structure_alignment(
    input_records: List[Dict[str, Any]], rewrite_records: List[Dict[str, Any]]
) -> bool:
    try:
        required_keys = {"id", "severity", "reporter", "created_at", "original_message", "rewritten_message"}
        if len(rewrite_records) != len(input_records):
            return False
        input_by_id: Dict[str, Dict[str, Any]] = {}
        for r in input_records:
            rid = r.get("id")
            if not isinstance(rid, str):
                return False
            input_by_id[rid] = r
        seen_ids = set()
        for rr in rewrite_records:
            keys = set(rr.keys())
            if keys != required_keys:
                return False
            rid = rr.get("id")
            if not isinstance(rid, str) or rid not in input_by_id:
                return False
            if rid in seen_ids:
                return False
            seen_ids.add(rid)
            src = input_by_id[rid]
            if rr.get("severity") != src.get("severity"):
                return False
            if rr.get("reporter") != src.get("reporter"):
                return False
            if rr.get("created_at") != src.get("created_at"):
                return False
            if rr.get("original_message") != src.get("message"):
                return False
            if not isinstance(rr.get("rewritten_message"), str):
                return False
        if set(input_by_id.keys()) != seen_ids:
            return False
        return True
    except Exception:
        return False


def _validate_rewrites_quality(
    rewrite_records: List[Dict[str, Any]]
) -> bool:
    try:
        for rr in rewrite_records:
            rw = rr.get("rewritten_message", "")
            if not isinstance(rw, str):
                return False
            if len(rw) > 140:
                return False
        by_id = {r.get("id"): r for r in rewrite_records if isinstance(r.get("id"), str)}
        if "T-1004" in by_id:
            rw = by_id["T-1004"]["rewritten_message"]
            if re.search(r"stack trace", rw, flags=re.IGNORECASE):
                return False
            if "!!!" in rw:
                return False
            if "AFFECTING PAYMENTS" in rw:
                return False
            if "500" not in rw:
                return False
            if not (re.search(r"\bapi\b", rw, flags=re.IGNORECASE) or re.search(r"payment", rw, flags=re.IGNORECASE)):
                return False
        if "T-1008" in by_id:
            rw8 = by_id["T-1008"]["rewritten_message"]
            if "WARNING" in rw8:
                return False
        return True
    except Exception:
        return False


def _validate_notification(
    notif_text: str,
    metrics: Dict[str, Any],
) -> bool:
    try:
        text = notif_text.strip("\n")
        if "\n" in text:
            return False
        if len(text) > 200:
            return False
        total = metrics.get("total_tickets")
        if not isinstance(total, int):
            return False
        if str(total) not in text:
            return False
        sev_counts = metrics.get("tickets_by_severity")
        if not isinstance(sev_counts, dict):
            return False
        for sev, cnt in sev_counts.items():
            if re.search(rf"\b{re.escape(sev)}\b", text, flags=re.IGNORECASE) is None:
                return False
            if str(cnt) not in text:
                return False
        earliest = metrics.get("earliest_created_at")
        latest = metrics.get("latest_created_at")
        if not (isinstance(earliest, str) and isinstance(latest, str)):
            return False
        if (earliest not in text) or (latest not in text):
            return False
        return True
    except Exception:
        return False


def _parse_processed_state(path: Path) -> Tuple[bool, Dict[str, str]]:
    data = _load_json(path)
    if not isinstance(data, list):
        return False, {}
    mapping: Dict[str, str] = {}
    for item in data:
        if not isinstance(item, dict):
            return False, {}
        bn = item.get("basename")
        pa = item.get("processed_at")
        if not isinstance(bn, str) or not isinstance(pa, str):
            return False, {}
        if bn in mapping:
            return False, {}
        if _parse_iso_z(pa) is None:
            return False, {}
        mapping[bn] = pa
    return True, mapping


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "rewrites_exists_2026_04_15": 0.0,
        "rewrites_structure_alignment_2026_04_15": 0.0,
        "rewrites_quality_constraints_2026_04_15": 0.0,
        "metrics_exists_and_keys_2026_04_15": 0.0,
        "metrics_values_correct_2026_04_15": 0.0,
        "notification_exists_and_content_2026_04_15": 0.0,
        "state_includes_batch_2026_04_15": 0.0,
        "rewrites_exists_2026_04_16": 0.0,
        "rewrites_structure_alignment_2026_04_16": 0.0,
        "rewrites_quality_constraints_2026_04_16": 0.0,
        "metrics_exists_and_keys_2026_04_16": 0.0,
        "metrics_values_correct_2026_04_16": 0.0,
        "notification_exists_and_content_2026_04_16": 0.0,
        "state_includes_batch_2026_04_16": 0.0,
        "state_file_structure_valid": 0.0,
    }

    batches = [
        ("2026-04-15_support_tickets", "input/inbox/2026-04-15_support_tickets.jsonl"),
        ("2026-04-16_support_tickets", "input/inbox/2026-04-16_support_tickets.jsonl"),
    ]

    state_path = workspace / "out/state/processed_batches.json"
    state_ok, state_map = (False, {})
    if state_path.exists():
        state_ok, state_map = _parse_processed_state(state_path)
    scores["state_file_structure_valid"] = 1.0 if state_ok else 0.0

    for base, in_rel in batches:
        suffix = "2026_04_15" if "04-15" in base else "2026_04_16"

        input_path = workspace / in_rel
        input_records = _read_jsonl(input_path) if input_path.exists() else None

        rewrites_path = workspace / f"out/rewritten/{base}.rewrites.jsonl"
        metrics_path = workspace / f"out/metrics/{base}.summary.json"
        notif_path = workspace / f"out/notifications/{base}.team_update.txt"

        if rewrites_path.exists():
            scores[f"rewrites_exists_{suffix}"] = 1.0

        if input_records is not None and rewrites_path.exists():
            rr = _read_jsonl(rewrites_path)
            if rr is not None and _validate_rewrites_structure_alignment(input_records, rr):
                scores[f"rewrites_structure_alignment_{suffix}"] = 1.0

            if rr is not None and _validate_rewrites_quality(rr):
                scores[f"rewrites_quality_constraints_{suffix}"] = 1.0

        expected_metrics = None
        if input_records is not None:
            expected_metrics = _compute_metrics(input_records)

        metrics_obj = None
        if metrics_path.exists():
            metrics_obj = _load_json(metrics_path)
            if isinstance(metrics_obj, dict):
                top_keys = {
                    "total_tickets",
                    "tickets_by_severity",
                    "avg_message_length_chars",
                    "avg_message_length_words",
                    "earliest_created_at",
                    "latest_created_at",
                    "unique_reporters",
                }
                if set(metrics_obj.keys()) == top_keys:
                    scores[f"metrics_exists_and_keys_{suffix}"] = 1.0

        if isinstance(metrics_obj, dict) and isinstance(expected_metrics, dict):
            ok_vals = True
            ok_vals = ok_vals and (metrics_obj.get("total_tickets") == expected_metrics.get("total_tickets"))
            ok_vals = ok_vals and (metrics_obj.get("earliest_created_at") == expected_metrics.get("earliest_created_at"))
            ok_vals = ok_vals and (metrics_obj.get("latest_created_at") == expected_metrics.get("latest_created_at"))
            ok_vals = ok_vals and (metrics_obj.get("unique_reporters") == expected_metrics.get("unique_reporters"))
            ok_vals = ok_vals and _float_equal(metrics_obj.get("avg_message_length_chars"), expected_metrics.get("avg_message_length_chars"))
            ok_vals = ok_vals and _float_equal(metrics_obj.get("avg_message_length_words"), expected_metrics.get("avg_message_length_words"))
            sev_obj = metrics_obj.get("tickets_by_severity")
            sev_exp = expected_metrics.get("tickets_by_severity")
            if not (isinstance(sev_obj, dict) and isinstance(sev_exp, dict)):
                ok_vals = False
            else:
                for sev, cnt in sev_exp.items():
                    if sev_obj.get(sev) != cnt:
                        ok_vals = False
                        break
            if ok_vals:
                scores[f"metrics_values_correct_{suffix}"] = 1.0

        if notif_path.exists() and isinstance(expected_metrics, dict):
            txt = _read_text(notif_path)
            if isinstance(txt, str) and _validate_notification(txt, expected_metrics):
                scores[f"notification_exists_and_content_{suffix}"] = 1.0

        if state_ok:
            if base in state_map:
                scores[f"state_includes_batch_{suffix}"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()