import sys, json, re
from pathlib import Path

USAGE = "Usage: python tests/validate_outputs.py <snapshot_json> <report_md> <log_md>"

ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

def fail(msg):
    print(f"VALIDATION FAILED: {msg}")
    sys.exit(1)

def load_text(p):
    try:
        return Path(p).read_text(encoding='utf-8')
    except Exception as e:
        fail(f"Cannot read {p}: {e}")

def as_float(x):
    return isinstance(x, (int, float))

def main():
    if len(sys.argv) != 4:
        print(USAGE)
        sys.exit(2)
    snap_p, report_p, log_p = sys.argv[1:4]
    # Check files exist
    for p in (snap_p, report_p, log_p):
        if not Path(p).exists():
            fail(f"Missing required file: {p}")

    # Validate JSON structure
    try:
        snap = json.loads(load_text(snap_p))
    except Exception as e:
        fail(f"Snapshot JSON parse error: {e}")

    required_keys = [
        'timestamp','os_name','kernel','hostname','cpu_model','logical_cores',
        'mem_total_mb','mem_available_mb','load_avg_1m','load_avg_5m','load_avg_15m',
        'fs_path','fs_total_gb','fs_used_gb','fs_used_percent','top_processes'
    ]
    for k in required_keys:
        if k not in snap:
            fail(f"Missing key in JSON: {k}")

    if not isinstance(snap['timestamp'], str) or not ISO_RE.match(snap['timestamp']):
        fail("timestamp must be ISO-like string: YYYY-MM-DDTHH:MM:SS…")
    date_str = snap['timestamp'][:10]

    for k in ['os_name','kernel','hostname','cpu_model','fs_path']:
        if not isinstance(snap[k], str):
            fail(f"{k} must be a string")

    if snap['fs_path'] != '.':
        fail("fs_path must be '.'")

    if not isinstance(snap['logical_cores'], int) or snap['logical_cores'] < 1:
        fail("logical_cores must be integer >= 1")

    if not isinstance(snap['mem_total_mb'], int) or snap['mem_total_mb'] <= 0:
        fail("mem_total_mb must be integer > 0")
    if not isinstance(snap['mem_available_mb'], int) or snap['mem_available_mb'] < 0 or snap['mem_available_mb'] > snap['mem_total_mb']:
        fail("mem_available_mb must be integer >= 0 and <= mem_total_mb")

    for k in ['load_avg_1m','load_avg_5m','load_avg_15m','fs_total_gb','fs_used_gb','fs_used_percent']:
        if not as_float(snap[k]):
            fail(f"{k} must be a number")
    if snap['fs_total_gb'] <= 0:
        fail("fs_total_gb must be > 0")
    if snap['fs_used_gb'] < 0:
        fail("fs_used_gb must be >= 0")
    if not (0 <= snap['fs_used_percent'] <= 100):
        fail("fs_used_percent must be between 0 and 100")

    tp = snap['top_processes']
    if not isinstance(tp, list) or len(tp) != 3:
        fail("top_processes must be a list of exactly 3 entries")
    for i, item in enumerate(tp, 1):
        if not isinstance(item, dict):
            fail(f"top_processes[{i}] must be an object")
        for k in ['pid','command','rss_mb']:
            if k not in item:
                fail(f"Missing {k} in top_processes[{i}]")
        if not isinstance(item['pid'], int) or item['pid'] <= 0:
            fail(f"top_processes[{i}].pid must be positive int")
        if not isinstance(item['command'], str) or not item['command']:
            fail(f"top_processes[{i}].command must be non-empty string")
        if not as_float(item['rss_mb']) or item['rss_mb'] < 0:
            fail(f"top_processes[{i}].rss_mb must be number >= 0")

    # Validate report contains key info
    report_txt = load_text(report_p)
    if 'System Status Report' not in report_txt:
        fail("Report should contain title 'System Status Report'")
    if 'Notes on Focus' not in report_txt:
        fail("Report should include a 'Notes on Focus' section")
    if date_str not in report_txt:
        fail("Report should include the date from the JSON timestamp")
    # Ensure some numeric agreement between JSON and report content
    if str(snap['logical_cores']) not in report_txt:
        fail("Report should mention logical cores count")
    if str(snap['mem_total_mb']) not in report_txt:
        fail("Report should include mem_total_mb value")
    fs_used_pct_int = int(round(float(snap['fs_used_percent'])))
    if str(fs_used_pct_int) not in report_txt:
        fail("Report should include fs_used_percent (integer or matching number)")

    # Validate log update
    log_txt = load_text(log_p)
    begin = '<!-- BEGIN LAST CHECK -->'
    end = '<!-- END LAST CHECK -->'
    if begin not in log_txt or end not in log_txt:
        fail("Log file must contain BEGIN/END marker comments")
    seg = log_txt.split(begin, 1)[1].split(end, 1)[0]
    if '2023-11-15' in seg or 'old_report.md' in seg or 'old_snapshot.json' in seg:
        fail("Log markers still contain placeholder content; must be replaced")
    if f'Date: {date_str}' not in seg:
        fail("Log 'Date:' line must reflect JSON timestamp date")
    if 'Report: output/system_status_report.md' not in seg:
        fail("Log must link to the report path")
    if 'Snapshot: output/system_snapshot.json' not in seg:
        fail("Log must link to the snapshot path")
    if 'Status:' not in seg and 'status:' not in seg:
        fail("Log segment should include a one-sentence status note")

    print('OK: outputs validated successfully.')

if __name__ == '__main__':
    main()
