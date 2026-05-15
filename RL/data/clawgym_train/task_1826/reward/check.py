import json
import os
import re
import sys

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    secrets_path = os.path.join(output_dir, "secrets.json")
    commands_path = os.path.join(output_dir, "commands.md")
    policy_path = os.path.join(input_dir, "secret_requirements.json")

    # Initialize checks (all False until verified)
    checks = {
        "secrets_file_exists": False,
        "commands_file_exists": False,
        "secrets_json_valid": False,
        "admin_password_format": False,
        "api_key_format": False,
        "session_token_format": False,
        "values_unique": False,
        "commands_admin_password": False,
        "commands_api_key": False,
        "commands_session_token": False,
    }

    # Load policy if present (reference only; does not contribute to reward directly)
    policy = None
    try:
        if os.path.isfile(policy_path):
            with open(policy_path, "r", encoding="utf-8") as f:
                policy = json.load(f)
    except Exception:
        policy = None  # Ignore policy parsing errors for scoring purposes

    # Check secrets.json
    secrets_data = None
    if os.path.isfile(secrets_path):
        checks["secrets_file_exists"] = True
        try:
            with open(secrets_path, "r", encoding="utf-8") as f:
                secrets_data = json.load(f)
            # Validate structure: exactly three keys: ADMIN_PASSWORD, API_KEY, SESSION_TOKEN
            if isinstance(secrets_data, dict):
                keys = set(secrets_data.keys())
                if keys == {"ADMIN_PASSWORD", "API_KEY", "SESSION_TOKEN"}:
                    checks["secrets_json_valid"] = True
        except Exception:
            secrets_data = None

    # Validate secret formats only if structure valid
    if checks["secrets_json_valid"]:
        admin_password = secrets_data.get("ADMIN_PASSWORD", "")
        api_key = secrets_data.get("API_KEY", "")
        session_token = secrets_data.get("SESSION_TOKEN", "")

        # ADMIN_PASSWORD: alphanumeric only, exactly 32 chars
        if isinstance(admin_password, str):
            if re.fullmatch(r"[A-Za-z0-9]{32}", admin_password or ""):
                checks["admin_password_format"] = True

        # API_KEY: lowercase hex, 64 chars
        if isinstance(api_key, str):
            if re.fullmatch(r"[0-9a-f]{64}", api_key or ""):
                checks["api_key_format"] = True

        # SESSION_TOKEN: base64 URL-safe (A-Za-z0-9_-), exactly 64 chars, no '='
        if isinstance(session_token, str):
            if re.fullmatch(r"[A-Za-z0-9_-]{64}", session_token or "") and ("=" not in session_token):
                checks["session_token_format"] = True

        # All three values must be unique
        vals = [admin_password, api_key, session_token]
        if all(isinstance(v, str) for v in vals) and len(set(vals)) == 3:
            checks["values_unique"] = True

    # Check commands.md
    if os.path.isfile(commands_path):
        checks["commands_file_exists"] = True
        try:
            with open(commands_path, "r", encoding="utf-8") as f:
                lines = [line.rstrip("\n") for line in f.readlines()]
        except Exception:
            lines = []

        def line_has_required(prefix_name: str, required_substrings):
            # Require a single line that starts with the secret name and contains all substrings
            pattern = r"^\s*" + re.escape(prefix_name) + r"\b"
            for line in lines:
                if re.search(pattern, line):
                    if all(sub in line for sub in required_substrings):
                        return True
            return False

        # ADMIN_PASSWORD: must include "openssl rand -base64", "tr -dc 'a-zA-Z0-9'", "head -c 32"
        checks["commands_admin_password"] = line_has_required(
            "ADMIN_PASSWORD",
            ["openssl rand -base64", "tr -dc 'a-zA-Z0-9'", "head -c 32"]
        )

        # API_KEY: must include "openssl rand -hex 32"
        checks["commands_api_key"] = line_has_required(
            "API_KEY",
            ["openssl rand -hex 32"]
        )

        # SESSION_TOKEN: must include "openssl rand -base64 48", "tr '+/' '-_'", "tr -d '='"
        checks["commands_session_token"] = line_has_required(
            "SESSION_TOKEN",
            ["openssl rand -base64 48", "tr '+/' '-_'", "tr -d '='"]
        )

    # Compute reward as fraction of checks passed (only those dependent on output/)
    # Baseline: if no outputs, reward must be 0.0
    dependent_checks = [
        "secrets_file_exists",
        "commands_file_exists",
        "secrets_json_valid",
        "admin_password_format",
        "api_key_format",
        "session_token_format",
        "values_unique",
        "commands_admin_password",
        "commands_api_key",
        "commands_session_token",
    ]
    passed = sum(1 for k in dependent_checks if checks[k])
    total = len(dependent_checks)
    reward = 0.0
    if total > 0:
        reward = passed / total

    # Ensure exact one JSON object printed on last non-empty stdout line
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()