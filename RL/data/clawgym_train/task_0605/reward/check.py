import json
import os
import re
import sys
import base64
import hashlib
from datetime import datetime, timezone

def parse_iso8601_utc(dt_str: str):
    # Accept ISO 8601 with Z or +00:00, normalize to aware UTC datetime
    s = dt_str.strip()
    if s.endswith("Z"):
        try:
            # Replace Z with +00:00 for fromisoformat
            return datetime.fromisoformat(s[:-1] + "+00:00")
        except Exception:
            pass
    try:
        dt = datetime.fromisoformat(s)
        # If offset-aware, convert to UTC
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc)
        # If naive, treat as UTC
        return dt.replace(tzinfo=timezone.utc)
    except Exception:
        # Fallback attempts for common patterns
        patterns = [
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d %H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
        ]
        for p in patterns:
            try:
                dt = datetime.strptime(s, p)
                return dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue
    raise ValueError(f"Invalid ISO 8601 datetime: {dt_str}")

def is_uuid_v4(s: str) -> bool:
    if not isinstance(s, str):
        return False
    pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    return re.match(pattern, s, flags=re.IGNORECASE) is not None

def lower_hex_digest(algorithm: str, data: bytes) -> str:
    h = hashlib.new(algorithm)
    h.update(data)
    return h.hexdigest()

def safe_read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def count_newlines(s: str) -> int:
    return s.count("\n") if isinstance(s, str) else 0

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "users_json_exists": False,
        "users_json_valid": False,
        "users_json_is_array_of_3": False,
        "users_json_required_fields": False,
        "users_json_uuid_v4_all_valid": False,
        "users_json_email_b64_matches": False,
        "users_json_password_sha256_valid": False,
        "users_json_md5_valid": False,
        "users_json_sha512_valid": False,
        "users_json_created_at_iso_z": False,
        "users_json_created_at_unix_matches": False,
        "users_min_json_exists": False,
        "users_min_json_valid": False,
        "users_min_json_structural_equality": False,
        "users_min_file_smaller": False,
        "users_min_one_line_preferred": False,
        "html_exists": False,
        "html_has_h1_tag": False,
        "html_has_required_h1_text": False,
        "readme_exists": False,
        "readme_has_keywords": False,
        "readme_has_user_count_digit": False,
    }

    # Paths
    users_pretty_path = os.path.join(output_dir, "users_with_ids.json")
    users_min_path = os.path.join(output_dir, "users_with_ids.min.json")
    announcement_html_path = os.path.join(output_dir, "announcement.html")
    readme_path = os.path.join(output_dir, "README.md")

    # 1) users_with_ids.json
    users_data = None
    if os.path.isfile(users_pretty_path):
        checks["users_json_exists"] = True
        txt = safe_read_text(users_pretty_path)
        if txt is not None:
            try:
                users_data = json.loads(txt)
                checks["users_json_valid"] = isinstance(users_data, list)
            except Exception:
                checks["users_json_valid"] = False

    if checks["users_json_valid"]:
        # Must be array of exactly 3 objects
        if isinstance(users_data, list) and len(users_data) == 3 and all(isinstance(x, dict) for x in users_data):
            checks["users_json_is_array_of_3"] = True

        required_fields = {
            "id",
            "name",
            "email",
            "email_b64",
            "password_plain",
            "password_sha256",
            "fingerprint_md5",
            "fingerprint_sha512",
            "created_at_iso",
            "created_at_unix",
        }

        all_have_fields = True
        all_uuid_v4 = True
        all_email_b64_ok = True
        all_sha256_ok = True
        all_md5_ok = True
        all_sha512_ok = True
        all_iso_end_z = True
        all_unix_match = True

        if checks["users_json_is_array_of_3"]:
            for obj in users_data:
                # Fields presence
                if not required_fields.issubset(set(obj.keys())):
                    all_have_fields = False

                # UUID v4
                if not is_uuid_v4(obj.get("id")):
                    all_uuid_v4 = False

                # email_b64
                email = obj.get("email")
                email_b64 = obj.get("email_b64")
                try:
                    decoded = base64.b64decode(email_b64.encode("utf-8"), validate=True).decode("utf-8")
                    if decoded != email:
                        all_email_b64_ok = False
                except Exception:
                    all_email_b64_ok = False

                # password_sha256 of "onboard2026:" + password_plain
                password_plain = obj.get("password_plain", "")
                salted = ("onboard2026:" + str(password_plain)).encode("utf-8")
                sha256_hex = lower_hex_digest("sha256", salted)
                if obj.get("password_sha256") != sha256_hex:
                    all_sha256_ok = False

                # fingerprints of "<name>|<email>"
                name = obj.get("name", "")
                concat = f"{name}|{email}".encode("utf-8")
                md5_hex = lower_hex_digest("md5", concat)
                sha512_hex = lower_hex_digest("sha512", concat)
                if obj.get("fingerprint_md5") != md5_hex:
                    all_md5_ok = False
                if obj.get("fingerprint_sha512") != sha512_hex:
                    all_sha512_ok = False

                # created_at iso and unix
                created_at_iso = obj.get("created_at_iso")
                created_at_unix = obj.get("created_at_unix")
                # must end with 'Z'
                if not (isinstance(created_at_iso, str) and created_at_iso.endswith("Z")):
                    all_iso_end_z = False
                # parse and compare unix seconds
                try:
                    dt = parse_iso8601_utc(created_at_iso)
                    unix_expected = int(dt.timestamp())
                    # ensure integer type
                    if not isinstance(created_at_unix, int):
                        all_unix_match = False
                    else:
                        if created_at_unix != unix_expected:
                            all_unix_match = False
                except Exception:
                    all_unix_match = False

        checks["users_json_required_fields"] = all_have_fields
        checks["users_json_uuid_v4_all_valid"] = all_uuid_v4
        checks["users_json_email_b64_matches"] = all_email_b64_ok
        checks["users_json_password_sha256_valid"] = all_sha256_ok
        checks["users_json_md5_valid"] = all_md5_ok
        checks["users_json_sha512_valid"] = all_sha512_ok
        checks["users_json_created_at_iso_z"] = all_iso_end_z
        checks["users_json_created_at_unix_matches"] = all_unix_match

    # 2) users_with_ids.min.json
    min_text = None
    min_data = None
    if os.path.isfile(users_min_path):
        checks["users_min_json_exists"] = True
        min_text = safe_read_text(users_min_path)
        if min_text is not None:
            try:
                min_data = json.loads(min_text)
                checks["users_min_json_valid"] = True
            except Exception:
                checks["users_min_json_valid"] = False

    if checks["users_json_valid"] and checks["users_min_json_valid"]:
        # Structural equality
        try:
            checks["users_min_json_structural_equality"] = (min_data == users_data)
        except Exception:
            checks["users_min_json_structural_equality"] = False

        # Minified file smaller
        try:
            pretty_size = os.path.getsize(users_pretty_path)
            min_size = os.path.getsize(users_min_path)
            checks["users_min_file_smaller"] = (min_size < pretty_size)
        except Exception:
            checks["users_min_file_smaller"] = False

        # One-line preferred: at most 2 newlines
        try:
            nl_count = count_newlines(min_text)
            checks["users_min_one_line_preferred"] = (nl_count <= 2)
        except Exception:
            checks["users_min_one_line_preferred"] = False

    # 3) announcement.html
    if os.path.isfile(announcement_html_path):
        checks["html_exists"] = True
        html = safe_read_text(announcement_html_path) or ""
        if "<h1" in html:
            checks["html_has_h1_tag"] = True
        # Require <h1> text "April Onboarding Announcement"
        h1_pattern = re.compile(r"<h1[^>]*>\s*April Onboarding Announcement\s*</h1>")
        if h1_pattern.search(html) is not None:
            checks["html_has_required_h1_text"] = True

    # 4) README.md
    if os.path.isfile(readme_path):
        checks["readme_exists"] = True
        readme = safe_read_text(readme_path) or ""
        rl = readme.lower()
        has_keywords = all([
            "sha256" in rl,
            "md5" in rl,
            "sha512" in rl,
            "base64" in rl,
            "uuid v4" in rl,
            "onboard2026:" in readme,  # exact salt string
        ])
        checks["readme_has_keywords"] = has_keywords
        checks["readme_has_user_count_digit"] = ("3" in readme)

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks

    # Output JSON
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()