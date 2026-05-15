import json
import os
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def file_exists(path):
    return os.path.isfile(path)

def contains_all(content, substrings, case_insensitive=True):
    data = content.lower() if case_insensitive else content
    for s in substrings:
        s_cmp = s.lower() if case_insensitive else s
        if s_cmp not in data:
            return False
    return True

def any_contains(content, substrings, case_insensitive=True):
    data = content.lower() if case_insensitive else content
    for s in substrings:
        s_cmp = s.lower() if case_insensitive else s
        if s_cmp in data:
            return True
    return False

def collect_py_files(root_dir):
    py_files = []
    for base, _, files in os.walk(root_dir):
        for n in files:
            if n.endswith(".py"):
                py_files.append(os.path.join(base, n))
    return py_files

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # Review checks
        "review_exists": False,
        "review_has_async_and_asyncmock": False,
        "review_has_parametrize_and_ids": False,
        "review_has_fixture_and_try_finally": False,
        "review_has_patch_and_where_used": False,
        # test_user_service.py checks
        "user_service_exists": False,
        "user_service_has_mark_asyncio": False,
        "user_service_has_async_def": False,
        "user_service_uses_asyncmock": False,
        "user_service_no_regular_mock_usage": False,
        "user_service_has_await": False,
        "user_service_verifies_mock_calls_precisely": False,
        "user_service_parametrize_with_ids": False,
        "user_service_no_private_helper_patch": False,
        # test_patching.py checks
        "patching_exists": False,
        "patching_correct_target": False,
        "patching_uses_mocker_or_patch": False,
        # conftest.py checks
        "conftest_exists": False,
        "conftest_has_async_fixture": False,
        "conftest_async_fixture_has_try_finally_yield": False,
        "conftest_has_explicit_scope": False,
        "conftest_no_autouse": False,
        # Global negative check
        "global_no_regular_mock_usage": False,
    }

    # Paths
    review_path = os.path.join(output_dir, "review.md")
    user_service_path = os.path.join(output_dir, "tests", "test_user_service.py")
    patching_path = os.path.join(output_dir, "tests", "test_patching.py")
    conftest_path = os.path.join(output_dir, "tests", "conftest.py")
    output_tests_dir = os.path.join(output_dir, "tests")

    # Review checks
    if file_exists(review_path):
        checks["review_exists"] = True
        review_content = read_text(review_path)
        # async + AsyncMock (case-insensitive)
        if contains_all(review_content, ["async", "asyncmock"]):
            checks["review_has_async_and_asyncmock"] = True
        # parametrize + ids or id=
        if "parametrize" in review_content.lower() and (("ids" in review_content.lower()) or ("id=" in review_content.lower())):
            checks["review_has_parametrize_and_ids"] = True
        # fixture + try/finally
        if contains_all(review_content, ["fixture", "try/finally"]):
            checks["review_has_fixture_and_try_finally"] = True
        # patch + where used
        if contains_all(review_content, ["patch", "where used"]):
            checks["review_has_patch_and_where_used"] = True

    # test_user_service.py checks
    if file_exists(user_service_path):
        checks["user_service_exists"] = True
        us_content = read_text(user_service_path)
        us_lower = us_content.lower()
        if "@pytest.mark.asyncio" in us_content:
            checks["user_service_has_mark_asyncio"] = True
        if "async def test_" in us_content:
            checks["user_service_has_async_def"] = True
        if "AsyncMock" in us_content:
            checks["user_service_uses_asyncmock"] = True
        # Ensure no regular Mock usage patterns
        no_from_mock = "from unittest.mock import Mock" not in us_content
        no_call_mock = " Mock(" not in us_content
        checks["user_service_no_regular_mock_usage"] = no_from_mock and no_call_mock
        if "await " in us_content:
            checks["user_service_has_await"] = True
        if "assert_called_once_with(" in us_content:
            checks["user_service_verifies_mock_calls_precisely"] = True
        if ("@pytest.mark.parametrize(" in us_content) and ("pytest.param(" in us_content) and ("id=" in us_content):
            checks["user_service_parametrize_with_ids"] = True
        # No patching of private helper (no substring)
        if "_validate_email" not in us_content:
            checks["user_service_no_private_helper_patch"] = True

    # test_patching.py checks
    if file_exists(patching_path):
        checks["patching_exists"] = True
        patch_content = read_text(patching_path)
        # correct patch target where used
        if "module_b.external_api_call" in patch_content:
            checks["patching_correct_target"] = True
        # uses mocker.patch or patch with target
        uses_mocker = "mocker.patch(" in patch_content
        uses_patch_with_target = ("patch(" in patch_content) and ("module_b.external_api_call" in patch_content)
        if uses_mocker or uses_patch_with_target:
            checks["patching_uses_mocker_or_patch"] = True

    # conftest.py checks
    if file_exists(conftest_path):
        checks["conftest_exists"] = True
        cf_content = read_text(conftest_path)
        if ("@pytest.fixture" in cf_content) and ("async def" in cf_content):
            checks["conftest_has_async_fixture"] = True
        if ("try:" in cf_content) and ("finally:" in cf_content) and ("yield" in cf_content):
            checks["conftest_async_fixture_has_try_finally_yield"] = True
        if "scope=" in cf_content:
            checks["conftest_has_explicit_scope"] = True
        if "autouse=True" not in cf_content:
            checks["conftest_no_autouse"] = True

    # Global negative check across all files in output/tests/
    global_no_mock = True
    if os.path.isdir(output_tests_dir):
        for py_file in collect_py_files(output_tests_dir):
            content = read_text(py_file)
            if ("from unittest.mock import Mock" in content) or (" Mock(" in content):
                global_no_mock = False
                break
        checks["global_no_regular_mock_usage"] = global_no_mock
    else:
        # If tests dir missing, keep False (no-op baseline)
        checks["global_no_regular_mock_usage"] = False

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks

    # No-op baseline: if output directory missing or empty and required artifacts absent, ensure reward 0.0
    # If none of the file-existence checks are true, force 0
    existence_flags = [
        checks["review_exists"],
        checks["user_service_exists"],
        checks["patching_exists"],
        checks["conftest_exists"],
    ]
    if not any(existence_flags):
        reward = 0.0

    result = {"reward": round(reward, 6)}
    # Preserve insertion order with reward first
    result.update(checks)

    print(json.dumps(result))

if __name__ == "__main__":
    main()