import json
import os
import sys
import re
import csv

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def parse_endpoints_csv(path):
    endpoints = []
    if not os.path.isfile(path):
        return endpoints
    try:
        with open(path, "r", encoding="utf-8") as f:
            # Try DictReader first
            try:
                reader = csv.DictReader(f)
                # Normalize fieldnames
                fieldnames = [fn.strip().lower() for fn in (reader.fieldnames or [])]
                # Ensure method and path exist
                if "method" in fieldnames and "path" in fieldnames:
                    for row in reader:
                        # Normalize keys
                        norm = {k.strip().lower(): (v if v is not None else "").strip() for k, v in row.items()}
                        m = norm.get("method", "")
                        p = norm.get("path", "")
                        if m and p:
                            endpoints.append((m.strip(), p.strip()))
                    return endpoints
            except Exception:
                pass
        # Fallback simple csv reader
        with open(path, "r", encoding="utf-8") as f2:
            reader2 = csv.reader(f2)
            rows = list(reader2)
            if not rows:
                return endpoints
            header = [h.strip().lower() for h in rows[0]]
            m_idx = None
            p_idx = None
            for i, h in enumerate(header):
                if h == "method":
                    m_idx = i
                if h == "path":
                    p_idx = i
            if m_idx is None or p_idx is None:
                # Try assume first two columns
                m_idx, p_idx = 0, 1 if len(header) >= 2 else (None, None)
            for i, row in enumerate(rows[1:]):
                try:
                    m = row[m_idx].strip()
                    p = row[p_idx].strip()
                except Exception:
                    continue
                if m and p:
                    endpoints.append((m, p))
    except Exception:
        return []
    return endpoints

def contains_all(substrings, text, case_sensitive=True):
    if not case_sensitive:
        t = text.lower()
        return all((s.lower() in t) for s in substrings)
    return all((s in text) for s in substrings)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Paths
    spec_path = os.path.join(input_dir, "spec.json")
    endpoints_path = os.path.join(input_dir, "endpoints.csv")

    manifest_path = os.path.join(output_dir, "manifest.json")
    src_main_path = os.path.join(output_dir, "src_main.rs.md")
    readme_path = os.path.join(output_dir, "README.md")
    design_path = os.path.join(output_dir, "DESIGN.md")

    checks = {
        # Existence
        "has_manifest": False,
        "has_src_main": False,
        "has_readme": False,
        "has_design": False,
        # manifest checks
        "manifest_valid_json": False,
        "manifest_has_required_keys": False,
        "manifest_package_matches_service": False,
        "manifest_edition_ok": False,
        "manifest_deps_include_required": False,
        # src_main checks
        "src_has_clap_derive": False,
        "src_has_clap_use": False,
        "src_has_enum_and_serve_check": False,
        "src_has_async_main_and_tokio_attr": False,
        "src_has_axum_router": False,
        "src_contains_all_paths": False,
        "src_has_shared_state": False,
        "src_has_tokio_select": False,
        "src_has_app_error_thiserror": False,
        "src_avoids_unwrap": False,
        "src_has_healthz": False,
        # README checks
        "readme_has_service_name": False,
        "readme_lists_all_routes_method_path": False,
        "readme_mentions_serve_check": False,
        "readme_has_healthz": False,
        # DESIGN checks
        "design_error_handling_phrases": False,
        "design_arc_rwlock_tradeoffs_channels": False,
        "design_avoid_blocking_io_async": False,
        "design_mentions_ownership_borrowing": False,
        # Cross-file consistency
        "cross_paths_in_both": False,
        "cross_healthz_in_both": False,
    }

    # Load inputs
    spec = load_json(spec_path)
    service_name = None
    if isinstance(spec, dict):
        sn = spec.get("service_name")
        if isinstance(sn, str):
            service_name = sn

    endpoints = parse_endpoints_csv(endpoints_path)

    # Existence
    has_manifest = os.path.isfile(manifest_path)
    has_src_main = os.path.isfile(src_main_path)
    has_readme = os.path.isfile(readme_path)
    has_design = os.path.isfile(design_path)
    checks["has_manifest"] = has_manifest
    checks["has_src_main"] = has_src_main
    checks["has_readme"] = has_readme
    checks["has_design"] = has_design

    # manifest checks
    manifest = None
    if has_manifest:
        manifest = load_json(manifest_path)
        if isinstance(manifest, dict):
            checks["manifest_valid_json"] = True
            # required keys
            if ("package_name" in manifest and isinstance(manifest.get("package_name"), str) and
                "edition" in manifest and isinstance(manifest.get("edition"), str) and
                "dependencies" in manifest and isinstance(manifest.get("dependencies"), list)):
                checks["manifest_has_required_keys"] = True

            # edition
            if manifest.get("edition") == "2024":
                checks["manifest_edition_ok"] = True

            # package name matches service_name if known
            if service_name is not None and isinstance(manifest.get("package_name"), str):
                if manifest.get("package_name") == service_name:
                    checks["manifest_package_matches_service"] = True

            # deps include
            deps_required = {"tokio", "axum", "serde", "serde_json", "clap", "thiserror", "anyhow"}
            deps = set()
            if isinstance(manifest.get("dependencies"), list):
                for d in manifest.get("dependencies"):
                    if isinstance(d, str):
                        deps.add(d)
            if deps_required.issubset(deps):
                checks["manifest_deps_include_required"] = True

    # src_main checks
    src_text = read_text(src_main_path) if has_src_main else None
    if src_text is not None:
        # clap derive and use
        if "#[derive(Parser)]" in src_text:
            checks["src_has_clap_derive"] = True
        if "use clap::" in src_text:
            checks["src_has_clap_use"] = True

        # enum and Serve/Check variants (simple presence-based)
        if ("enum " in src_text) and ("Serve" in src_text) and ("Check" in src_text):
            checks["src_has_enum_and_serve_check"] = True

        # async main and tokio attribute
        if ("async fn main() -> anyhow::Result<()>"
                in src_text) and ("#[tokio::main" in src_text):
            checks["src_has_async_main_and_tokio_attr"] = True

        # axum router presence
        if ("use axum" in src_text) and ("Router" in src_text) and (".route(" in src_text):
            checks["src_has_axum_router"] = True

        # shared state
        if ("Arc<" in src_text) and ("RwLock" in src_text):
            checks["src_has_shared_state"] = True

        # tokio::select!
        if "tokio::select!" in src_text:
            checks["src_has_tokio_select"] = True

        # thiserror custom error with AppError
        has_derive_error = "#[derive(Error" in src_text or "#[derive(thiserror::Error" in src_text
        has_app_error_ident = "AppError" in src_text
        has_thiserror_import_or_path = ("use thiserror" in src_text) or ("thiserror::Error" in src_text)
        if has_derive_error and has_app_error_ident and has_thiserror_import_or_path:
            checks["src_has_app_error_thiserror"] = True

        # avoid unwrap
        if ("unwrap(" not in src_text) and (".unwrap()" not in src_text):
            checks["src_avoids_unwrap"] = True

        # healthz path literal
        if "/healthz" in src_text:
            checks["src_has_healthz"] = True

        # contains all CSV paths (only award if endpoints are provided)
        if endpoints:
            all_paths_present = True
            for _, path in endpoints:
                if path not in src_text:
                    all_paths_present = False
                    break
            checks["src_contains_all_paths"] = all_paths_present
        else:
            # Avoid vacuous pass: keep False if no endpoints available
            checks["src_contains_all_paths"] = False

    # README checks
    readme_text = read_text(readme_path) if has_readme else None
    if readme_text is not None:
        # has service name
        if service_name and service_name in readme_text:
            checks["readme_has_service_name"] = True

        # list all method+path pairs from CSV (only if endpoints present)
        if endpoints:
            upper_readme = readme_text.upper()
            method_path_ok = True
            for method, path in endpoints:
                pair = f"{method.strip().upper()} {path.strip()}".upper()
                if pair not in upper_readme:
                    method_path_ok = False
                    break
            checks["readme_lists_all_routes_method_path"] = method_path_ok
        else:
            checks["readme_lists_all_routes_method_path"] = False

        # mentions Serve and Check subcommands
        if (("Serve" in readme_text or "serve" in readme_text) and
            ("Check" in readme_text or "check" in readme_text)):
            checks["readme_mentions_serve_check"] = True

        # healthz in README
        if "/healthz" in readme_text:
            checks["readme_has_healthz"] = True

    # DESIGN checks
    design_text = read_text(design_path) if has_design else None
    if design_text is not None:
        low = design_text.lower()
        # error handling phrases (case-insensitive)
        if ("thiserror for libraries" in low) and ("anyhow for applications" in low):
            checks["design_error_handling_phrases"] = True

        # Arc<RwLock>, channels, trade-off(s)
        arc_present = "Arc<RwLock>" in design_text
        channels_present = "channels" in low
        tradeoff_present = ("trade-off" in low) or ("tradeoffs" in low) or ("tradeoff" in low)
        if arc_present and channels_present and tradeoff_present:
            checks["design_arc_rwlock_tradeoffs_channels"] = True

        # Avoid blocking I/O in async with tokio::fs or spawn_blocking
        avoid_blocking = ("blocking" in low and "async" in low)
        mentions_io_tooling = ("tokio::fs" in design_text) or ("spawn_blocking" in design_text)
        if avoid_blocking and mentions_io_tooling:
            checks["design_avoid_blocking_io_async"] = True

        # ownership and borrowing
        if ("ownership" in low) and ("borrowing" in low):
            checks["design_mentions_ownership_borrowing"] = True

    # Cross-file consistency
    if has_src_main and has_readme and src_text is not None and readme_text is not None:
        cross_ok = False
        if endpoints:
            paths_ok = True
            for _, path in endpoints:
                if (path not in src_text) or (path not in readme_text):
                    paths_ok = False
                    break
            cross_ok = paths_ok
        # only set True if endpoints provided and both contain all paths
        checks["cross_paths_in_both"] = cross_ok

        # healthz present in both
        checks["cross_healthz_in_both"] = ("/healthz" in src_text) and ("/healthz" in readme_text)

    # Compute reward
    # No-op baseline: if output is empty or missing, reward must be 0.0
    # We'll use fraction of passed checks.
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # If none of the output files exist, force 0.0
    if not (has_manifest or has_src_main or has_readme or has_design):
        reward = 0.0
    else:
        # Proportional reward
        reward = passed / total_checks if total_checks > 0 else 0.0

    # Clamp reward to [0,1]
    reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()