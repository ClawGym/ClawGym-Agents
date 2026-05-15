import json
import os
import sys

def read_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    output_dir = os.path.join(workspace_root, "output")

    # Initialize checks (all False until verified)
    checks = {
        # Existence checks
        "main_py_exists": False,
        "models_py_exists": False,
        "deps_py_exists": False,
        "tests_exists": False,
        "arch_exists": False,

        # main.py content checks
        "main_has_lifespan_asynccontextmanager": False,
        "main_uses_app_state": False,
        "main_has_post_201": False,
        "main_has_plain_text_response": False,
        "main_uses_backgroundtasks": False,
        "main_no_time_sleep": False,
        "main_has_asyncio_sleep": False,
        "main_raises_http_exception": False,

        # models.py content checks
        "models_has_default_factory": False,
        "models_has_annotated_min_length": False,
        "models_uses_model_dump": False,

        # deps.py content checks
        "deps_has_yield_dependency": False,
        "deps_uses_lru_cache": False,  # optional but rewarded if present
        "deps_has_security_dependency": False,

        # tests content checks
        "tests_uses_asyncclient": False,
        "tests_uses_asgi_transport": False,
        "tests_imports_app": False,

        # architecture doc keyword checks
        "arch_mentions_lifespan": False,
        "arch_mentions_dependency": False,
        "arch_mentions_background": False,
        "arch_mentions_security": False,
        "arch_mentions_error": False,
    }

    # Paths
    main_py = os.path.join(output_dir, "main.py")
    models_py = os.path.join(output_dir, "models.py")
    deps_py = os.path.join(output_dir, "deps.py")
    tests_py = os.path.join(output_dir, "tests", "test_app.py")
    arch_md = os.path.join(output_dir, "ARCHITECTURE.md")

    # Existence checks
    if os.path.isfile(main_py):
        checks["main_py_exists"] = True
    if os.path.isfile(models_py):
        checks["models_py_exists"] = True
    if os.path.isfile(deps_py):
        checks["deps_py_exists"] = True
    if os.path.isfile(tests_py):
        checks["tests_exists"] = True
    if os.path.isfile(arch_md):
        checks["arch_exists"] = True

    # main.py content checks
    if checks["main_py_exists"]:
        content = read_file(main_py)
        if content is None:
            content = ""
        lc = content.lower()

        # Lifespan context manager and FastAPI lifespan arg
        # Look for "asynccontextmanager" and "fastapi(lifespan="
        if ("asynccontextmanager" in lc) and ("fastapi(" in lc) and ("lifespan=" in lc):
            checks["main_has_lifespan_asynccontextmanager"] = True

        # app.state usage
        if "app.state" in content:
            checks["main_uses_app_state"] = True

        # POST with status_code=201
        if ("post(" in lc or "@app.post" in lc) and "status_code=201" in lc:
            checks["main_has_post_201"] = True

        # Plain text Response
        if ("response(" in lc) and ("text/plain" in lc):
            checks["main_has_plain_text_response"] = True

        # BackgroundTasks usage
        if "backgroundtasks" in lc:
            checks["main_uses_backgroundtasks"] = True

        # No blocking sleep, has asyncio.sleep
        if "time.sleep(" not in lc:
            checks["main_no_time_sleep"] = True
        if "await asyncio.sleep(" in lc:
            checks["main_has_asyncio_sleep"] = True

        # raise HTTPException
        if "raise httpexception" in lc:
            checks["main_raises_http_exception"] = True

    # models.py content checks
    if checks["models_py_exists"]:
        content = read_file(models_py)
        if content is None:
            content = ""
        lc = content.lower()

        if "field(default_factory=" in lc:
            checks["models_has_default_factory"] = True
        if "annotated[" in lc and "min_length" in lc:
            checks["models_has_annotated_min_length"] = True
        if "model_dump(" in lc:
            checks["models_uses_model_dump"] = True

    # deps.py content checks
    if checks["deps_py_exists"]:
        content = read_file(deps_py)
        if content is None:
            content = ""
        lc = content.lower()

        # Yield-based dependency: function name starting with get_ and yield present
        if ("def get_" in lc) and ("yield" in lc):
            checks["deps_has_yield_dependency"] = True

        # Optional lru_cache
        if "lru_cache" in lc:
            checks["deps_uses_lru_cache"] = True

        # Security dependency: OAuth2PasswordBearer and get_current_user and raises HTTPException
        has_oauth = "oauth2passwordbearer" in lc
        has_get_current_user = "get_current_user" in lc
        raises_http_exc = "raise httpexception" in lc
        if has_oauth and has_get_current_user and raises_http_exc:
            checks["deps_has_security_dependency"] = True

    # tests/test_app.py content checks
    if checks["tests_exists"]:
        content = read_file(tests_py)
        if content is None:
            content = ""
        lc = content.lower()

        if "httpx.asyncclient" in lc:
            checks["tests_uses_asyncclient"] = True
        if "asgitransport" in lc:
            checks["tests_uses_asgi_transport"] = True
        # Import or construct app: permissive check as per rubric ("grep for 'import' and 'app' usage")
        if "import " in lc and "app" in lc:
            checks["tests_imports_app"] = True

    # ARCHITECTURE.md keyword checks
    if checks["arch_exists"]:
        content = read_file(arch_md)
        if content is None:
            content = ""
        lc = content.lower()

        if "lifespan" in lc:
            checks["arch_mentions_lifespan"] = True
        if "dependency" in lc:
            checks["arch_mentions_dependency"] = True
        if "background" in lc:
            checks["arch_mentions_background"] = True
        if "security" in lc:
            checks["arch_mentions_security"] = True
        if "error" in lc:
            checks["arch_mentions_error"] = True

    # Compute reward: average of all checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks

    # Ensure reward is exactly 0.0 for no-op baseline (no output files or empty output dir)
    # If none of the existence checks are true, force reward to 0.0
    if not any(checks[k] for k in ["main_py_exists", "models_py_exists", "deps_py_exists", "tests_exists", "arch_exists"]):
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()