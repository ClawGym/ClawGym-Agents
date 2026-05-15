import csv
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def read_csv_dicts(path: Path) -> Tuple[Optional[List[dict]], Optional[List[str]]]:
    try:
        with path.open(newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None, None
            rows = [dict(r) for r in reader]
            return rows, headers
    except Exception:
        return None, None


def load_json(path: Path) -> Optional[object]:
    try:
        with path.open('r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def run_hash_tool_to_mapping(workspace: Path, root_rel: str, episodes_csv_rel: str) -> Optional[Dict[str, dict]]:
    tool_path = workspace / "tools" / "hash_all.py"
    root_path = workspace / root_rel
    episodes_path = workspace / episodes_csv_rel
    if not tool_path.exists() or not episodes_path.exists() or not root_path.exists():
        return None
    try:
        with tempfile.NamedTemporaryFile(mode='w+', delete=True, suffix='.csv') as tmp:
            cmd = [
                sys.executable,
                str(tool_path),
                '--root', str(root_path),
                '--episodes', str(episodes_path),
                '--out', tmp.name
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if res.returncode != 0:
                return None
            tmp.flush()
            tmp.seek(0)
            rows, headers = read_csv_dicts(Path(tmp.name))
            if rows is None or headers is None:
                return None
            expected_cols = {'episode_id', 'file_path', 'root', 'sha256', 'missing'}
            if not expected_cols.issubset(set(headers)):
                return None
            mapping: Dict[str, dict] = {}
            for r in rows:
                eid = r.get('episode_id', '')
                if not eid:
                    return None
                mapping[eid] = {
                    'episode_id': eid,
                    'file_path': r.get('file_path', ''),
                    'root': r.get('root', ''),
                    'sha256': r.get('sha256', ''),
                    'missing': str(r.get('missing', '')).strip().lower()
                }
            return mapping
    except Exception:
        return None


def parse_checksums_csv(path: Path) -> Optional[Dict[str, dict]]:
    rows, headers = read_csv_dicts(path)
    if rows is None or headers is None:
        return None
    expected_cols = {'episode_id', 'file_path', 'root', 'sha256', 'missing'}
    if set(headers) != ['episode_id', 'file_path', 'root', 'sha256', 'missing'] and not expected_cols.issubset(set(headers)):
        return None
    mapping: Dict[str, dict] = {}
    try:
        for r in rows:
            eid = r.get('episode_id', '')
            if not eid or eid in mapping:
                return None
            mapping[eid] = {
                'episode_id': eid,
                'file_path': r.get('file_path', ''),
                'root': r.get('root', ''),
                'sha256': r.get('sha256', ''),
                'missing': str(r.get('missing', '')).strip().lower()
            }
        return mapping
    except Exception:
        return None


def compare_checksums(expected: Dict[str, dict], actual: Dict[str, dict]) -> float:
    # Require exact set of episode_ids
    if set(expected.keys()) != set(actual.keys()):
        return 0.0
    total = len(expected)
    if total == 0:
        return 0.0
    correct = 0
    for eid, exp in expected.items():
        act = actual.get(eid)
        if act is None:
            continue
        # file_path must match
        if act.get('file_path', '') != exp.get('file_path', ''):
            continue
        # missing flag must match exactly
        if str(act.get('missing', '')).strip().lower() != str(exp.get('missing', '')).strip().lower():
            continue
        # if not missing, sha must match
        if str(exp.get('missing', '')).strip().lower() == 'false':
            if act.get('sha256', '') != exp.get('sha256', ''):
                continue
        correct += 1
    return correct / float(total)


def aggregate_logs(logs_path: Path, valid_episode_ids: List[str]) -> Dict[str, dict]:
    result: Dict[str, dict] = {eid: {'plays': 0, 'errors': 0, 'error_rate': 0.0} for eid in valid_episode_ids}
    rows, headers = read_csv_dicts(logs_path)
    if rows is None or headers is None:
        return result
    for r in rows:
        eid = r.get('episode_id', '')
        if eid not in result:
            continue
        result[eid]['plays'] += 1
        status = (r.get('status', '') or '').strip().upper()
        if status == 'ERROR':
            result[eid]['errors'] += 1
    for eid, agg in result.items():
        plays = agg['plays']
        errors = agg['errors']
        agg['error_rate'] = (errors / plays) if plays > 0 else 0.0
    return result


def compute_checksum_status(expected_baseline: Dict[str, dict], expected_library: Dict[str, dict], episode_ids: List[str]) -> Dict[str, str]:
    status: Dict[str, str] = {}
    for eid in episode_ids:
        b = expected_baseline.get(eid)
        l = expected_library.get(eid)
        if b is None or l is None:
            status[eid] = 'missing'
            continue
        b_missing = str(b.get('missing', '')).strip().lower() == 'true'
        l_missing = str(l.get('missing', '')).strip().lower() == 'true'
        if b_missing or l_missing:
            status[eid] = 'missing'
        else:
            status[eid] = 'match' if b.get('sha256', '') == l.get('sha256', '') else 'mismatch'
    return status


def floats_equal(a: float, b: float, tol: float = 1e-9) -> bool:
    return math.isclose(a, b, rel_tol=0.0, abs_tol=tol)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "baseline_checksums_correct": 0.0,
        "library_checksums_correct": 0.0,
        "episode_health_content_correct": 0.0,
        "episode_health_sorted_correctly": 0.0,
        "top3_content_correct": 0.0,
    }

    episodes_csv = workspace / "input" / "meta" / "episodes.csv"
    episodes_rows, episodes_headers = read_csv_dicts(episodes_csv)
    if episodes_rows is None or episodes_headers is None:
        return scores
    required_episode_cols = {'episode_id', 'title', 'season', 'file_path'}
    if not required_episode_cols.issubset(set(episodes_headers)):
        return scores
    catalog: List[dict] = []
    for r in episodes_rows:
        catalog.append({
            'episode_id': r.get('episode_id', ''),
            'title': r.get('title', ''),
            'season': r.get('season', ''),
            'file_path': r.get('file_path', ''),
        })
    # Validate episode IDs
    episode_ids = [r['episode_id'] for r in catalog if r.get('episode_id')]
    if not episode_ids or len(episode_ids) != len(set(episode_ids)):
        return scores

    # Compute expected checksums by running provided tool
    expected_baseline = run_hash_tool_to_mapping(workspace, "input/baseline", "input/meta/episodes.csv")
    expected_library = run_hash_tool_to_mapping(workspace, "input/library", "input/meta/episodes.csv")

    # Student-produced checksum files
    student_baseline_path = workspace / "workspace" / "checksums_baseline.csv"
    student_library_path = workspace / "workspace" / "checksums_library.csv"
    student_baseline = parse_checksums_csv(student_baseline_path) if student_baseline_path.exists() else None
    student_library = parse_checksums_csv(student_library_path) if student_library_path.exists() else None

    if expected_baseline is not None and student_baseline is not None:
        scores["baseline_checksums_correct"] = compare_checksums(expected_baseline, student_baseline)
    else:
        scores["baseline_checksums_correct"] = 0.0

    if expected_library is not None and student_library is not None:
        scores["library_checksums_correct"] = compare_checksums(expected_library, student_library)
    else:
        scores["library_checksums_correct"] = 0.0

    # Compute expected aggregates and checksum_status for reports
    logs_csv = workspace / "input" / "logs" / "plays.csv"
    agg = aggregate_logs(logs_csv, episode_ids)
    checksum_status_map: Dict[str, str] = {}
    if expected_baseline is not None and expected_library is not None:
        checksum_status_map = compute_checksum_status(expected_baseline, expected_library, episode_ids)
    else:
        checksum_status_map = {eid: 'missing' for eid in episode_ids}

    # Validate episode_health.csv
    health_csv_path = workspace / "workspace" / "reports" / "episode_health.csv"
    health_rows, health_headers = read_csv_dicts(health_csv_path) if health_csv_path.exists() else (None, None)
    health_content_ok = 0.0
    health_sorted_ok = 0.0
    if health_rows is not None and health_headers is not None:
        expected_headers = ['episode_id', 'title', 'plays', 'errors', 'error_rate', 'checksum_status']
        if health_headers == expected_headers:
            # Build map and ensure exact set of episodes
            health_map: Dict[str, dict] = {}
            valid_parse = True
            for r in health_rows:
                eid = r.get('episode_id', '')
                if not eid or eid in health_map:
                    valid_parse = False
                    break
                health_map[eid] = r
            if valid_parse and set(health_map.keys()) == set(episode_ids) and len(health_rows) == len(episode_ids):
                total = len(episode_ids)
                correct = 0
                for ep in catalog:
                    eid = ep['episode_id']
                    r = health_map.get(eid)
                    if r is None:
                        continue
                    if r.get('title', '') != ep.get('title', ''):
                        continue
                    try:
                        plays_val = int(str(r.get('plays', '0')))
                        errors_val = int(str(r.get('errors', '0')))
                        erate_val = float(str(r.get('error_rate', '0')))
                    except Exception:
                        continue
                    exp = agg.get(eid, {'plays': 0, 'errors': 0, 'error_rate': 0.0})
                    if plays_val != exp['plays']:
                        continue
                    if errors_val != exp['errors']:
                        continue
                    if not floats_equal(erate_val, exp['error_rate'], tol=1e-9):
                        continue
                    if r.get('checksum_status', '') != checksum_status_map.get(eid, ''):
                        continue
                    correct += 1
                health_content_ok = correct / float(total) if total > 0 else 0.0

                # Check sorting
                def sort_key(ep_row: dict):
                    eid = ep_row['episode_id']
                    exp = agg.get(eid, {'plays': 0, 'errors': 0, 'error_rate': 0.0})
                    return (-exp['error_rate'], -exp['errors'], eid)

                expected_sorted = sorted(catalog, key=sort_key)
                expected_order = [r['episode_id'] for r in expected_sorted]
                actual_order = [r['episode_id'] for r in health_rows]
                health_sorted_ok = 1.0 if actual_order == expected_order else 0.0
    scores["episode_health_content_correct"] = health_content_ok
    scores["episode_health_sorted_correctly"] = health_sorted_ok

    # Validate top3.json
    top3_path = workspace / "workspace" / "reports" / "top3.json"
    top3 = load_json(top3_path) if top3_path.exists() else None
    top3_ok = 0.0
    if isinstance(top3, list):
        def sort_key(ep_row: dict):
            eid = ep_row['episode_id']
            exp = agg.get(eid, {'plays': 0, 'errors': 0, 'error_rate': 0.0})
            return (-exp['error_rate'], -exp['errors'], eid)

        expected_sorted = sorted(catalog, key=sort_key)
        expected_top = expected_sorted[: min(3, len(expected_sorted))]
        expected_objs = []
        for ep in expected_top:
            eid = ep['episode_id']
            expected_objs.append({
                'episode_id': eid,
                'title': ep['title'],
                'plays': agg.get(eid, {}).get('plays', 0),
                'errors': agg.get(eid, {}).get('errors', 0),
                'error_rate': agg.get(eid, {}).get('error_rate', 0.0),
                'checksum_status': checksum_status_map.get(eid, 'missing')
            })
        if len(top3) == len(expected_objs):
            match_count = 0
            for idx, obj in enumerate(top3):
                exp = expected_objs[idx]
                if not isinstance(obj, dict):
                    continue
                fields = ['episode_id', 'title', 'plays', 'errors', 'error_rate', 'checksum_status']
                if any(k not in obj for k in fields):
                    continue
                try:
                    eid_ok = str(obj['episode_id']) == exp['episode_id']
                    title_ok = str(obj['title']) == exp['title']
                    plays_ok = int(obj['plays']) == exp['plays']
                    errors_ok = int(obj['errors']) == exp['errors']
                    erate_ok = floats_equal(float(obj['error_rate']), exp['error_rate'], tol=1e-9)
                    csum_ok = str(obj['checksum_status']) == exp['checksum_status']
                except Exception:
                    continue
                if eid_ok and title_ok and plays_ok and errors_ok and erate_ok and csum_ok:
                    match_count += 1
            top3_ok = match_count / float(len(expected_objs)) if expected_objs else 0.0
        else:
            top3_ok = 0.0
    scores["top3_content_correct"] = top3_ok

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()