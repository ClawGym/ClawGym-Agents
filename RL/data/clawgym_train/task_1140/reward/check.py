import json
import os
import re
import sys

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks dict with all checks defaulting to False
    checks = {
        # Existence checks per table (11 files each)
        "files_useraccount_exist": False,
        "files_orderitem_exist": False,

        # Content sanity checks
        "po_useraccount_content": False,
        "po_orderitem_content": False,
        "mapper_useraccount_content": False,
        "mapper_orderitem_content": False,
        "service_useraccount_class": False,
        "service_orderitem_class": False,
        "repository_useraccount_class": False,
        "repository_orderitem_class": False,

        # Plan file validation
        "plan_exists": False,
        "plan_valid_json": False,
        "plan_has_keys": False,
        "plan_lists_all_files": False,

        # Report validation
        "report_exists": False,
        "report_has_template_group": False,
        "report_has_base_package": False,
        "report_has_overwrite_candidates_phrase": False,
        "report_mentions_no_plaintext_passwords": False,
    }

    # Expected configuration derived from task specification
    base_package = "com.acme.shop"
    template_group = "Custom-V2"
    package_path = base_package.replace(".", "/")
    tables = [
        ("user_account", "UserAccount"),
        ("order_item", "OrderItem"),
    ]

    # Build expected relative file paths under output/src/main/java/<package_path>/...
    relative_java_root = os.path.join("output", "src", "main", "java", package_path)
    expected_suffixes = [
        ("domain/repository/po", "{}PO.java"),
        ("domain/repository/mapper", "{}Mapper.java"),
        ("domain/entity", "{}.java"),
        ("domain/repository/service", "{}Repository.java"),
        ("domain/factory", "{}Factory.java"),
        ("domain/service", "{}Service.java"),
        ("application/service", "{}ApplicationService.java"),
        ("interfaces/dto", "{}DTO.java"),
        ("interfaces/dto", "{}EditDTO.java"),
        ("interfaces/dto", "{}PageDTO.java"),
        ("interfaces/viewobject", "{}VO.java"),
    ]

    expected_paths_per_table = {}
    for snake, pascal in tables:
        paths = []
        for subdir, filename_tpl in expected_suffixes:
            filename = filename_tpl.format(pascal)
            rel_path = os.path.join(relative_java_root, subdir, filename)
            paths.append(rel_path)
        expected_paths_per_table[pascal] = paths

    # Helper: file existence check for a list of relative paths
    def all_exist(rel_paths):
        for rel in rel_paths:
            abs_p = os.path.join(workspace_root, rel)
            if not os.path.isfile(abs_p):
                return False
        return True

    # Perform existence checks for both tables
    ua_paths = expected_paths_per_table["UserAccount"]
    oi_paths = expected_paths_per_table["OrderItem"]

    if all_exist(ua_paths):
        checks["files_useraccount_exist"] = True
    if all_exist(oi_paths):
        checks["files_orderitem_exist"] = True

    # Content sanity checks
    # PO files: class declaration and @TableName("table_name")
    def read_file(abs_path):
        try:
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception:
            return None

    def check_po_content(pascal, table_snake):
        rel_po = os.path.join(relative_java_root, "domain", "repository", "po", f"{pascal}PO.java")
        content = read_file(os.path.join(workspace_root, rel_po))
        if not content:
            return False
        cls_ok = re.search(rf"\bpublic\s+class\s+{pascal}PO\b", content) is not None
        table_ok = f'@TableName("{table_snake}")' in content
        return cls_ok and table_ok

    checks["po_useraccount_content"] = check_po_content("UserAccount", "user_account")
    checks["po_orderitem_content"] = check_po_content("OrderItem", "order_item")

    # Mapper files: interface declaration and extends BaseMapper<PO>
    def check_mapper_content(pascal):
        rel_mapper = os.path.join(relative_java_root, "domain", "repository", "mapper", f"{pascal}Mapper.java")
        content = read_file(os.path.join(workspace_root, rel_mapper))
        if not content:
            return False
        iface_ok = re.search(rf"\binterface\s+{pascal}Mapper\b", content) is not None
        extends_ok = re.search(rf"extends\s+BaseMapper\s*<\s*{pascal}PO\s*>", content) is not None
        return iface_ok and extends_ok

    checks["mapper_useraccount_content"] = check_mapper_content("UserAccount")
    checks["mapper_orderitem_content"] = check_mapper_content("OrderItem")

    # Service and Repository classes: class declarations present
    def check_class_decl(rel_path, class_name):
        content = read_file(os.path.join(workspace_root, rel_path))
        if not content:
            return False
        return re.search(rf"\bpublic\s+class\s+{class_name}\b", content) is not None

    # UserAccount Service and Repository
    ua_service_rel = os.path.join(relative_java_root, "domain", "service", "UserAccountService.java")
    ua_repo_rel = os.path.join(relative_java_root, "domain", "repository", "service", "UserAccountRepository.java")
    checks["service_useraccount_class"] = check_class_decl(ua_service_rel, "UserAccountService")
    checks["repository_useraccount_class"] = check_class_decl(ua_repo_rel, "UserAccountRepository")

    # OrderItem Service and Repository
    oi_service_rel = os.path.join(relative_java_root, "domain", "service", "OrderItemService.java")
    oi_repo_rel = os.path.join(relative_java_root, "domain", "repository", "service", "OrderItemRepository.java")
    checks["service_orderitem_class"] = check_class_decl(oi_service_rel, "OrderItemService")
    checks["repository_orderitem_class"] = check_class_decl(oi_repo_rel, "OrderItemRepository")

    # Plan file validation
    plan_path = os.path.join(output_dir, "plan.json")
    if os.path.isfile(plan_path):
        checks["plan_exists"] = True
        plan_data = None
        try:
            with open(plan_path, "r", encoding="utf-8", errors="ignore") as f:
                plan_data = json.load(f)
            checks["plan_valid_json"] = True
        except Exception:
            plan_data = None

        if isinstance(plan_data, dict):
            bp_ok = plan_data.get("base_package") == base_package
            tg_ok = plan_data.get("template_group") == template_group
            checks["plan_has_keys"] = bool(bp_ok and tg_ok)

            # files array must list at least the 22 expected files
            files_list = plan_data.get("files")
            if isinstance(files_list, list):
                # Normalize plan file paths for comparison
                norm_files = set()
                for s in files_list:
                    if not isinstance(s, str):
                        continue
                    p = s.replace("\\", "/")
                    # Strip workspace absolute prefix if present
                    ws_prefix = workspace_root.replace("\\", "/").rstrip("/") + "/"
                    if p.startswith(ws_prefix):
                        p = p[len(ws_prefix):]
                    # Strip leading "./"
                    if p.startswith("./"):
                        p = p[2:]
                    # Ensure prefixed with "output/" for comparison
                    if p.startswith("src/"):
                        p = "output/" + p
                    # We only care about the segment under output
                    norm_files.add(p)

                # Build expected normalized set
                expected_norm = set(path.replace("\\", "/") for path in ua_paths + oi_paths)
                # Check all expected are included
                if expected_norm.issubset(norm_files):
                    checks["plan_lists_all_files"] = True

    # Report validation
    report_path = os.path.join(output_dir, "GENERATION_REPORT.md")
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        try:
            with open(report_path, "r", encoding="utf-8", errors="ignore") as f:
                rpt = f.read()
            if "Template Group: Custom-V2" in rpt:
                checks["report_has_template_group"] = True
            if "Base Package: com.acme.shop" in rpt:
                checks["report_has_base_package"] = True
            if "Overwrite Candidates" in rpt:
                checks["report_has_overwrite_candidates_phrase"] = True
            if "No plaintext passwords" in rpt:
                checks["report_mentions_no_plaintext_passwords"] = True
        except Exception:
            pass

    # Compute reward as fraction of checks passed
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks

    # Ensure no-op baseline yields 0.0 if nothing produced
    # If output directory missing or empty and no checks passed, reward will be 0.0
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()