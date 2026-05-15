import json
import sys
import csv
import re
from pathlib import Path
from typing import Optional, Dict, Any, List


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        header = reader.fieldnames or []
        for r in rows:
            if set(r.keys()) != set(header):
                return None
        return rows
    except Exception:
        return None


def _parse_claim_percent(md_text: str) -> Optional[float]:
    if not md_text:
        return None
    matches = re.findall(r'([0-9]+(?:\.[0-9]+)?)\s*%', md_text)
    if not matches:
        return None
    try:
        return float(matches[0])
    except Exception:
        return None


def _safe_float(val: Any) -> Optional[float]:
    try:
        return float(val)
    except Exception:
        return None


def _compute_expected_metrics(workspace: Path) -> Optional[Dict[str, Any]]:
    pred_path = workspace / "input" / "predictions.csv"
    truth_path = workspace / "input" / "ground_truth.csv"
    labels_path = workspace / "input" / "label_map.json"

    pred_rows = _read_csv_rows(pred_path)
    truth_rows = _read_csv_rows(truth_path)
    labels = _read_json(labels_path)

    if pred_rows is None or truth_rows is None or labels is None:
        return None

    truth_map = {}
    for r in truth_rows:
        if "image_id" not in r or "true_label" not in r:
            return None
        truth_map[r["image_id"]] = r["true_label"]

    pred_index_map = {}
    for r in pred_rows:
        if "image_id" not in r or "predicted_index" not in r:
            return None
        pred_index_map[r["image_id"]] = r["predicted_index"]

    ids_truth = set(truth_map.keys())
    ids_pred = set(pred_index_map.keys())
    unmatched_ids = ids_truth.symmetric_difference(ids_pred)
    unmatched_ids_count = len(unmatched_ids)

    common_ids = sorted(ids_truth.intersection(ids_pred))

    label_keys = set(labels.keys())
    unknown_index_count = 0
    correct = 0
    total = len(common_ids)
    for img_id in common_ids:
        idx = pred_index_map[img_id]
        if idx not in label_keys:
            unknown_index_count += 1
            continue
        pred_class = labels.get(idx)
        true_label = truth_map.get(img_id)
        if pred_class == true_label:
            correct += 1

    measured_accuracy_percent = (correct / total * 100.0) if total > 0 else 0.0

    return {
        "total_images": total,
        "correct_predictions": correct,
        "unmatched_ids_count": unmatched_ids_count,
        "unknown_index_count": unknown_index_count,
        "measured_accuracy_percent": measured_accuracy_percent,
    }


def _near(a: float, b: float, tol: float = 0.05) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def _load_report(path: Path) -> Optional[Dict[str, Any]]:
    data = _read_json(path)
    if not isinstance(data, dict):
        return None
    required_fields = [
        "claim_accuracy_percent",
        "measured_accuracy_percent",
        "claim_supported",
        "total_images",
        "correct_predictions",
        "unmatched_ids_count",
        "unknown_index_count",
    ]
    for k in required_fields:
        if k not in data:
            return None
    return data


def _extract_numbers(text: str) -> List[float]:
    nums = []
    for m in re.findall(r'[-+]?\d+(?:\.\d+)?', text or ""):
        try:
            nums.append(float(m))
        except Exception:
            pass
    return nums


def _count_sentences(text: str) -> int:
    parts = re.split(r'[.!?]+', text.strip())
    count = sum(1 for p in parts if p.strip())
    return count


def _has_next_step_indicator(text: str) -> bool:
    indicators = [
        "next step", "next steps", "we will", "please", "proceed", "follow-up",
        "action", "plan to", "let's", "lets ", "schedule", "run ", "check ", "investigate", "review"
    ]
    lower = text.lower()
    return any(ind in lower for ind in indicators)


def _is_professional_tone(text: str) -> bool:
    lower = text.toLower() if hasattr(text, "toLower") else text.lower()
    casual = [
        "hey", "ok-ish", "lol", "lmao", "btw", "imo", "idk", "i think", "maybe", "not 100%", "🙂", "😉", "👍", "gonna"
    ]
    return not any(term in lower for term in casual)


def _contains_accuracy_value(text: str, percent_value: Optional[float]) -> bool:
    if percent_value is None:
        return False
    lower = text.lower()
    pattern = re.findall(r'([0-9]+(?:\.[0-9]+)?)\s*%?', lower)
    for num_str in pattern:
        try:
            val = float(num_str)
            if _near(val, percent_value, tol=0.1):
                if '%' in lower or 'percent' in lower:
                    return True
        except Exception:
            continue
    return False


def _check_rewritten_ops_message(path: Path, measured_percent: Optional[float]) -> Dict[str, float]:
    content = _read_text(path)
    if content is None:
        return {
            "rewritten_ops_message_accuracy_and_next_step": 0.0,
            "rewritten_ops_message_professional_tone": 0.0,
        }
    sentence_count = _count_sentences(content)
    has_next = _has_next_step_indicator(content)
    has_accuracy = _contains_accuracy_value(content, measured_percent)
    one_sentence_ok = sentence_count == 1
    acc_next_ok = 1.0 if (has_accuracy and has_next and one_sentence_ok) else 0.0

    tone_ok = 1.0 if _is_professional_tone(content) else 0.0

    return {
        "rewritten_ops_message_accuracy_and_next_step": acc_next_ok,
        "rewritten_ops_message_professional_tone": tone_ok,
    }


def _check_email(workspace: Path, measured_percent: Optional[float], claim_supported: Optional[bool]) -> Dict[str, float]:
    email_path = workspace / "output" / "email_to_ml_contractor.md"
    content = _read_text(email_path)
    scores = {
        "email_subject_and_greeting": 0.0,
        "email_summary_references_accuracy_and_support": 0.0,
        "email_two_bullets_no_links": 0.0,
    }
    if content is None:
        return scores

    lines = [ln.rstrip() for ln in content.splitlines()]
    nonempty_lines = [ln for ln in lines if ln.strip() != ""]
    subject_ok = False
    if nonempty_lines:
        first = nonempty_lines[0]
        subject_ok = first.strip().lower().startswith("subject:")
    greeting_ok = any(re.match(r'^\s*(Hi|Hello|Dear)\b', ln) for ln in lines)
    scores["email_subject_and_greeting"] = 1.0 if (subject_ok and greeting_ok) else 0.0

    greet_idx = None
    for i, ln in enumerate(lines):
        if re.match(r'^\s*(Hi|Hello|Dear)\b', ln):
            greet_idx = i
            break

    summary_text = ""
    if greet_idx is not None:
        sum_lines = []
        for ln in lines[greet_idx + 1:]:
            if not ln.strip():
                if sum_lines:
                    break
                else:
                    continue
            if re.match(r'^\s*[-*]\s+', ln):
                break
            sum_lines.append(ln.strip())
        summary_text = " ".join(sum_lines).strip()

    sentences_count = _count_sentences(summary_text) if summary_text else 0
    has_accuracy = _contains_accuracy_value(summary_text, measured_percent)
    support_phrase_positive = any(kw in summary_text.lower() for kw in ["support", "supports", "supported", "match", "matches", "aligned", "aligns", "consistent", "in line with", "validate", "validated"])
    negative_phrase = any(kw in summary_text.lower() for kw in ["does not support", "not support", "doesn't support", "falls short", "below the claim", "below claim", "above the claim"])
    support_ok = False
    if claim_supported is True:
        support_ok = support_phrase_positive and not negative_phrase
    elif claim_supported is False:
        support_ok = negative_phrase and not support_phrase_positive
    else:
        support_ok = False
    summary_ok = (2 <= sentences_count <= 3) and has_accuracy and support_ok
    scores["email_summary_references_accuracy_and_support"] = 1.0 if summary_ok else 0.0

    bullet_lines = [ln for ln in lines if re.match(r'^\s*[-*]\s+', ln)]
    bullets_ok = len(bullet_lines) == 2
    no_links = ("http://" not in content and "https://" not in content and "www." not in content)
    scores["email_two_bullets_no_links"] = 1.0 if (bullets_ok and no_links) else 0.0

    return scores


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "verify_script_exists": 0.0,
        "verify_script_has_required_cli": 0.0,
        "verification_report_present_and_valid": 0.0,
        "verification_report_values_correct": 0.0,
        "run_log_present_and_nonempty": 0.0,
        "rewritten_ops_message_accuracy_and_next_step": 0.0,
        "rewritten_ops_message_professional_tone": 0.0,
        "email_subject_and_greeting": 0.0,
        "email_summary_references_accuracy_and_support": 0.0,
        "email_two_bullets_no_links": 0.0,
    }

    verify_path = workspace / "scripts" / "verify.py"
    if verify_path.exists() and verify_path.is_file():
        scores["verify_script_exists"] = 1.0
        text = _read_text(verify_path) or ""
        required_flags = ["--pred", "--truth", "--labels", "--claim", "--out"]
        has_all_flags = all(flag in text for flag in required_flags)
        scores["verify_script_has_required_cli"] = 1.0 if has_all_flags else 0.0

    expected_metrics = _compute_expected_metrics(workspace)

    readme_path = workspace / "input" / "README_claim.md"
    readme_text = _read_text(readme_path)
    expected_claim = _parse_claim_percent(readme_text) if readme_text is not None else None

    report_path = workspace / "output" / "verification_report.json"
    report = _load_report(report_path)
    if report is not None:
        scores["verification_report_present_and_valid"] = 1.0

    if report is not None and expected_metrics is not None and expected_claim is not None:
        ok = True
        ok = ok and _near(_safe_float(report.get("claim_accuracy_percent")), expected_claim, tol=0.05)
        ok = ok and _near(_safe_float(report.get("measured_accuracy_percent")), expected_metrics["measured_accuracy_percent"], tol=0.05)
        try:
            ok = ok and int(report.get("total_images")) == int(expected_metrics["total_images"])
            ok = ok and int(report.get("correct_predictions")) == int(expected_metrics["correct_predictions"])
            ok = ok and int(report.get("unmatched_ids_count")) == int(expected_metrics["unmatched_ids_count"])
            ok = ok and int(report.get("unknown_index_count")) == int(expected_metrics["unknown_index_count"])
        except Exception:
            ok = False
        expected_supported = _near(expected_metrics["measured_accuracy_percent"], expected_claim, tol=0.05)
        if isinstance(report.get("claim_supported"), bool):
            ok = ok and (report["claim_supported"] == expected_supported)
        else:
            ok = False
        scores["verification_report_values_correct"] = 1.0 if ok else 0.0

    run_log_path = workspace / "output" / "run.log"
    try:
        if run_log_path.exists() and run_log_path.is_file() and run_log_path.stat().st_size > 0:
            scores["run_log_present_and_nonempty"] = 1.0
    except Exception:
        scores["run_log_present_and_nonempty"] = 0.0

    measured_percent_for_text: Optional[float] = None
    claim_supported_for_text: Optional[bool] = None
    if report is not None and isinstance(report.get("measured_accuracy_percent"), (int, float)):
        measured_percent_for_text = float(report["measured_accuracy_percent"])
    elif expected_metrics is not None:
        measured_percent_for_text = float(expected_metrics["measured_accuracy_percent"])
    if report is not None and isinstance(report.get("claim_supported"), bool):
        claim_supported_for_text = bool(report["claim_supported"])
    else:
        if expected_metrics is not None and expected_claim is not None:
            claim_supported_for_text = _near(expected_metrics["measured_accuracy_percent"], expected_claim, tol=0.05)

    ops_msg_path = workspace / "output" / "rewritten_ops_message.md"
    ops_scores = _check_rewritten_ops_message(ops_msg_path, measured_percent_for_text)
    scores.update(ops_scores)

    email_scores = _check_email(workspace, measured_percent_for_text, claim_supported_for_text)
    scores.update(email_scores)

    return scores


def main() -> None:
    workspace_path = "."
    if len(sys.argv) > 1:
        workspace_path = sys.argv[1]
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()