import csv
import datetime as _dt
from typing import List, Dict, Tuple, Any

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None


def _parse_date(value: Any):
    if value is None:
        return None
    if isinstance(value, _dt.date):
        return value
    s = str(value).strip()
    if not s:
        return None
    # Expect ISO format YYYY-MM-DD
    try:
        return _dt.date.fromisoformat(s)
    except Exception:
        return None


def load_rules(path: str) -> Dict[str, Any]:
    if yaml is None:
        raise RuntimeError("pyyaml is required")
    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    return data


def load_fieldmap(path: str) -> Dict[str, str]:
    if yaml is None:
        raise RuntimeError("pyyaml is required")
    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    mapping = data.get('columns') or {}
    return mapping


def parse_roster(csv_path: str, fieldmap_path: str) -> List[Dict[str, Any]]:
    mapping = load_fieldmap(fieldmap_path)
    records: List[Dict[str, Any]] = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rec: Dict[str, Any] = {}
            for src_col, norm_key in mapping.items():
                raw = (row.get(src_col) or '').strip()
                if norm_key == 'hours_q1':
                    try:
                        rec[norm_key] = float(raw)
                    except Exception:
                        rec[norm_key] = 0.0
                elif norm_key == 'bg_check_date':
                    rec[norm_key] = _parse_date(raw)
                else:
                    rec[norm_key] = raw
            # Ensure all expected keys exist even if missing in CSV
            for k in ['name', 'email', 'unit', 'rank', 'hours_q1', 'bg_check_date']:
                rec.setdefault(k, '' if k not in ('hours_q1', 'bg_check_date') else (0.0 if k == 'hours_q1' else None))
            records.append(rec)
    return records


def _is_email_valid(email: str) -> bool:
    if not email or not isinstance(email, str):
        return False
    s = email.strip()
    if not s:
        return False
    # Simple heuristic: must contain '@' and a dot after the '@'
    if '@' not in s:
        return False
    user, _, domain = s.partition('@')
    return bool(user and domain and ('.' in domain))


def classify(vol: Dict[str, Any], rules: Dict[str, Any]) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    min_hours = float(rules.get('min_hours', 0))
    valid_years = int(rules.get('bg_check_valid_years', 0))
    ref = rules.get('reference_date')
    if isinstance(ref, str):
        reference_date = _parse_date(ref)
    elif isinstance(ref, _dt.date):
        reference_date = ref
    else:
        reference_date = _dt.date.today()

    hours = float(vol.get('hours_q1') or 0)
    email = (vol.get('email') or '').strip()
    bg_date = vol.get('bg_check_date')

    if not email:
        reasons.append('missing_email')
    elif not _is_email_valid(email):
        reasons.append('invalid_email')

    if hours < min_hours:
        reasons.append('low_hours')

    if not isinstance(bg_date, _dt.date):
        reasons.append('expired_bg_check')
    else:
        max_age_days = valid_years * 365
        age_days = (reference_date - bg_date).days
        if age_days > max_age_days:
            reasons.append('expired_bg_check')

    active = len(reasons) == 0
    return active, sorted(set(reasons))
