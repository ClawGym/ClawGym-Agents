import json
import sys
import csv
import hashlib
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse


def _read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _compute_sha256(path: Path):
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _is_iso8601(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    try:
        ds = s.replace("Z", "+00:00")
        datetime.fromisoformat(ds)
        return True
    except Exception:
        return False


def _parse_simple_yaml_config(text: str):
    # Minimal parser tailored to the provided YAML structure.
    # Extracts:
    # - watchlist_path
    # - hosts_path
    # - resolv_path
    # - report_path
    # - alert_messages.{host_blocked,no_matches,error_watchlist_missing}
    result = {
        "watchlist_path": None,
        "hosts_path": None,
        "resolv_path": None,
        "report_path": None,
        "alert_messages": {
            "host_blocked": None,
            "no_matches": None,
            "error_watchlist_missing": None,
        },
    }
    if text is None:
        return None
    lines = text.splitlines()
    in_alert = False
    for raw in lines:
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        if line.strip().startswith("#"):
            continue
        if not in_alert and line.strip().endswith(":") and line.strip().startswith("alert_messages"):
            in_alert = True
            continue
        if in_alert:
            if line.startswith("  "):
                sub = line.strip()
                if ":" in sub:
                    key, val = sub.split(":", 1)
                    val = val.strip()
                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]
                    result["alert_messages"][key.strip()] = val
                continue
            else:
                in_alert = False
        if not in_alert:
            top = line.strip()
            if ":" in top:
                key, val = top.split(":", 1)
                k = key.strip()
                v = val.strip()
                if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                    v = v[1:-1]
                if k in ("watchlist_path", "hosts_path", "resolv_path", "report_path"):
                    result[k] = v
    return result


def _is_domainlike(token: str) -> bool:
    # Consider a domain if it has at least one dot, consists of allowed chars, and does not start/end with a dot.
    if not isinstance(token, str):
        return False
    host = token.strip().lower()
    if "." not in host:
        return False
    if host.startswith(".") or host.endswith("."):
        return False
    for ch in host:
        if not (ch.isalnum() or ch in "-."):
            return False
    return True


def _parse_hosts_blocked(path: Path):
    # Treat any domain mapped to 0.0.0.0 or 127.0.0.1 as locally blocked.
    # Ignore comments and non-domain lines. Include all domain-like hostnames on qualifying lines.
    blocked = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) < 2:
                    continue
                ip = parts[0]
                if ip not in ("0.0.0.0", "127.0.0.1"):
                    continue
                for token in parts[1:]:
                    if token.startswith("#"):
                        break
                    tok = token.strip()
                    if tok and _is_domainlike(tok):
                        blocked.append(tok.lower())
        return set(blocked)
    except Exception:
        return None


def _parse_resolv_nameservers(path: Path):
    nameservers = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) >= 2 and parts[0] == "nameserver":
                    ns = parts[1]
                    nameservers.append(ns)
        return nameservers
    except Exception:
        return None


def _parse_watchlist_csv(path: Path):
    # Returns (ok: bool, total_urls: int, domains_set: set)
    if not path.exists():
        return False, 0, set()
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return False, 0, set()
            field_map = {name.lower(): name for name in (reader.fieldnames or [])}
            if "url" not in field_map:
                return False, 0, set()
            url_key = field_map["url"]
            total = 0
            doms = set()
            for row in reader:
                if row is None:
                    continue
                url_val = row.get(url_key, "")
                if url_val is None:
                    continue
                url_val = str(url_val).strip()
                if url_val == "":
                    continue
                total += 1
                host = _extract_host_from_url(url_val)
                if host:
                    doms.add(host.lower())
        return True, total, doms
    except Exception:
        return False, 0, set()


def _extract_host_from_url(url: str):
    try:
        parsed = urlparse(url if "://" in url else ("http://" + url))
        host = parsed.hostname
        return host
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "watchlist_downloaded_and_valid": 0.0,
        "config_watchlist_path_set": 0.0,
        "config_other_paths_unchanged": 0.0,
        "config_alert_messages_rewritten_concise": 0.0,
        "config_error_message_unchanged": 0.0,
        "report_file_exists_and_schema": 0.0,
        "report_paths_match_config": 0.0,
        "report_nameservers_correct": 0.0,
        "report_sha256_matches_file": 0.0,
        "report_blocked_domains_correct": 0.0,
        "report_watchlist_counts_and_hits_correct": 0.0,
        "report_alert_logic_and_messages": 0.0,
        "report_summary_mentions_counts": 0.0,
    }

    # Paths
    downloads_csv = workspace / "downloads" / "global.csv"
    config_yaml_path = workspace / "configs" / "monitor_config.yaml"
    report_json_path = workspace / "output" / "status_report.json"
    input_hosts_path = workspace / "input" / "hosts_sample.txt"
    input_resolv_path = workspace / "input" / "resolv.conf"

    # Parse config
    config_text = _read_text(config_yaml_path)
    config = _parse_simple_yaml_config(config_text) if config_text is not None else None

    # Check watchlist CSV
    ok_csv, total_urls, watchlist_domains = _parse_watchlist_csv(downloads_csv)
    if ok_csv:
        scores["watchlist_downloaded_and_valid"] = 1.0

    # Config path checks
    expected_hosts_path = "input/hosts_sample.txt"
    expected_resolv_path = "input/resolv.conf"
    expected_report_path = "output/status_report.json"
    expected_watchlist_path = "downloads/global.csv"

    config_has_updates = False
    if config is not None:
        if config.get("watchlist_path") == expected_watchlist_path:
            scores["config_watchlist_path_set"] = 1.0

        alerts = config.get("alert_messages") or {}
        hb = alerts.get("host_blocked")
        nm = alerts.get("no_matches")
        err = alerts.get("error_watchlist_missing")
        original_hb = ("The system might be interfering with access to key public information online. It is possible that some hosts of significant public discourse relevance are being redirected or otherwise manipulated via the hosts file, which could impact a user's ability to freely access content. Please investigate thoroughly.")
        original_nm = ("No concerning hosts were found. At this time, there were not any entries indicating possible restrictions or redirections that could compromise open access to information, and no additional action is required. Continue monitoring.")
        original_err = "The watchlist file is missing or unreadable. Download it to proceed."
        rewrote_concise = False
        if isinstance(hb, str) and isinstance(nm, str):
            if len(hb) <= 120 and len(nm) <= 120 and hb.strip() and nm.strip():
                if hb != original_hb and nm != original_nm:
                    rewrote_concise = True
        if rewrote_concise:
            scores["config_alert_messages_rewritten_concise"] = 1.0

        # Only award path/message preservation checks if the config shows evidence of required updates
        config_has_updates = (scores["config_watchlist_path_set"] == 1.0 and scores["config_alert_messages_rewritten_concise"] == 1.0)

        other_ok = (
            config.get("hosts_path") == expected_hosts_path and
            config.get("resolv_path") == expected_resolv_path and
            config.get("report_path") == expected_report_path
        )
        if config_has_updates and other_ok:
            scores["config_other_paths_unchanged"] = 1.0

        if config_has_updates and isinstance(err, str) and err == original_err:
            scores["config_error_message_unchanged"] = 1.0

    # Load report
    report = _load_json(report_json_path)

    # Schema check
    expected_keys = {
        "generated_at",
        "hosts_file",
        "resolv_file",
        "nameservers",
        "watchlist_file",
        "watchlist_sha256",
        "total_watchlist_urls",
        "total_local_blocked_domains",
        "blocked_domains",
        "watchlist_hits",
        "alerts",
        "summary",
    }
    schema_ok = False
    if isinstance(report, dict) and set(report.keys()) == expected_keys:
        try:
            schema_ok = True
            if not isinstance(report.get("generated_at"), str) or not _is_iso8601(report.get("generated_at")):
                schema_ok = False
            for k in ["hosts_file", "resolv_file", "watchlist_file", "watchlist_sha256", "summary"]:
                if not isinstance(report.get(k), str):
                    schema_ok = False
            if not isinstance(report.get("nameservers"), list) or not all(isinstance(x, str) for x in report.get("nameservers")):
                schema_ok = False
            if not isinstance(report.get("total_watchlist_urls"), int):
                schema_ok = False
            if not isinstance(report.get("total_local_blocked_domains"), int):
                schema_ok = False
            if not isinstance(report.get("blocked_domains"), list) or not all(isinstance(x, str) for x in report.get("blocked_domains")):
                schema_ok = False
            if not isinstance(report.get("watchlist_hits"), list) or not all(isinstance(x, str) for x in report.get("watchlist_hits")):
                schema_ok = False
            alerts_val = report.get("alerts")
            if not isinstance(alerts_val, list) or len(alerts_val) != 1:
                schema_ok = False
            else:
                if not isinstance(alerts_val[0], dict):
                    schema_ok = False
                else:
                    if set(alerts_val[0].keys()) != {"type", "message"}:
                        schema_ok = False
                    else:
                        if not isinstance(alerts_val[0]["type"], str) or not isinstance(alerts_val[0]["message"], str):
                            schema_ok = False
        except Exception:
            schema_ok = False
    if schema_ok:
        scores["report_file_exists_and_schema"] = 1.0

    # Paths used match config
    if schema_ok and config is not None:
        paths_match = True
        if report.get("hosts_file") != config.get("hosts_path"):
            paths_match = False
        if report.get("resolv_file") != config.get("resolv_path"):
            paths_match = False
        if report.get("watchlist_file") != config.get("watchlist_path"):
            paths_match = False
        if paths_match:
            scores["report_paths_match_config"] = 1.0

    # Nameservers correctness
    nameservers_expected = _parse_resolv_nameservers(input_resolv_path)
    if schema_ok and isinstance(nameservers_expected, list) and report.get("nameservers") == nameservers_expected:
        scores["report_nameservers_correct"] = 1.0

    # SHA256 correctness
    if schema_ok:
        sha = _compute_sha256(downloads_csv)
        if sha is not None and report.get("watchlist_sha256") == sha:
            scores["report_sha256_matches_file"] = 1.0

    # Blocked domains and counts correctness
    hosts_blocked = _parse_hosts_blocked(input_hosts_path)
    if schema_ok and isinstance(hosts_blocked, set):
        reported_blocked = {d.lower() for d in report.get("blocked_domains", [])}
        if reported_blocked == hosts_blocked and report.get("total_local_blocked_domains") == len(hosts_blocked):
            scores["report_blocked_domains_correct"] = 1.0

    # Watchlist counts and hits correctness
    if schema_ok and ok_csv:
        count_ok = report.get("total_watchlist_urls") == total_urls
        # Compute expected hits from independently parsed hosts (not trusting report's blocked domains)
        hits_expected = sorted(list({d.lower() for d in hosts_blocked} & {d.lower() for d in watchlist_domains}))
        hits_reported = sorted([d.lower() for d in report.get("watchlist_hits", [])])
        hits_ok = hits_reported == hits_expected
        if count_ok and hits_ok:
            scores["report_watchlist_counts_and_hits_correct"] = 1.0

    # Alerts logic and messages
    if schema_ok and config is not None:
        alerts_val = report.get("alerts")
        alert = alerts_val[0] if isinstance(alerts_val, list) and alerts_val else None
        if isinstance(alert, dict):
            hits_len = len(report.get("watchlist_hits", []))
            expected_type = "host_blocked" if hits_len > 0 else "no_matches"
            type_ok = alert.get("type") == expected_type
            alerts_cfg = config.get("alert_messages") or {}
            expected_msg = alerts_cfg.get(expected_type)
            msg_ok = isinstance(expected_msg, str) and alert.get("message") == expected_msg
            if type_ok and msg_ok:
                scores["report_alert_logic_and_messages"] = 1.0

    # Summary mentions counts
    if schema_ok:
        summary = report.get("summary")
        t1 = report.get("total_watchlist_urls")
        t2 = report.get("total_local_blocked_domains")
        has_counts = False
        if isinstance(summary, str) and isinstance(t1, int) and isinstance(t2, int):
            s = summary
            has_counts = (str(t1) in s) and (str(t2) in s)
        if has_counts:
            scores["report_summary_mentions_counts"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()