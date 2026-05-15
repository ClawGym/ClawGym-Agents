import json
import os
import sys
import re

def read_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def load_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def any_contains(text, substrings):
    return any(s in text for s in substrings)

def get_spec_values(spec):
    # Extract expected fields with robust fallback keys and sensible defaults
    solution = (
        spec.get("solution")
        or spec.get("solution_name")
        or spec.get("solutionPath")
        or spec.get("solution_path")
        or spec.get("solutionFile")
        or "MySolution.sln"
    )
    web_project = (
        spec.get("web_project")
        or spec.get("webProject")
        or spec.get("web")
        or spec.get("webProjectPath")
        or "src/MyWeb/MyWeb.csproj"
    )
    lib_project = (
        spec.get("lib_project")
        or spec.get("library_project")
        or spec.get("libProject")
        or spec.get("libraryProject")
        or spec.get("libProjectPath")
        or "src/MyLib/MyLib.csproj"
    )
    version = (
        spec.get("version")
        or spec.get("package_version")
        or spec.get("packageVersion")
        or spec.get("pkgVersion")
        or "1.2.3"
    )
    return solution, web_project, lib_project, version

def has_parallel_flag(cmd):
    # Accept /m or /m:n
    return bool(re.search(r"\s/m(:\d+)?(\s|$)", cmd))

def restore_locked_ok(text, solution):
    return (
        ("dotnet msbuild" in text)
        and (solution in text)
        and ("/t:Restore" in text)
        and ("RestoreLockedMode=true" in text)
    )

def build_release_ok(text, solution):
    return (
        ("dotnet msbuild" in text)
        and (solution in text)
        and ("/t:Build" in text)
        and ("Configuration=Release" in text)
        and ("Deterministic=true" in text)
        and ("ContinuousIntegrationBuild=true" in text)
        and (has_parallel_flag(text))
    )

def test_trx_ok(text, solution):
    # Must use dotnet test with trx logger and results dir
    return (
        ("dotnet test" in text)
        and (solution in text)
        and ("--results-directory" in text)
        and ("artifacts/testresults" in text)
        and ("--logger" in text)
        and ("trx" in text)  # allow with or without quotes
    )

def publish_linux_ok(text, web_project):
    # Accept PublishDir with or without trailing slash
    publishdir_ok = ("PublishDir=artifacts/publish/linux-x64/" in text) or ("PublishDir=artifacts/publish/linux-x64" in text)
    return (
        ("dotnet msbuild" in text)
        and (web_project in text)
        and ("/t:Publish" in text)
        and ("RuntimeIdentifier=linux-x64" in text)
        and ("SelfContained=true" in text)
        and ("PublishSingleFile=true" in text)
        and publishdir_ok
    )

def pack_lib_ok(text, lib_project, version):
    # Accept PackageOutputPath with or without trailing slash
    pkg_out_ok = ("PackageOutputPath=artifacts/nuget/" in text) or ("PackageOutputPath=artifacts/nuget" in text)
    return (
        ("dotnet msbuild" in text)
        and (lib_project in text)
        and ("/t:Pack" in text)
        and ("Configuration=Release" in text)
        and pkg_out_ok
        and (f"Version={version}" in text)
    )

def contains_binlog(text):
    # At least one /bl (with or without path)
    return "/bl" in text

def find_matching_in_lines(text, predicate):
    # Returns True if any line satisfies the predicate
    for line in text.splitlines():
        if predicate(line):
            return True
    return False

def find_matching_in_list(commands, predicate):
    for cmd in commands:
        if isinstance(cmd, str) and predicate(cmd):
            return True
    return False

def validate_ci_array(ci_path):
    try:
        data = read_json_file(ci_path)
        if not isinstance(data, list):
            return False, []
        if not all(isinstance(x, str) for x in data):
            return False, []
        return True, data
    except Exception:
        return False, []

def count_nonempty_lines(text):
    return sum(1 for l in text.splitlines() if l.strip() != "")

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "build_plan_exists": False,
        "build_plan_restore_locked": False,
        "build_plan_build_release_deterministic_ci_parallel": False,
        "build_plan_test_trx_results": False,
        "build_plan_publish_linux_selfcontained_singlefile": False,
        "build_plan_pack_library": False,
        "build_plan_has_bl": False,
        "ci_commands_exists_and_valid": False,
        "ci_restore_locked": False,
        "ci_build_release_deterministic_ci_parallel": False,
        "ci_test_trx_results": False,
        "ci_publish_linux_selfcontained_singlefile": False,
        "ci_pack_library": False,
        "ci_has_bl": False,
        "notes_exists": False,
        "notes_length_ok": False,
        "notes_min_lines": False,
        "notes_contains_singlefile": False,
        "notes_contains_selfcontained": False,
        "notes_contains_trim": False,
        "notes_contains_readytorun": False,
    }

    # Load spec
    spec_path = os.path.join(input_dir, "solution_spec.json")
    spec = read_json_file(spec_path) or {}
    solution, web_project, lib_project, version = get_spec_values(spec)

    # build_plan.md checks
    build_plan_path = os.path.join(output_dir, "build_plan.md")
    if os.path.isfile(build_plan_path):
        checks["build_plan_exists"] = True
        bp = load_text(build_plan_path)

        # Restore locked
        if find_matching_in_lines(bp, lambda ln: restore_locked_ok(ln, solution)):
            checks["build_plan_restore_locked"] = True

        # Build Release with CI properties and parallelism
        if find_matching_in_lines(bp, lambda ln: build_release_ok(ln, solution)):
            checks["build_plan_build_release_deterministic_ci_parallel"] = True

        # Test with trx and results dir
        if find_matching_in_lines(bp, lambda ln: test_trx_ok(ln, solution)):
            checks["build_plan_test_trx_results"] = True

        # Publish linux-x64 self-contained single-file with publish dir
        if find_matching_in_lines(bp, lambda ln: publish_linux_ok(ln, web_project)):
            checks["build_plan_publish_linux_selfcontained_singlefile"] = True

        # Pack with version and output path
        if find_matching_in_lines(bp, lambda ln: pack_lib_ok(ln, lib_project, version)):
            checks["build_plan_pack_library"] = True

        # At least one /bl binary log
        if contains_binlog(bp):
            checks["build_plan_has_bl"] = True

    # ci_commands.json checks
    ci_path = os.path.join(output_dir, "ci_commands.json")
    if os.path.isfile(ci_path):
        valid_json, cmds = validate_ci_array(ci_path)
        if valid_json and len(cmds) >= 6:
            checks["ci_commands_exists_and_valid"] = True

            if find_matching_in_list(cmds, lambda c: restore_locked_ok(c, solution)):
                checks["ci_restore_locked"] = True

            if find_matching_in_list(cmds, lambda c: build_release_ok(c, solution)):
                checks["ci_build_release_deterministic_ci_parallel"] = True

            if find_matching_in_list(cmds, lambda c: test_trx_ok(c, solution)):
                checks["ci_test_trx_results"] = True

            if find_matching_in_list(cmds, lambda c: publish_linux_ok(c, web_project)):
                checks["ci_publish_linux_selfcontained_singlefile"] = True

            if find_matching_in_list(cmds, lambda c: pack_lib_ok(c, lib_project, version)):
                checks["ci_pack_library"] = True

            if any_contains(" ".join(cmds), ["/bl"]):
                checks["ci_has_bl"] = True

    # notes.txt checks
    notes_path = os.path.join(output_dir, "notes.txt")
    if os.path.isfile(notes_path):
        checks["notes_exists"] = True
        notes = load_text(notes_path)
        if len(notes) <= 2500:
            checks["notes_length_ok"] = True
        if count_nonempty_lines(notes) >= 5:
            checks["notes_min_lines"] = True
        if ("SingleFile" in notes) or ("single-file" in notes):
            checks["notes_contains_singlefile"] = True
        if ("SelfContained" in notes) or ("self-contained" in notes):
            checks["notes_contains_selfcontained"] = True
        if ("PublishTrimmed" in notes) or ("trim" in notes):
            checks["notes_contains_trim"] = True
        if "ReadyToRun" in notes:
            checks["notes_contains_readytorun"] = True

    # Compute reward: average of all checks
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total if total > 0 else 0.0

    # Baseline: if there are no output artifacts, ensure reward is 0
    output_exists = os.path.isdir(output_dir) and any(
        os.path.isfile(os.path.join(output_dir, f)) for f in os.listdir(output_dir)
    )
    if not output_exists:
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()