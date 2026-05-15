import json
import os
import sys

def read_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            # Preserve spaces; strip only newline characters
            return [line.rstrip("\r\n") for line in f.readlines()]
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {
        "answers_json_exists": False,
        "answers_json_valid": False,
        "structure_ok": False,
        "encryption_algorithm_ok": False,
        "supported_cloud_providers_ok": False,
        "chunk_size_change_v1_2_0_ok": False,
        "retention_policy_ok": False,
        "sync_modes_streaming_ok": False,
        "sync_modes_batch_ok": False,
        "incident_2025_03_17_root_cause_ok": False,
    }

    expected = {
        "encryption_algorithm": {
            "quote": "Default encryption algorithm: AES-256-GCM with per-file keys and envelope encryption.",
            "source_path": "input/notes/security.md",
        },
        "supported_cloud_providers": {
            "quote": "Supported cloud providers: AWS, GCP, and Azure.",
            "source_path": "input/notes/deployment.md",
        },
        "chunk_size_change_v1_2_0": {
            "quote": "- Increased default chunk size from 8 MiB to 16 MiB for large file uploads.",
            "source_path": "input/notes/changelog.md",
        },
        "retention_policy": {
            "quote": "A: Deleted files are retained for 30 days and then permanently purged.",
            "source_path": "input/notes/faq.md",
        },
        "sync_modes_streaming": {
            "quote": "Streaming Sync applies changes in near real-time using a persistent WebSocket connection.",
            "source_path": "input/notes/product_overview.md",
        },
        "sync_modes_batch": {
            "quote": "Batch Sync groups changes into 5-minute windows and applies them on schedule.",
            "source_path": "input/notes/product_overview.md",
        },
        "incident_2025_03_17_root_cause": {
            "quote": "Root cause: exhausted Postgres connection pool due to runaway debug queries.",
            "source_path": "input/notes/incidents.md",
        },
    }

    answers_path = os.path.join(output_dir, "answers.json")
    if os.path.isfile(answers_path):
        checks["answers_json_exists"] = True

        try:
            with open(answers_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            checks["answers_json_valid"] = True
        except Exception:
            data = None

        if isinstance(data, dict):
            expected_keys = set(expected.keys())
            data_keys = set(data.keys())

            # Structure requires exactly the specified keys and each entry has only quote and source_path
            structure_ok = (data_keys == expected_keys)
            if structure_ok:
                for k in expected_keys:
                    v = data.get(k)
                    if not isinstance(v, dict):
                        structure_ok = False
                        break
                    if set(v.keys()) != {"quote", "source_path"}:
                        structure_ok = False
                        break
            checks["structure_ok"] = structure_ok

            # Only proceed with per-key checks if structure is ok
            if structure_ok:
                # Verify each quote and source_path matches exactly and that the quote exists as a line in the referenced file
                for key, exp in expected.items():
                    got = data.get(key, {})
                    quote_ok = (got.get("quote") == exp["quote"])
                    path_ok = (got.get("source_path") == exp["source_path"])

                    line_exists = False
                    if path_ok:
                        src_abs = os.path.join(workspace_root, exp["source_path"])
                        lines = read_lines(src_abs)
                        if isinstance(lines, list):
                            line_exists = any(line == exp["quote"] for line in lines)

                    ok = quote_ok and path_ok and line_exists

                    if key == "encryption_algorithm":
                        checks["encryption_algorithm_ok"] = ok
                    elif key == "supported_cloud_providers":
                        checks["supported_cloud_providers_ok"] = ok
                    elif key == "chunk_size_change_v1_2_0":
                        checks["chunk_size_change_v1_2_0_ok"] = ok
                    elif key == "retention_policy":
                        checks["retention_policy_ok"] = ok
                    elif key == "sync_modes_streaming":
                        checks["sync_modes_streaming_ok"] = ok
                    elif key == "sync_modes_batch":
                        checks["sync_modes_batch_ok"] = ok
                    elif key == "incident_2025_03_17_root_cause":
                        checks["incident_2025_03_17_root_cause_ok"] = ok

    # Determine final reward: strict 0/1 scoring as per task specification
    all_items_ok = (
        checks["encryption_algorithm_ok"]
        and checks["supported_cloud_providers_ok"]
        and checks["chunk_size_change_v1_2_0_ok"]
        and checks["retention_policy_ok"]
        and checks["sync_modes_streaming_ok"]
        and checks["sync_modes_batch_ok"]
        and checks["incident_2025_03_17_root_cause_ok"]
    )
    full_success = (
        checks["answers_json_exists"]
        and checks["answers_json_valid"]
        and checks["structure_ok"]
        and all_items_ok
    )
    reward = 1.0 if full_success else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()