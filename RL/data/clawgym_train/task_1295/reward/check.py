import json
import sys
import re
from pathlib import Path
import zipfile


def _safe_read_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_jsonl(path: Path):
    try:
        items = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                items.append(json.loads(line))
        return items
    except Exception:
        return None


def _records_valid(items):
    # Required fields: call_sign, scenario, pilot_says, atc_says
    if not isinstance(items, list) or len(items) != 2:
        return False
    pat = re.compile(r"^[A-Z0-9]{3,7}$")
    required = ["call_sign", "scenario", "pilot_says", "atc_says"]
    for it in items:
        if not isinstance(it, dict):
            return False
        # All required fields present, string, non-empty
        for k in required:
            v = it.get(k, "")
            if not isinstance(v, str) or len(v.strip()) == 0:
                return False
        # Call sign pattern
        cs = it.get("call_sign", "")
        if pat.fullmatch(cs) is None:
            return False
    return True


def _zip_has_members(zip_path: Path, members):
    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            names = set(z.namelist())
            return all(m in names for m in members)
    except Exception:
        return False


def _read_zip_member_text(zip_path: Path, member: str):
    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            with z.open(member) as f:
                return f.read().decode("utf-8")
    except Exception:
        return None


def _count_sentences(text: str) -> int:
    # Split on ., !, ? while ignoring multiple punctuation
    parts = re.split(r"[.!?]+", text)
    return len([p for p in parts if p.strip()])


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_version_1_1_0": 0.0,
        "config_enabled_steps_order": 0.0,
        "scenarios_two_records_fields_and_callsigns_valid": 0.0,
        "ci_summary_present_and_parseable": 0.0,
        "ci_steps_run_exact_order": 0.0,
        "ci_phrase_check_passed_true": 0.0,
        "ci_scenario_count_2": 0.0,
        "ci_artifact_path_and_exists": 0.0,
        "artifact_zip_has_scenarios_and_manifest": 0.0,
        "artifact_manifest_matches": 0.0,
        "email_subject_line_correct": 0.0,
        "email_labeled_lines_exact": 0.0,
        "email_addressed_to_cfi_team": 0.0,
        "email_explains_phrase_check_practice_clear_atc": 0.0,
        "email_requests_feedback_on_scenarios": 0.0,
        "email_sentence_count_between_1_and_2": 0.0,
    }

    # 1) config.json checks
    cfg_path = workspace / "input" / "config.json"
    cfg = _safe_read_json(cfg_path)
    if isinstance(cfg, dict):
        if cfg.get("version") == "1.1.0":
            scores["config_version_1_1_0"] = 1.0
        enabled_steps = cfg.get("enabled_steps")
        if isinstance(enabled_steps, list) and enabled_steps == ["test", "phrase_check", "build"]:
            scores["config_enabled_steps_order"] = 1.0

    # 2) scenarios.jsonl checks (combined strict validation)
    scenarios_path = workspace / "input" / "data" / "scenarios.jsonl"
    items = _safe_read_jsonl(scenarios_path)
    if isinstance(items, list) and _records_valid(items):
        scores["scenarios_two_records_fields_and_callsigns_valid"] = 1.0

    # 3) CI summary and artifact checks
    summary_path = workspace / "reports" / "ci-summary.json"
    summary = _safe_read_json(summary_path)
    if isinstance(summary, dict):
        scores["ci_summary_present_and_parseable"] = 1.0
        steps_run = summary.get("steps_run")
        if isinstance(steps_run, list) and steps_run == ["test", "phrase_check", "build"]:
            scores["ci_steps_run_exact_order"] = 1.0
        if summary.get("phrase_check_passed") is True:
            scores["ci_phrase_check_passed_true"] = 1.0
        if summary.get("scenario_count") == 2:
            scores["ci_scenario_count_2"] = 1.0
        artifact_rel_expected = "dist/atc-phrase-trainer-1.1.0.zip"
        artifact_field = summary.get("artifact")
        artifact_exists_flag = summary.get("artifact_exists")
        artifact_fs = workspace / "dist" / "atc-phrase-trainer-1.1.0.zip"
        if (
            artifact_field == artifact_rel_expected
            and artifact_exists_flag is True
            and artifact_fs.exists()
        ):
            scores["ci_artifact_path_and_exists"] = 1.0

    # 3b) Artifact zip contents and manifest
    artifact_zip = workspace / "dist" / "atc-phrase-trainer-1.1.0.zip"
    if artifact_zip.exists():
        if _zip_has_members(artifact_zip, ["scenarios.jsonl", "manifest.json"]):
            scores["artifact_zip_has_scenarios_and_manifest"] = 1.0
            manifest_text = _read_zip_member_text(artifact_zip, "manifest.json")
            try:
                manifest = json.loads(manifest_text) if manifest_text is not None else None
            except Exception:
                manifest = None
            if isinstance(manifest, dict):
                if (
                    manifest.get("app_name") == "atc-phrase-trainer"
                    and manifest.get("version") == "1.1.0"
                    and manifest.get("scenario_count") == 2
                ):
                    scores["artifact_manifest_matches"] = 1.0

    # 4) Release email checks
    email_path = workspace / "out" / "release_email.txt"
    email_text = _safe_read_text(email_path)
    if isinstance(email_text, str):
        lines = email_text.splitlines()
        if len(lines) >= 1 and lines[0].strip() == "ATC Phrase Trainer v1.1.0 CI summary":
            scores["email_subject_line_correct"] = 1.0

        # Body labeled lines required
        required_labeled = [
            "Version: 1.1.0",
            "Scenarios: 2",
            "Phrase check: PASS",
            "Artifact: dist/atc-phrase-trainer-1.1.0.zip",
        ]
        body_lines = [ln.strip() for ln in lines[1:]] if len(lines) > 1 else []
        body_set = set([ln for ln in body_lines if ln])
        if all(req in body_set for req in required_labeled):
            scores["email_labeled_lines_exact"] = 1.0

        # Remainder text (non-labeled) for prose checks
        remainder_lines = [ln for ln in body_lines if ln and ln not in required_labeled]
        remainder_text = " ".join(remainder_lines).strip()
        if remainder_text:
            # Addressed to CFI Team
            if "cfi team" in remainder_text.lower():
                scores["email_addressed_to_cfi_team"] = 1.0
            lower = remainder_text.lower()
            # Explains enabling a phrase consistency check to practice clearer ATC communications
            explains = (
                ("enable" in lower or "enabled" in lower)
                and ("phrase" in lower and "check" in lower)
                and ("consisten" in lower)  # consistency or consistent
                and ("practic" in lower)     # practice/practicing
                and ("atc" in lower)
                and ("clear" in lower)       # clear/clearer/clarity
            )
            if explains:
                scores["email_explains_phrase_check_practice_clear_atc"] = 1.0
            # Requests feedback on the scenarios
            if ("feedback" in lower) and ("scenario" in lower):
                scores["email_requests_feedback_on_scenarios"] = 1.0
            # Sentence count 1–2
            if 1 <= _count_sentences(remainder_text) <= 2:
                scores["email_sentence_count_between_1_and_2"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()