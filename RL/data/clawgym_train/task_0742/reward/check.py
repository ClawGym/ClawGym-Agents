import json
import os
import sys
import re

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        try:
            with open(path, "r", encoding="latin-1") as f:
                return f.read()
        except Exception:
            return ""

def file_exists(path: str) -> bool:
    return os.path.isfile(path)

def validate_config(content: str) -> bool:
    # Must define Settings class, include jwt_secret and database_url names,
    # have a get_settings function, and reference lru_cache
    has_class = "class Settings" in content
    has_jwt = "jwt_secret" in content
    has_db = "database_url" in content
    has_getter = "def get_settings" in content
    has_cache = "lru_cache" in content
    return all([has_class, has_jwt, has_db, has_getter, has_cache])

def validate_errors(content: str) -> bool:
    # Must define AppError and at least NotFoundError and AuthenticationError subclasses
    # and include the literal keys "code", "message", "details"
    has_base = "class AppError" in content
    has_not_found = "class NotFoundError" in content
    has_auth_err = "class AuthenticationError" in content
    has_keys = '"code"' in content and '"message"' in content and '"details"' in content
    return all([has_base, has_not_found, has_auth_err, has_keys])

def validate_main(content: str) -> bool:
    # Must define create_app, include '/api/users' and '/health', and register a global error handler
    has_factory = "def create_app" in content
    has_users_ref = "/api/users" in content
    has_health_ref = "/health" in content
    has_handler = ("exception_handler" in content) or ("add_exception_handler" in content)
    return all([has_factory, has_users_ref, has_health_ref, has_handler])

def validate_logging(content: str) -> bool:
    # Must include request_id and evidence of JSON/structured logging
    has_req_id = "request_id" in content
    has_struct = ("JSON" in content) or ("structured" in content)
    return has_req_id and has_struct

def validate_schemas_no_password_in_response(content: str) -> bool:
    # Must contain class UserCreate and class UserResponse.
    # Within the UserResponse class block, 'password' must not appear before the next 'class ' declaration.
    if "class UserCreate" not in content or "class UserResponse" not in content:
        return False
    # Find the start of UserResponse class
    m = re.search(r"class\s+UserResponse\b", content)
    if not m:
        return False
    start_idx = m.start()
    # Find next class declaration after UserResponse
    next_m = re.search(r"\nclass\s+", content[m.end():])
    if next_m:
        end_idx = m.end() + next_m.start()
    else:
        end_idx = len(content)
    block = content[start_idx:end_idx]
    # Ensure 'password' does not appear in this block
    return "password" not in block

def validate_users_router_di(content: str) -> bool:
    return ("router =" in content) and ("Depends(" in content)

def validate_health_paths(content: str) -> bool:
    return ("/health" in content) and ("/ready" in content)

def validate_openapi_summary(path: str) -> bool:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return False
    keys_required = {"/api/users", "/api/auth/login", "/health", "/ready"}
    # Check top-level
    top_keys = set(data.keys()) if isinstance(data, dict) else set()
    if keys_required.issubset(top_keys):
        return True
    # Check under 'paths'
    if isinstance(data, dict) and isinstance(data.get("paths"), dict):
        path_keys = set(data["paths"].keys())
        if keys_required.issubset(path_keys):
            return True
    return False

def validate_tests(content: str) -> bool:
    has_async = "async def" in content
    has_refs = ("/api/users" in content) or ("/health" in content)
    return has_async and has_refs

def validate_readme(content: str) -> bool:
    has_phrase = "Router → Service → Repository" in content
    has_section = re.search(r"project structure", content, re.IGNORECASE) is not None
    return has_phrase and has_section

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    output_dir = os.path.join(workspace_root, "output")

    # Build absolute paths
    paths = {
        "main": os.path.join(output_dir, "src", "app", "main.py"),
        "config": os.path.join(output_dir, "src", "app", "config.py"),
        "errors": os.path.join(output_dir, "src", "app", "core", "errors.py"),
        "logging": os.path.join(output_dir, "src", "app", "core", "logging.py"),
        "security": os.path.join(output_dir, "src", "app", "core", "security.py"),
        "users_router": os.path.join(output_dir, "src", "app", "features", "users", "router.py"),
        "users_service": os.path.join(output_dir, "src", "app", "features", "users", "service.py"),
        "users_repository": os.path.join(output_dir, "src", "app", "features", "users", "repository.py"),
        "users_schemas": os.path.join(output_dir, "src", "app", "features", "users", "schemas.py"),
        "users_models": os.path.join(output_dir, "src", "app", "features", "users", "models.py"),
        "auth_router": os.path.join(output_dir, "src", "app", "features", "auth", "router.py"),
        "health_router": os.path.join(output_dir, "src", "app", "health", "router.py"),
        "tests_e2e": os.path.join(output_dir, "tests", "test_e2e.py"),
        "readme": os.path.join(output_dir, "README.md"),
        "openapi": os.path.join(output_dir, "OPENAPI_SUMMARY.json"),
    }

    checks = {
        # Existence checks
        "has_main": False,
        "has_config": False,
        "has_errors": False,
        "has_logging": False,
        "has_security": False,
        "has_users_router": False,
        "has_users_service": False,
        "has_users_repository": False,
        "has_users_schemas": False,
        "has_users_models": False,
        "has_auth_router": False,
        "has_health_router": False,
        "has_tests_e2e": False,
        "has_readme": False,
        "has_openapi_summary": False,
        # Content validations
        "config_content_valid": False,
        "errors_content_valid": False,
        "main_content_valid": False,
        "logging_content_valid": False,
        "schemas_no_password_in_response": False,
        "users_router_di": False,
        "health_paths_present": False,
        "openapi_has_paths": False,
        "tests_async_and_refs": False,
        "readme_has_phrases": False,
    }

    # Existence
    for key in [
        "main","config","errors","logging","security","users_router","users_service",
        "users_repository","users_schemas","users_models","auth_router","health_router",
        "tests_e2e","readme","openapi"
    ]:
        checks_key = {
            "main": "has_main",
            "config": "has_config",
            "errors": "has_errors",
            "logging": "has_logging",
            "security": "has_security",
            "users_router": "has_users_router",
            "users_service": "has_users_service",
            "users_repository": "has_users_repository",
            "users_schemas": "has_users_schemas",
            "users_models": "has_users_models",
            "auth_router": "has_auth_router",
            "health_router": "has_health_router",
            "tests_e2e": "has_tests_e2e",
            "readme": "has_readme",
            "openapi": "has_openapi_summary",
        }[key]
        checks[checks_key] = file_exists(paths[key])

    # Content checks (only if files exist)
    if checks["has_config"]:
        cfg_content = read_text(paths["config"])
        checks["config_content_valid"] = validate_config(cfg_content)

    if checks["has_errors"]:
        err_content = read_text(paths["errors"])
        checks["errors_content_valid"] = validate_errors(err_content)

    if checks["has_main"]:
        main_content = read_text(paths["main"])
        checks["main_content_valid"] = validate_main(main_content)

    if checks["has_logging"]:
        log_content = read_text(paths["logging"])
        checks["logging_content_valid"] = validate_logging(log_content)

    if checks["has_users_schemas"]:
        schemas_content = read_text(paths["users_schemas"])
        checks["schemas_no_password_in_response"] = validate_schemas_no_password_in_response(schemas_content)

    if checks["has_users_router"]:
        ur_content = read_text(paths["users_router"])
        checks["users_router_di"] = validate_users_router_di(ur_content)

    if checks["has_health_router"]:
        health_content = read_text(paths["health_router"])
        checks["health_paths_present"] = validate_health_paths(health_content)

    if checks["has_openapi_summary"]:
        checks["openapi_has_paths"] = validate_openapi_summary(paths["openapi"])

    if checks["has_tests_e2e"]:
        test_content = read_text(paths["tests_e2e"])
        checks["tests_async_and_refs"] = validate_tests(test_content)

    if checks["has_readme"]:
        readme_content = read_text(paths["readme"])
        checks["readme_has_phrases"] = validate_readme(readme_content)

    # Compute reward: proportion of checks passed
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)

    # No-op baseline: if no output or no checks passed => 0.0
    reward = (passed_checks / total_checks) if passed_checks > 0 else 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()