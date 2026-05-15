import json
import os
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def lines_set(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return set([line.strip() for line in f.read().splitlines()])
    except Exception:
        return set()

def file_contains(path, substrings):
    content = read_text(path)
    if content is None:
        return False
    return all(s in content for s in substrings)

def file_contains_any(path, substrings):
    content = read_text(path)
    if content is None:
        return False
    return any(s in content for s in substrings)

def safe_lower_contains(path, needle):
    content = read_text(path)
    if content is None:
        return False
    return needle.lower() in content.lower()

def scan_no_substring(dir_path, forbidden_lower):
    # True if no file in dir contains forbidden_lower substring (case-insensitive)
    if not os.path.isdir(dir_path):
        return False
    for root, _, files in os.walk(dir_path):
        for fn in files:
            fp = os.path.join(root, fn)
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                    if forbidden_lower in f.read().lower():
                        return False
            except Exception:
                return False
    return True

def main():
        workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
        input_dir = os.path.join(workspace_root, "input")
        output_dir = os.path.join(workspace_root, "output")
        reward_dir = os.path.join(workspace_root, "reward")

        checks = {
            "has_decision_json": False,
            "decision_json_valid": False,
            "chosen_pattern_valid_option": False,
            "chosen_pattern_expected": False,
            "decision_reason_keywords": False,
            "inputs_digest_is_object": False,
            "has_structure_txt": False,
            "structure_contains_all": False,
            "entity_order_class_methods": False,
            "port_payment_gateway_abc": False,
            "port_notification_abc": False,
            "port_order_repository_abc": False,
            "port_place_order_abc": False,
            "service_order_service_ports_ok": False,
            "adapter_mock_payment_ok": False,
            "adapter_console_notifier_ok": False,
            "adapter_in_memory_repo_ok": False,
            "primary_cli_calls_execute": False,
            "composition_root_wiring_ok": False,
            "boundary_no_adapters_in_domain_ports": False
        }

        # 1) decision.json checks
        decision_path = os.path.join(output_dir, "decision.json")
        if os.path.isfile(decision_path):
            checks["has_decision_json"] = True
            decision = load_json(decision_path)
            if isinstance(decision, dict):
                # Must have keys
                keys_ok = all(k in decision for k in ["chosen_pattern", "decision_reason", "inputs_digest"])
                if keys_ok:
                    checks["decision_json_valid"] = True
                    chosen = decision.get("chosen_pattern")
                    reason = decision.get("decision_reason", "")
                    inputs_digest = decision.get("inputs_digest")

                    # chosen_pattern valid
                    allowed = {"clean architecture", "hexagonal", "ports & adapters", "domain-driven design"}
                    if isinstance(chosen, str):
                        chosen_l = chosen.strip().lower()
                        if chosen_l in allowed:
                            checks["chosen_pattern_valid_option"] = True
                            if chosen_l in {"hexagonal", "ports & adapters"}:
                                checks["chosen_pattern_expected"] = True

                    # decision_reason keywords: must contain "integration" and at least one of swapp/adapter/test/independ
                    if isinstance(reason, str):
                        rl = reason.lower()
                        has_integration = ("integration" in rl)
                        other_keywords = any(kw in rl for kw in ["swapp", "adapter", "test", "independ"])
                        if has_integration and other_keywords:
                            checks["decision_reason_keywords"] = True

                    # inputs_digest must be an object
                    if isinstance(inputs_digest, dict):
                        checks["inputs_digest_is_object"] = True

        # 2) structure.txt checks
        structure_path = os.path.join(output_dir, "structure.txt")
        required_lines = [
            "output/src/",
            "output/src/domain/",
            "output/src/domain/entities/",
            "output/src/domain/services/",
            "output/src/ports/",
            "output/src/ports/inbound/",
            "output/src/ports/outbound/",
            "output/src/adapters/",
            "output/src/adapters/primary/",
            "output/src/adapters/primary/cli/",
            "output/src/adapters/secondary/",
            "output/src/adapters/secondary/persistence/",
            "output/src/adapters/secondary/payment/",
            "output/src/adapters/secondary/notification/",
            "output/src/infrastructure/",
            "output/src/domain/entities/order.py",
            "output/src/domain/services/order_service.py",
            "output/src/ports/inbound/place_order.py",
            "output/src/ports/outbound/payment_gateway.py",
            "output/src/ports/outbound/notification.py",
            "output/src/ports/outbound/order_repository.py",
            "output/src/adapters/secondary/payment/mock_payment.py",
            "output/src/adapters/secondary/notification/console_notifier.py",
            "output/src/adapters/secondary/persistence/in_memory_order_repository.py",
            "output/src/adapters/primary/cli/place_order_cli.py",
            "output/src/infrastructure/composition_root.py"
        ]
        if os.path.isfile(structure_path):
            checks["has_structure_txt"] = True
            listed = lines_set(structure_path)
            if all(req in listed for req in required_lines):
                checks["structure_contains_all"] = True

        # 3) file content checks
        # Paths
        base_src = os.path.join(output_dir, "src")
        paths = {
            "order_entity": os.path.join(base_src, "domain", "entities", "order.py"),
            "payment_gateway": os.path.join(base_src, "ports", "outbound", "payment_gateway.py"),
            "notification": os.path.join(base_src, "ports", "outbound", "notification.py"),
            "order_repository": os.path.join(base_src, "ports", "outbound", "order_repository.py"),
            "place_order": os.path.join(base_src, "ports", "inbound", "place_order.py"),
            "order_service": os.path.join(base_src, "domain", "services", "order_service.py"),
            "mock_payment": os.path.join(base_src, "adapters", "secondary", "payment", "mock_payment.py"),
            "console_notifier": os.path.join(base_src, "adapters", "secondary", "notification", "console_notifier.py"),
            "in_memory_repo": os.path.join(base_src, "adapters", "secondary", "persistence", "in_memory_order_repository.py"),
            "primary_cli": os.path.join(base_src, "adapters", "primary", "cli", "place_order_cli.py"),
            "composition_root": os.path.join(base_src, "infrastructure", "composition_root.py"),
        }

        # order entity
        if os.path.isfile(paths["order_entity"]):
            c = read_text(paths["order_entity"]) or ""
            if ("class Order" in c) and ("def is_valid(" in c) and ("def mark_as_paid(" in c):
                checks["entity_order_class_methods"] = True

        # PaymentGatewayPort
        if os.path.isfile(paths["payment_gateway"]):
            c = read_text(paths["payment_gateway"]) or ""
            if ("class PaymentGatewayPort" in c) and ("def charge(" in c) and (("ABC" in c) or ("@abstractmethod" in c)):
                checks["port_payment_gateway_abc"] = True

        # NotificationPort
        if os.path.isfile(paths["notification"]):
            c = read_text(paths["notification"]) or ""
            if ("class NotificationPort" in c) and ("def send(" in c) and (("ABC" in c) or ("@abstractmethod" in c)):
                checks["port_notification_abc"] = True

        # OrderRepositoryPort
        if os.path.isfile(paths["order_repository"]):
            c = read_text(paths["order_repository"]) or ""
            if ("class OrderRepositoryPort" in c) and ("def save(" in c) and (("ABC" in c) or ("@abstractmethod" in c)):
                checks["port_order_repository_abc"] = True

        # PlaceOrderPort
        if os.path.isfile(paths["place_order"]):
            c = read_text(paths["place_order"]) or ""
            if ("class PlaceOrderPort" in c) and ("def execute(" in c) and (("ABC" in c) or ("@abstractmethod" in c)):
                checks["port_place_order_abc"] = True

        # OrderService
        if os.path.isfile(paths["order_service"]):
            c = read_text(paths["order_service"]) or ""
            has_class = "class OrderService" in c
            has_execute = "def execute(" in c
            mentions_ports = all(name in c for name in ["PaymentGatewayPort", "OrderRepositoryPort", "NotificationPort"])
            no_adapters = "adapters" not in c.lower()
            if has_class and has_execute and mentions_ports and no_adapters:
                checks["service_order_service_ports_ok"] = True

        # MockPaymentAdapter
        if os.path.isfile(paths["mock_payment"]):
            c = read_text(paths["mock_payment"]) or ""
            if ("class MockPaymentAdapter" in c) and ("PaymentGatewayPort" in c) and ("def charge(" in c):
                checks["adapter_mock_payment_ok"] = True

        # ConsoleNotifierAdapter
        if os.path.isfile(paths["console_notifier"]):
            c = read_text(paths["console_notifier"]) or ""
            if ("class ConsoleNotifierAdapter" in c) and ("NotificationPort" in c) and ("def send(" in c):
                checks["adapter_console_notifier_ok"] = True

        # InMemoryOrderRepositoryAdapter
        if os.path.isfile(paths["in_memory_repo"]):
            c = read_text(paths["in_memory_repo"]) or ""
            if ("class InMemoryOrderRepositoryAdapter" in c) and ("OrderRepositoryPort" in c) and ("def save(" in c):
                checks["adapter_in_memory_repo_ok"] = True

        # Primary CLI
        if os.path.isfile(paths["primary_cli"]):
            c = read_text(paths["primary_cli"]) or ""
            if ("PlaceOrderPort" in c) and ("execute(" in c):
                checks["primary_cli_calls_execute"] = True

        # Composition root wiring
        if os.path.isfile(paths["composition_root"]):
            c = read_text(paths["composition_root"]) or ""
            if all(s in c for s in ["OrderService(", "MockPaymentAdapter", "ConsoleNotifierAdapter", "InMemoryOrderRepositoryAdapter"]):
                checks["composition_root_wiring_ok"] = True

        # 4) Boundary enforcement: no "adapters" substring in domain or ports
        domain_dir = os.path.join(base_src, "domain")
        ports_dir = os.path.join(base_src, "ports")
        domain_ok = scan_no_substring(domain_dir, "adapters")
        ports_ok = scan_no_substring(ports_dir, "adapters")
        if domain_ok and ports_ok:
            checks["boundary_no_adapters_in_domain_ports"] = True

        # Compute reward: all checks must pass
        all_pass = all(checks.values())
        reward = 1.0 if all_pass else 0.0

        result = {"reward": reward}
        result.update(checks)
        print(json.dumps(result))

if __name__ == "__main__":
    main()