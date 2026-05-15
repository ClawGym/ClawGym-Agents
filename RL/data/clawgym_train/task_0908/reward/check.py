import json
import os
import sys
import re
from typing import List, Dict, Any

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks (all False by default)
    checks = {
        "all_subjects_json_exists": False,
        "json_min_3_entries": False,
        "json_entries_schema_ok": False,
        "per_campaign_txt_files_exist": False,
        "txt_numbering_and_count_ok": False,
        "constraint_lengths_ok": False,
        "constraint_spam_free_ok": False,
        "constraint_placeholders_ok": False,
        "constraint_numeric_ok": False,
        "constraint_power_words_ok": False,
        "cross_file_subjects_match": False,
        "metrics_consistency_ok": False,
        "qa_notes_exists": False,
        "qa_notes_80_words": False,
    }

    # Helper definitions
    power_words = ["you", "free", "new", "exclusive", "limited"]
    banned_substrings = ["FREE", "!!!", "100%"]

    def strip_numbering(line: str, index: int) -> str:
        prefix = f"{index}. "
        if line.startswith(prefix):
            return line[len(prefix):].rstrip("\n").strip()
        return line.strip()

    def parse_txt_subjects(path: str) -> List[str] | None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = [ln.rstrip("\n") for ln in f.readlines()]
        except Exception:
            return None
        if len(lines) != 10:
            return None
        subjects = []
        for i in range(1, 11):
            expected_prefix = f"{i}. "
            line = lines[i - 1]
            if not line.startswith(expected_prefix):
                return None
            # After prefix, ensure non-empty content
            content = line[len(expected_prefix):].strip()
            if content == "":
                return None
            subjects.append(content)
        return subjects

    def count_in_range(subjects: List[str], lo: int = 40, hi: int = 50) -> int:
        return sum(1 for s in subjects if lo <= len(s.strip()) <= hi)

    def contains_banned(s: str) -> bool:
        # "FREE" uppercase only, "!!!", "100%" exact substrings
        if "FREE" in s:
            return True
        if "!!!" in s:
            return True
        if "100%" in s:
            return True
        return False

    def placeholder_present(s: str) -> bool:
        return ("{name}" in s) or ("{company}" in s)

    def numeric_present(s: str) -> bool:
        return any(ch.isdigit() for ch in s)

    def subject_contains_power_word(s: str) -> bool:
        s_lower = s.lower()
        # Use regex word boundaries for each power word
        for pw in power_words:
            if re.search(rf"\b{re.escape(pw)}\b", s_lower, flags=re.IGNORECASE):
                return True
        return False

    def distinct_power_words(subjects: List[str]) -> int:
        found = set()
        for s in subjects:
            s_lower = s.lower()
            for pw in power_words:
                if re.search(rf"\b{re.escape(pw)}\b", s_lower, flags=re.IGNORECASE):
                    found.add(pw.lower())
        return len(found)

    def recompute_metrics(subjects: List[str]) -> Dict[str, Any]:
        trimmed = [s.strip() for s in subjects]
        lengths = [len(s) for s in trimmed]
        avg_length = sum(lengths) / len(lengths) if lengths else 0.0
        in_range_count = count_in_range(trimmed, 40, 50)
        contains_power_words_count = sum(1 for s in trimmed if subject_contains_power_word(s))
        placeholder_count = sum(1 for s in trimmed if placeholder_present(s))
        numeric_count = sum(1 for s in trimmed if numeric_present(s))
        return {
            "avg_length": avg_length,
            "in_range_count": in_range_count,
            "contains_power_words_count": contains_power_words_count,
            "placeholder_count": placeholder_count,
            "numeric_count": numeric_count,
        }

    # Load all_subjects.json
    all_json_path = os.path.join(output_dir, "all_subjects.json")
    json_data: Dict[str, Any] | None = None
    if os.path.isfile(all_json_path):
        try:
            with open(all_json_path, "r", encoding="utf-8") as f:
                json_data = json.load(f)
            # It must be an object/dict
            if isinstance(json_data, dict):
                checks["all_subjects_json_exists"] = True
        except Exception:
            json_data = None

    if json_data is not None and checks["all_subjects_json_exists"]:
        # Check at least 3 campaign entries
        if len(json_data.keys()) >= 3:
            checks["json_min_3_entries"] = True

        # Validate schema for each entry
        schema_ok = True
        for slug, obj in json_data.items():
            if not isinstance(slug, str):
                schema_ok = False
                break
            if not isinstance(obj, dict):
                schema_ok = False
                break
            # Required keys
            if "topic" not in obj or "purpose" not in obj or "subjects" not in obj or "metrics" not in obj:
                schema_ok = False
                break
            if not isinstance(obj["topic"], str) or not isinstance(obj["purpose"], str):
                schema_ok = False
                break
            if not isinstance(obj["subjects"], list) or len(obj["subjects"]) != 10:
                schema_ok = False
                break
            # subjects must be strings without numbering
            for s in obj["subjects"]:
                if not isinstance(s, str):
                    schema_ok = False
                    break
                # Should not start with numbering like "1. "
                if re.match(r"^\s*\d+\.\s", s):
                    schema_ok = False
                    break
            if not schema_ok:
                break
            metrics = obj["metrics"]
            if not isinstance(metrics, dict):
                schema_ok = False
                break
            # Required metric keys
            required_metric_keys = [
                "avg_length",
                "in_range_count",
                "contains_power_words_count",
                "placeholder_count",
                "numeric_count",
            ]
            for k in required_metric_keys:
                if k not in metrics:
                    schema_ok = False
                    break
            if not schema_ok:
                break
            # Type checks (numbers)
            # Accept int or float; reject non-numeric
            def is_number(x):
                return isinstance(x, (int, float))
            if not is_number(metrics["avg_length"]):
                schema_ok = False
                break
            if not all(isinstance(metrics[k], int) for k in ["in_range_count", "contains_power_words_count", "placeholder_count", "numeric_count"]):
                schema_ok = False
                break
        if schema_ok:
            checks["json_entries_schema_ok"] = True

        # For each slug, verify per-campaign .txt exists
        all_txt_exist = True
        numbering_ok_all = True
        subjects_match_all = True
        constraints_lengths_all = True
        constraints_spam_free_all = True
        constraints_placeholders_all = True
        constraints_numeric_all = True
        constraints_power_words_all = True
        metrics_consistency_all = True

        for slug, obj in json_data.items():
            txt_path = os.path.join(output_dir, f"subjects_{slug}.txt")
            if not os.path.isfile(txt_path):
                all_txt_exist = False
                numbering_ok_all = False
                subjects_match_all = False
                # Without file, all dependent checks remain False
                constraints_lengths_all = False
                constraints_spam_free_all = False
                constraints_placeholders_all = False
                constraints_numeric_all = False
                constraints_power_words_all = False
                metrics_consistency_all = False
                continue

            # Parse txt subjects
            parsed_subjects = parse_txt_subjects(txt_path)
            if parsed_subjects is None:
                numbering_ok_all = False
                subjects_match_all = False
                constraints_lengths_all = False
                constraints_spam_free_all = False
                constraints_placeholders_all = False
                constraints_numeric_all = False
                constraints_power_words_all = False
                metrics_consistency_all = False
                continue

            # Update existence flag
            # Defer setting checks until after we loop all; but track per-campaign booleans
            # Cross-file consistency
            json_subjects = obj.get("subjects", [])
            if len(json_subjects) != 10:
                subjects_match_all = False
            else:
                for js, ts in zip(json_subjects, parsed_subjects):
                    if js.strip() != ts.strip():
                        subjects_match_all = False
                        break

            # Constraints
            # Length window: at least 7 between 40 and 50
            in_range_cnt = count_in_range(parsed_subjects, 40, 50)
            if in_range_cnt < 7:
                constraints_lengths_all = False
            # Spam triggers absent
            if any(contains_banned(s) for s in parsed_subjects):
                constraints_spam_free_all = False
            # Placeholders at least 3
            placeholder_cnt = sum(1 for s in parsed_subjects if placeholder_present(s))
            if placeholder_cnt < 3:
                constraints_placeholders_all = False
            # Numeric at least 3
            numeric_cnt = sum(1 for s in parsed_subjects if numeric_present(s))
            if numeric_cnt < 3:
                constraints_numeric_all = False
            # Power words: at least 2 distinct across set
            distinct_pw = distinct_power_words(parsed_subjects)
            if distinct_pw < 2:
                constraints_power_words_all = False

            # Metrics consistency
            recomputed = recompute_metrics(parsed_subjects)
            recorded = obj.get("metrics", {})
            # All keys must match within tolerance for avg_length
            # Tolerance for floating differences
            tol = 1e-6
            if not isinstance(recorded, dict):
                metrics_consistency_all = False
            else:
                # avg_length
                rec_avg = recorded.get("avg_length", None)
                if not isinstance(rec_avg, (int, float)) or abs(float(rec_avg) - float(recomputed["avg_length"])) > tol:
                    metrics_consistency_all = False
                # in_range_count
                if recorded.get("in_range_count") != recomputed["in_range_count"]:
                    metrics_consistency_all = False
                # contains_power_words_count
                if recorded.get("contains_power_words_count") != recomputed["contains_power_words_count"]:
                    metrics_consistency_all = False
                # placeholder_count
                if recorded.get("placeholder_count") != recomputed["placeholder_count"]:
                    metrics_consistency_all = False
                # numeric_count
                if recorded.get("numeric_count") != recomputed["numeric_count"]:
                    metrics_consistency_all = False

        # Set aggregated checks after loop if appropriate
        if len(json_data) > 0 and all(os.path.isfile(os.path.join(output_dir, f"subjects_{slug}.txt")) for slug in json_data.keys()):
            checks["per_campaign_txt_files_exist"] = True

        # For numbering format
        if numbering_ok_all and checks["per_campaign_txt_files_exist"]:
            checks["txt_numbering_and_count_ok"] = True

        if subjects_match_all and checks["per_campaign_txt_files_exist"]:
            checks["cross_file_subjects_match"] = True

        # Constraints combined
        if constraints_lengths_all and checks["per_campaign_txt_files_exist"]:
            checks["constraint_lengths_ok"] = True
        if constraints_spam_free_all and checks["per_campaign_txt_files_exist"]:
            checks["constraint_spam_free_ok"] = True
        if constraints_placeholders_all and checks["per_campaign_txt_files_exist"]:
            checks["constraint_placeholders_ok"] = True
        if constraints_numeric_all and checks["per_campaign_txt_files_exist"]:
            checks["constraint_numeric_ok"] = True
        if constraints_power_words_all and checks["per_campaign_txt_files_exist"]:
            checks["constraint_power_words_ok"] = True

        if metrics_consistency_all and checks["per_campaign_txt_files_exist"]:
            checks["metrics_consistency_ok"] = True

    # QA notes check
    qa_notes_path = os.path.join(output_dir, "qa_notes.md")
    if os.path.isfile(qa_notes_path):
        checks["qa_notes_exists"] = True
        try:
            with open(qa_notes_path, "r", encoding="utf-8") as f:
                text = f.read()
            # Count words (split by whitespace)
            words = re.findall(r"\S+", text)
            if len(words) >= 80:
                checks["qa_notes_80_words"] = True
        except Exception:
            pass

    # Compute reward as fraction of passed checks
    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    reward = (passed / total) if total > 0 else 0.0

    # No-op baseline: if output dir missing or empty critical files missing, ensure 0.0
    if not os.path.isdir(output_dir):
        reward = 0.0
    if not checks["all_subjects_json_exists"]:
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()