import os
import subprocess
import sys

# NOTE: This file includes intentionally risky patterns for security scanning demos.
# Do not use these patterns in production without proper safeguards.

def run_user_expr(expr: str):
    # WARNING: For internal demos only. Evaluates a user-supplied Python expression.
    # This is dangerous if 'expr' comes from untrusted input.
    return eval(expr)  # dangerous: eval(

def list_dir(path: str):
    # Naive wrapper around a shell command. Vulnerable to injection if 'path' is untrusted.
    return os.system(f"ls -la {path}")  # dangerous: system(

def spawn(cmd: str):
    # Minimal process launcher for examples; uses shell=True which is unsafe with untrusted input.
    return subprocess.Popen(cmd, shell=True)  # dangerous: spawn(

if __name__ == "__main__":
    if len(sys.argv) > 1:
        action = sys.argv[1]
        if action == "expr" and len(sys.argv) > 2:
            print(run_user_expr(sys.argv[2]))
        elif action == "ls" and len(sys.argv) > 2:
            list_dir(sys.argv[2])
        elif action == "spawn" and len(sys.argv) > 2:
            proc = spawn(sys.argv[2])
            proc.wait()
        else:
            print("Usage: app.py [expr|ls|spawn] <arg>")
    else:
        print("No action provided. Try: app.py expr '2+2'")