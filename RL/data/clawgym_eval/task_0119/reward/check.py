import json
import csv
import subprocess
import sys
import re
from pathlib import Path
from typing import Optional, Tuple, Any, List


def safe_load_json(path: Path) -> Tuple[bool, Optional[Any]]:
    try:
        if not path.exists() or not path.is_file():
            return False, None
        with path.open('r', encoding='utf-8') as f:
            return True, json.load(f)
    except Exception:
        return False, None


def safe_read_text(path: Path) -> Tuple[bool, Optional[str]]:
    try:
        if not path.exists() or not path.is_file():
            return False, None
        return True, path.read_text(encoding='utf-8')
    except Exception:
        return False, None


def compute_expected_metrics(csv_path: Path) -> Tuple[bool, Optional[dict]]:
    try:
        temps: List[float] = []
        richness: List[int] = []
        if not csv_path.exists() or not csv_path.is_file():
            return False, None
        with csv_path.open('r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if 'temp_anomaly' not in row or 'species_richness' not in row:
                    return False, None
                try:
                    temps.append(float(row['temp_anomaly']))
                    richness.append(int(row['species_richness']))
                except Exception:
                    return False, None
        if not temps or not richness:
            return False, None
        mean_temp = sum(temps) / len(temps)
        delta = richness[-1] - richness[0]
        return True, {
            'mean_temp_anomaly': mean_temp,
            'species_richness_delta': delta
        }
    except Exception:
        return False, None


def import_compute_metrics(workspace: Path):
    try:
        if str(workspace) not in sys.path:
            sys.path.insert(0, str(workspace))
        import importlib
        mod = importlib.import_module('analysis.metrics')
        func = getattr(mod, 'compute_metrics', None)
        return func
    except Exception:
        return None


def run_unittests(workspace: Path, timeout: int = 60) -> Tuple[bool, int, str, str]:
    try:
        proc = subprocess.run(
            ['python', '-m', 'unittest', '-q'],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return True, proc.returncode, proc.stdout, proc.stderr
    except Exception as e:
        return False, -1, '', str(e)


def nearly_equal(a: float, b: float, tol: float = 1e-2) -> bool:
    try:
        return abs(a - b) <= tol
    except Exception:
        return False


def extract_sections_status_md(text: str) -> dict:
    lines = text.splitlines()
    sections = {'steps': [], 'metrics': [], 'notes': []}
    current = None
    for line in lines:
        stripped = line.strip()
        low = stripped.lower()
        if low.startswith('steps:'):
            current = 'steps'
            continue
        if low.startswith('metrics:'):
            current = 'metrics'
            continue
        if low.startswith('notes:'):
            current = 'notes'
            continue
        if current:
            sections[current].append(line)
    return sections


def parse_bullets(lines: List[str]) -> List[str]:
    bullets = []
    for ln in lines:
        if ln.strip().startswith('-'):
            bullets.append(re.sub(r'\s+', ' ', ln.strip()))
    return bullets


def count_sentences(text_lines: List[str]) -> int:
    joined = ' '.join(text_lines).strip()
    if not joined:
        return 0
    parts = re.split(r'[.!?]+', joined)
    return len([p for p in parts if p.strip()])


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "pipeline_packaging_command_correct": 0.0,
        "artifacts_metrics_json_present": 0.0,
        "artifacts_metrics_keys_present": 0.0,
        "artifacts_metrics_values_correct": 0.0,
        "latest_run_json_present": 0.0,
        "latest_run_ok_true": 0.0,
        "all_steps_succeeded": 0.0,
        "unit_tests_pass": 0.0,
        "metrics_function_correctness": 0.0,
        "cli_out_flag_declared_in_code": 0.0,
        "status_md_has_sections": 0.0,
        "status_steps_match_ci": 0.0,
        "status_metrics_match_artifact": 0.0,
        "notes_section_length_ok": 0.0,
    }

    # Check pipeline packaging command
    pipeline_path = workspace / 'ci' / 'pipeline.json'
    ok, pipeline = safe_load_json(pipeline_path)
    expected_cmd = "python analysis/metrics.py --input data/observations.csv --out artifacts/metrics.json"
    if ok and isinstance(pipeline, dict):
        steps = pipeline.get('steps', [])
        if isinstance(steps, list) and steps:
            pkg_cmd = None
            for st in steps:
                if isinstance(st, dict) and st.get('name') == 'package':
                    pkg_cmd = st.get('run')
                    break
            if pkg_cmd == expected_cmd:
                scores["pipeline_packaging_command_correct"] = 1.0

    # Check artifacts/metrics.json existence and parseability and keys/values
    artifacts_metrics_path = workspace / 'artifacts' / 'metrics.json'
    ok_art, artifact_data = safe_load_json(artifacts_metrics_path)
    if ok_art and isinstance(artifact_data, dict):
        scores["artifacts_metrics_json_present"] = 1.0
        keys_ok = ('mean_temp_anomaly' in artifact_data) and ('species_richness_delta' in artifact_data)
        if keys_ok:
            scores["artifacts_metrics_keys_present"] = 1.0
        ok_exp, exp_metrics = compute_expected_metrics(workspace / 'data' / 'observations.csv')
        if ok_exp and keys_ok and isinstance(exp_metrics, dict):
            try:
                m_ok = nearly_equal(float(artifact_data['mean_temp_anomaly']), float(exp_metrics['mean_temp_anomaly']), tol=1e-2)
                d_ok = float(artifact_data['species_richness_delta']) == float(exp_metrics['species_richness_delta'])
            except Exception:
                m_ok = False
                d_ok = False
            if m_ok and d_ok:
                scores["artifacts_metrics_values_correct"] = 1.0

    # Check latest_run.json
    latest_run_path = workspace / 'ci' / 'latest_run.json'
    ok_run, run_data = safe_load_json(latest_run_path)
    if ok_run and isinstance(run_data, dict):
        scores["latest_run_json_present"] = 1.0
        if run_data.get('ok') is True:
            scores["latest_run_ok_true"] = 1.0
        steps_list = run_data.get('steps')
        if isinstance(steps_list, list) and steps_list:
            if all(isinstance(s, dict) and s.get('status') == 'success' for s in steps_list):
                scores["all_steps_succeeded"] = 1.0

    # Run unit tests
    ran, returncode, _, _ = run_unittests(workspace)
    if ran and returncode == 0:
        scores["unit_tests_pass"] = 1.0

    # Test compute_metrics correctness directly
    func = import_compute_metrics(workspace)
    if func is not None:
        try:
            result = func(str(workspace / 'data' / 'observations.csv'))
            ok_exp, exp_metrics = compute_expected_metrics(workspace / 'data' / 'observations.csv')
            if isinstance(result, dict) and ok_exp and isinstance(exp_metrics, dict):
                m_ok = nearly_equal(float(result.get('mean_temp_anomaly')), float(exp_metrics['mean_temp_anomaly']), tol=1e-2)
                d_ok = float(result.get('species_richness_delta')) == float(exp_metrics['species_richness_delta'])
                if m_ok and d_ok:
                    scores["metrics_function_correctness"] = 1.0
        except Exception:
            pass

    # Check CLI --out flag declared via argparse in analysis/metrics.py
    metrics_py_path = workspace / 'analysis' / 'metrics.py'
    ok_txt, metrics_py_text = safe_read_text(metrics_py_path)
    if ok_txt and isinstance(metrics_py_text, str):
        # Require it to be part of an argparse add_argument call, not just a comment
        out_flag_pattern = re.compile(r'add_argument\(\s*[\'"]--out[\'"]')
        if out_flag_pattern.search(metrics_py_text):
            scores["cli_out_flag_declared_in_code"] = 1.0

    # Check delivery/STATUS.md content
    status_path = workspace / 'delivery' / 'STATUS.md'
    ok_status, status_text = safe_read_text(status_path)
    if ok_status and isinstance(status_text, str):
        sections = extract_sections_status_md(status_text)
        has_steps = len(sections.get('steps', [])) >= 1
        has_metrics = len(sections.get('metrics', [])) >= 1
        has_notes = len(sections.get('notes', [])) >= 1
        if has_steps and has_metrics and has_notes:
            scores["status_md_has_sections"] = 1.0

        # Validate steps bullets match latest_run.json
        if ok_run and isinstance(run_data, dict):
            bullets = parse_bullets(sections.get('steps', []))
            step_items = run_data.get('steps', []) if isinstance(run_data.get('steps'), list) else []
            if bullets and step_items:
                matches = 0
                for s in step_items:
                    name = str(s.get('name', '')).strip()
                    status = str(s.get('status', '')).strip()
                    for b in bullets:
                        if name in b and status in b:
                            matches += 1
                            break
                if matches == len(step_items) and len(bullets) >= len(step_items):
                    scores["status_steps_match_ci"] = 1.0

        # Validate metrics values match artifact
        if ok_art and isinstance(artifact_data, dict):
            metrics_lines = sections.get('metrics', [])
            mt_present = False
            sr_present = False
            mt_val = artifact_data.get('mean_temp_anomaly')
            sr_val = artifact_data.get('species_richness_delta')
            for ln in metrics_lines:
                lower_ln = ln.lower()
                if 'mean_temp_anomaly' in lower_ln:
                    nums = re.findall(r'[-+]?\d*\.\d+|\d+', ln)
                    if nums:
                        try:
                            val = float(nums[0])
                            if nearly_equal(val, float(mt_val), tol=1e-2):
                                mt_present = True
                        except Exception:
                            pass
                if 'species_richness_delta' in lower_ln:
                    nums = re.findall(r'[-+]?\d+', ln)
                    if nums:
                        try:
                            val = int(nums[0])
                            if val == int(sr_val):
                                sr_present = True
                        except Exception:
                            pass
            if mt_present and sr_present:
                scores["status_metrics_match_artifact"] = 1.0

        # Notes length 2–3 sentences (allowing up to 4 with punctuation quirks)
        notes_lines = sections.get('notes', [])
        n_sent = count_sentences(notes_lines)
        if 2 <= n_sent <= 4:
            scores["notes_section_length_ok"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()