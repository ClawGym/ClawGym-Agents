import json
import os
import sys

def read_bytes(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except Exception:
        return None

def is_dir(path):
    return os.path.isdir(path)

def list_dirs(path):
    try:
        return [d for d in os.listdir(path) if is_dir(os.path.join(path, d))]
    except Exception:
        return []

def list_files(path):
    try:
        return [f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))]
    except Exception:
        return []

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "correct_backup_set": False,
        "no_oldest_backup": False,
        "subdirs_present": False,
        "config_files_copied_and_match": False,
        "skills_copied_and_match": False,
        "workspace_md_only_and_match": False,
        "memory_md_only_and_match": False,
    }

    # Expected backup directories (after rotation)
    expected_backups = [
        "20240102_120000",
        "20240103_120000",
        "20240104_120000",
        "20240105_120000",
        "20240106_120000",
    ]
    oldest_backup = "20240101_120000"

    backup_base = os.path.join(output_dir, "backup")
    if is_dir(backup_base):
        found_dirs = list_dirs(backup_base)
        # Verify exact set match
        if set(found_dirs) == set(expected_backups) and len(found_dirs) == len(expected_backups):
            checks["correct_backup_set"] = True
        # Verify the oldest backup is not present
        if oldest_backup not in found_dirs:
            checks["no_oldest_backup"] = True

        # Only proceed with deeper checks if the expected backups exist
        if checks["correct_backup_set"]:
            # Check subdirectories presence for each backup
            all_subdirs_ok = True
            for b in expected_backups:
                b_path = os.path.join(backup_base, b)
                cfg = os.path.join(b_path, "config")
                skl = os.path.join(b_path, "skills")
                wsp = os.path.join(b_path, "workspace")
                mem = os.path.join(b_path, "memory")
                if not (is_dir(cfg) and is_dir(skl) and is_dir(wsp) and is_dir(mem)):
                    all_subdirs_ok = False
                    break
            checks["subdirs_present"] = all_subdirs_ok

            # Config files check (byte-identical to inputs)
            cfg_names = ["openclaw.json", "exec-approvals.json", "update-check.json"]
            cfg_input_dir = os.path.join(input_dir, "openclaw", "config")
            all_cfg_ok = True
            for b in expected_backups:
                for name in cfg_names:
                    src = os.path.join(cfg_input_dir, name)
                    dst = os.path.join(backup_base, b, "config", name)
                    src_bytes = read_bytes(src)
                    dst_bytes = read_bytes(dst)
                    if src_bytes is None or dst_bytes is None or src_bytes != dst_bytes:
                        all_cfg_ok = False
                        break
                if not all_cfg_ok:
                    break
            checks["config_files_copied_and_match"] = all_cfg_ok

            # Skills recursive copy check (verify presence and content of key files)
            skills_checks = [
                ("skillA", "skill.json"),
                ("skillA", "README.md"),
                ("skillB", os.path.join("src", "main.py")),
            ]
            skills_input_dir = os.path.join(input_dir, "skills")
            all_skills_ok = True
            for b in expected_backups:
                for parts in skills_checks:
                    rel_path = os.path.join(*parts)
                    src = os.path.join(skills_input_dir, rel_path)
                    dst = os.path.join(backup_base, b, "skills", rel_path)
                    src_bytes = read_bytes(src)
                    dst_bytes = read_bytes(dst)
                    if src_bytes is None or dst_bytes is None or src_bytes != dst_bytes:
                        all_skills_ok = False
                        break
                if not all_skills_ok:
                    break
            checks["skills_copied_and_match"] = all_skills_ok

            # Workspace .md only from root (AGENTS.md, README.md) and byte-identical
            workspace_input_dir = os.path.join(input_dir, "workspace")
            required_workspace_files = {"AGENTS.md", "README.md"}
            all_workspace_ok = True
            for b in expected_backups:
                wdir = os.path.join(backup_base, b, "workspace")
                if not is_dir(wdir):
                    all_workspace_ok = False
                    break
                found_files = set(list_files(wdir))
                # Must be exactly the two markdown files
                if found_files != required_workspace_files:
                    all_workspace_ok = False
                    break
                # Compare contents
                for fname in required_workspace_files:
                    src = os.path.join(workspace_input_dir, fname)
                    dst = os.path.join(wdir, fname)
                    src_bytes = read_bytes(src)
                    dst_bytes = read_bytes(dst)
                    if src_bytes is None or dst_bytes is None or src_bytes != dst_bytes:
                        all_workspace_ok = False
                        break
                if not all_workspace_ok:
                    break
            checks["workspace_md_only_and_match"] = all_workspace_ok

            # Memory .md only from input/workspace/memory (session1.md only), byte-identical
            memory_input_dir = os.path.join(input_dir, "workspace", "memory")
            required_memory_files = {"session1.md"}
            all_memory_ok = True
            for b in expected_backups:
                mdir = os.path.join(backup_base, b, "memory")
                if not is_dir(mdir):
                    all_memory_ok = False
                    break
                found_files = set(list_files(mdir))
                if found_files != required_memory_files:
                    all_memory_ok = False
                    break
                for fname in required_memory_files:
                    src = os.path.join(memory_input_dir, fname)
                    dst = os.path.join(mdir, fname)
                    src_bytes = read_bytes(src)
                    dst_bytes = read_bytes(dst)
                    if src_bytes is None or dst_bytes is None or src_bytes != dst_bytes:
                        all_memory_ok = False
                        break
                if not all_memory_ok:
                    break
            checks["memory_md_only_and_match"] = all_memory_ok

    # Reward calculation:
    # Enforce no-op baseline to yield 0.0 if required artifacts are missing.
    # Grant 1.0 only if all checks pass; otherwise 0.0.
    all_pass = all(checks.values())
    reward = 1.0 if all_pass else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()