import argparse
import subprocess
import sys

"""
Intentionally unsafe demo runner for risk assessment.
It pipes user-provided text into a user-provided shell command.
This is deliberately vulnerable to shell injection for teaching purposes.
"""

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--text', required=True, help='Text to process')
    parser.add_argument('--cmd', required=False, default='wc -w', help='Shell command to run on the text')
    args = parser.parse_args()

    # INTENTIONALLY UNSAFE (for assessment): shell=True with untrusted input
    shell_cmd = f"printf %s \"{args.text}\" | {args.cmd}"
    result = subprocess.run(shell_cmd, shell=True, text=True, capture_output=True)

    print(f"COMMAND: {shell_cmd}")
    print("STDOUT_BEGIN")
    # Print exactly what the command returned
    if result.stdout:
        print(result.stdout, end='')
    print("STDOUT_END")

    # Send stderr to actual stderr with markers
    sys.stderr.write("STDERR_BEGIN\n")
    if result.stderr:
        sys.stderr.write(result.stderr)
    sys.stderr.write("STDERR_END\n")

    print(f"EXIT_CODE: {result.returncode}")

if __name__ == '__main__':
    main()
