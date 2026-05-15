#!/usr/bin/env python3
import sys
import urllib.parse

# Reads test case lines like: "GET /path?param=<urlencoded-payload>"
# Emits simulated responses to stdout and sometimes stderr.
# Signals to detect in combined output:
#  - "SQL syntax error"
#  - "500 Internal Server Error"
#  - "Traceback"

def handle_line(line: str):
    line = line.strip()
    if not line or not line.startswith('GET '):
        return
    rest = line[4:].strip()
    if not rest:
        print("200 OK on /")
        return
    if '?' in rest:
        path, qs = rest.split('?', 1)
    else:
        path, qs = rest, ''
    param = None
    value = ''
    if qs:
        first = qs.split('&', 1)[0]
        if '=' in first:
            param, value = first.split('=', 1)
    decoded = urllib.parse.unquote(value)
    # Simulate different classes of errors based on payload contents
    if decoded and ("' OR '1'='1" in decoded or 'UNION SELECT' in decoded):
        # Simulate SQL error
        print(f"SQL syntax error near '{decoded}' on {path} param {param}")
    elif decoded and '<script' in decoded:
        # Simulate server exception with traceback on stderr and 500 on stdout
        sys.stderr.write(f"Traceback (most recent call last): ValueError('bad html in param {param}') on {path}\n")
        print(f"500 Internal Server Error on {path}")
    elif decoded and '${7*7}' in decoded:
        # Simulate generic 500
        print(f"500 Internal Server Error on {path}")
    else:
        print(f"200 OK on {path}")

if __name__ == '__main__':
    data = sys.stdin.read().splitlines()
    for ln in data:
        handle_line(ln)
