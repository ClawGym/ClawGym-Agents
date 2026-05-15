# Simplified signup handler (for audit only)
import yaml
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent / 'config' / 'app_config.yaml'

with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
    CONFIG = yaml.safe_load(f)

# Fields persisted when saving a consented signup.
# NOTE: consent_text_version is currently NOT persisted.
STORED_FIELDS = [
    'user_id',
    'email',
    'consent_timestamp',
    'ip',
    'double_opt_in_confirmed'
]

def save_consent(record: dict) -> dict:
    """
    Simulate storing a consent record. Only fields in STORED_FIELDS are kept.
    This intentionally does not persist 'consent_text_version'.
    """
    stored = {k: record.get(k) for k in STORED_FIELDS}
    return stored

def is_double_opt_in_enabled() -> bool:
    return bool(CONFIG.get('require_double_opt_in', False))

def is_age_gate_enabled() -> bool:
    return bool(CONFIG.get('enforce_eu_age_limit', False))

def get_unsubscribe_url() -> str:
    return str(CONFIG.get('unsubscribe_url', ''))

def log_ip_enabled() -> bool:
    return bool(CONFIG.get('log_ip', False))
