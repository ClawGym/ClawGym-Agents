import json
import os
import sys
from datetime import datetime

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks - all False until positively verified
    checks = {
        "backup_exists": False,
        "backup_identical": False,
        "sanitized_exists": False,
        "sanitized_valid_json": False,
        "identity_name_preserved": False,
        "last_updated_changed": False,
        "sanitized_no_sensitive_tokens": False,
        "contacts_unique_names": False,
        "david_kim_exists_once": False,
        "david_kim_aliases_have_dk_and_dave": False,
        "episodic_removed_2025_08_10": False,
        "episodic_kept_2025_09_01": False,
        "episodic_contains_memory_hygiene_entry": False,
        "conflicts_exists": False,
        "conflicts_valid_json_array": False,
        "conflicts_has_alex_tone": False,
        "ambiguities_exists": False,
        "ambiguities_valid_json_object": False,
        "ambiguities_duplicate_names_contains_david_kim": False,
        "ambiguities_alias_david_maps_to_two": False,
    }

    # Paths
    input_profile_path = os.path.join(input_dir, "user_profile.json")
    backup_path = os.path.join(output_dir, "backup_original.json")
    sanitized_path = os.path.join(output_dir, "sanitized_profile.json")
    conflicts_path = os.path.join(output_dir, "conflicts.json")
    ambiguities_path = os.path.join(output_dir, "ambiguities.json")

    # Load input profile (reference)
    input_profile = load_json(input_profile_path)

    # 1) Backup check
    if os.path.isfile(backup_path):
        checks["backup_exists"] = True
        # Compare bytes to ensure verbatim match
        try:
            with open(input_profile_path, "rb") as f_in, open(backup_path, "rb") as f_out:
                in_bytes = f_in.read()
                out_bytes = f_out.read()
                if in_bytes == out_bytes and len(in_bytes) > 0:
                    checks["backup_identical"] = True
        except Exception:
            pass

    # 2) Sanitized profile checks
    sanitized_json = None
    if os.path.isfile(sanitized_path):
        checks["sanitized_exists"] = True
        sanitized_text = read_text(sanitized_path)
        sanitized_json = load_json(sanitized_path)
        if sanitized_json is not None:
            checks["sanitized_valid_json"] = True

            # identity.name preservation
            try:
                input_name = None
                if isinstance(input_profile, dict):
                    input_name = input_profile.get("identity", {}).get("name", None)
                san_name = sanitized_json.get("identity", {}).get("name", None)
                if input_name is not None and san_name == input_name:
                    checks["identity_name_preserved"] = True
            except Exception:
                pass

            # meta.last_updated changed
            try:
                input_last = None
                if isinstance(input_profile, dict):
                    input_last = input_profile.get("meta", {}).get("last_updated", None)
                san_last = sanitized_json.get("meta", {}).get("last_updated", None)
                if san_last is not None and san_last != input_last:
                    checks["last_updated_changed"] = True
            except Exception:
                pass

            # sensitive tokens not present anywhere in sanitized file
            if isinstance(sanitized_text, str):
                lowered = sanitized_text.lower()
                forbidden = ["secrets", "password", "api_key", "bank_pin"]
                if not any(tok in lowered for tok in forbidden):
                    checks["sanitized_no_sensitive_tokens"] = True

            # Contacts unique names and specific David Kim requirements
            try:
                contacts = sanitized_json.get("relationships", {}).get("contacts", [])
                if isinstance(contacts, list) and len(contacts) > 0:
                    names = [c.get("name") for c in contacts if isinstance(c, dict)]
                    if all(isinstance(n, str) for n in names):
                        if len(names) == len(set(names)):
                            checks["contacts_unique_names"] = True
                    # Exactly one David Kim
                    david_kim_count = sum(1 for n in names if n == "David Kim")
                    if david_kim_count == 1:
                        checks["david_kim_exists_once"] = True
                        # Check aliases for David Kim
                        dk_contact = next((c for c in contacts if c.get("name") == "David Kim"), None)
                        if dk_contact is not None:
                            aliases = dk_contact.get("alias", []) or dk_contact.get("aliases", [])
                            # normalize aliases list
                            if isinstance(aliases, list):
                                alias_lower = {str(a).strip().lower() for a in aliases if a is not None}
                                if "dk" in alias_lower and "dave" in alias_lower:
                                    checks["david_kim_aliases_have_dk_and_dave"] = True
            except Exception:
                pass

            # Episodic checks
            try:
                episodic = sanitized_json.get("episodic", [])
                if isinstance(episodic, list):
                    dates = []
                    has_memory_hygiene = False
                    for e in episodic:
                        if not isinstance(e, dict):
                            continue
                        d = e.get("date")
                        if isinstance(d, str):
                            dates.append(d)
                        tags = e.get("tags", [])
                        if isinstance(tags, list):
                            tag_lower = {str(t).strip().lower() for t in tags if t is not None}
                            if "memory-hygiene" in tag_lower:
                                has_memory_hygiene = True
                    # Must not include 2025-08-10
                    if "2025-08-10" not in dates:
                        checks["episodic_removed_2025_08_10"] = True
                    # Must include 2025-09-01
                    if "2025-09-01" in dates:
                        checks["episodic_kept_2025_09_01"] = True
                    # Must include new memory-hygiene tag
                    if has_memory_hygiene:
                        checks["episodic_contains_memory_hygiene_entry"] = True
            except Exception:
                pass

    # 3) conflicts.json checks
    conflicts_json = None
    if os.path.isfile(conflicts_path):
        checks["conflicts_exists"] = True
        conflicts_json = load_json(conflicts_path)
        if isinstance(conflicts_json, list):
            checks["conflicts_valid_json_array"] = True
            # Look for an entry referencing Alex Rivera and email tone
            found_alex_tone = False
            for entry in conflicts_json:
                try:
                    # Serialize entry to string for searching
                    entry_str = json.dumps(entry, ensure_ascii=False).lower()
                    # Check name and tone field/value
                    has_alex = "alex rivera" in entry_str
                    has_tone = ("email_tone" in entry_str) or (" tone" in entry_str) or ("tone" in entry_str)
                    if has_alex and has_tone:
                        found_alex_tone = True
                        break
                except Exception:
                    continue
            if found_alex_tone:
                checks["conflicts_has_alex_tone"] = True

    # 4) ambiguities.json checks
    ambiguities_json = None
    if os.path.isfile(ambiguities_path):
        checks["ambiguities_exists"] = True
        ambiguities_json = load_json(ambiguities_path)
        if isinstance(ambiguities_json, dict):
            checks["ambiguities_valid_json_object"] = True
            dup_names = ambiguities_json.get("duplicate_names")
            amb_aliases = ambiguities_json.get("ambiguous_aliases")
            # duplicate_names contains "David Kim"
            try:
                if isinstance(dup_names, list):
                    if any(str(x) == "David Kim" for x in dup_names):
                        checks["ambiguities_duplicate_names_contains_david_kim"] = True
            except Exception:
                pass
            # ambiguous_aliases: key "David" value includes "David Kim" and "David Okafor"
            try:
                if isinstance(amb_aliases, dict) and "David" in amb_aliases:
                    val = amb_aliases.get("David")
                    if isinstance(val, list):
                        names_set = {str(x) for x in val}
                        if "David Kim" in names_set and "David Okafor" in names_set:
                            checks["ambiguities_alias_david_maps_to_two"] = True
            except Exception:
                pass

    # Compute reward: fraction of passed checks
    # Only count checks that depend on outputs; all defined checks already do.
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed_checks > 0:
        reward = passed_checks / total_checks
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0

    # Baseline: if no required artifacts exist, ensure 0.0
    # If output dir missing or empty of our four files and no checks passed, reward stays 0.0.
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()