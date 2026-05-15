# Sample Project

This is a minimal demo project used to test a lightweight static security scan.

Important notes:
- app.py purposefully uses eval(), os.system(), and a spawn-like process launcher. These are included to trigger detection rules and should not be used with untrusted input.
- worker.py demonstrates exec() to simulate a simplistic plugin loader for internal testing.
- config.py contains clearly dummy keys (e.g., sk-****, AIza****) to test secret scanning and redaction routines. Do not use these values for anything real.

Usage examples (demo only):
- python app.py expr "2+2"
- python app.py ls "."
- python app.py spawn "echo hello from child"

Security guidance:
- Never pass untrusted input to eval(), exec(), or shell commands.
- Store real credentials in environment variables or secret managers, not in source control.
- Review file permissions and avoid world-writable files in production environments.