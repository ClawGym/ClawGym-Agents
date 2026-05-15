import json
import os
import sys

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text_file(path):
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

    # Expected output files (top-level under output/)
    expected_files = {
        "preview.txt",
        "status.json",
        "cached.txt",
        "post_exorcise.json",
    }

    # Initialize checks (artifact dependent initialized False)
    checks = {
        "files_exist": False,
        "no_extra_files": False,
        "preview_has_required_substrings": False,
        "status_json_keys_ok": False,
        "status_json_values_ok": False,
        "cached_txt_has_entry": False,
        "post_exorcise_json_keys_ok": False,
        "post_exorcise_json_values_ok": False,
    }

    # If output directory missing, everything remains False and reward will be 0.0
    if os.path.isdir(output_dir):
        # Collect all files under output/ (recursive) as relative paths from output/
        all_output_files = []
        for root, dirs, files in os.walk(output_dir):
            for fname in files:
                full_path = os.path.join(root, fname)
                rel_path = os.path.relpath(full_path, output_dir)
                # Normalize to POSIX style for comparison
                rel_path_norm = rel_path.replace("\\", "/")
                all_output_files.append(rel_path_norm)

        # files_exist: all required files exist at top-level (no subdirectories)
        top_level_paths = {name: os.path.join(output_dir, name) for name in expected_files}
        if all(os.path.isfile(p) for p in top_level_paths.values()):
            checks["files_exist"] = True

        # no_extra_files: exactly the four expected files and nothing else anywhere under output/
        if set(all_output_files) == expected_files:
            checks["no_extra_files"] = True

        # Check preview.txt
        preview_path = top_level_paths.get("preview.txt")
        if preview_path and os.path.isfile(preview_path):
            content = read_text_file(preview_path)
            if isinstance(content, str):
                text = content
                if len(text.strip()) > 0 and ("dry-run" in text) and ("input/SOUL.md" in text):
                    checks["preview_has_required_substrings"] = True

        # Check status.json structure and values
        status_path = top_level_paths.get("status.json")
        if status_path and os.path.isfile(status_path):
            data = load_json_file(status_path)
            if isinstance(data, dict):
                required_keys = {"active_name", "source", "soul_path", "possessed"}
                if set(data.keys()) == required_keys:
                    checks["status_json_keys_ok"] = True
                    # Validate required values and types
                    active_ok = isinstance(data.get("active_name"), str) and data.get("active_name") == "The Friendly Curator"
                    source_ok = isinstance(data.get("source"), str) and data.get("source") == "local"
                    path_ok = isinstance(data.get("soul_path"), str) and data.get("soul_path") == "input/SOUL.md"
                    possessed_ok = isinstance(data.get("possessed"), bool) and data.get("possessed") is True
                    if active_ok and source_ok and path_ok and possessed_ok:
                        checks["status_json_values_ok"] = True

        # Check cached.txt
        cached_path = top_level_paths.get("cached.txt")
        if cached_path and os.path.isfile(cached_path):
            content = read_text_file(cached_path)
            if isinstance(content, str):
                text = content
                if len(text.strip()) > 0 and ("The Friendly Curator" in text or "input/SOUL.md" in text):
                    checks["cached_txt_has_entry"] = True

        # Check post_exorcise.json
        post_path = top_level_paths.get("post_exorcise.json")
        if post_path and os.path.isfile(post_path):
            data = load_json_file(post_path)
            if isinstance(data, dict):
                required_keys = {"possessed", "previous_active"}
                if set(data.keys()) == required_keys:
                    checks["post_exorcise_json_keys_ok"] = True
                    possessed_ok = isinstance(data.get("possessed"), bool) and data.get("possessed") is False
                    prev_ok = isinstance(data.get("previous_active"), str) and data.get("previous_active") == "The Friendly Curator"
                    if possessed_ok and prev_ok:
                        checks["post_exorcise_json_values_ok"] = True

    # Compute reward as fraction of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure baseline no-op (no output dir or missing files) yields 0.0: already satisfied by checks all False
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()