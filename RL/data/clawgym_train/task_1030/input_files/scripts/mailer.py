import re
from jinja2 import Template

ALLOWED_VARS = {"driver_name","truck_id","current_location","delivery_eta","care_pkg_tracking","lunch_note"}
REQUIRED_TEMPLATE_FIELDS = {"Subject"}  # first non-empty line must start with "Subject:"

def parse_subject_and_body(text):
    lines = text.splitlines()
    subject_line = None
    body_lines = []
    for i, line in enumerate(lines):
        if line.strip():
            if line.startswith("Subject:"):
                subject_line = line[len("Subject:"):].strip()
                body_lines = lines[i+1:]
            break
    return subject_line, "\n".join(body_lines).strip()

def find_placeholders(text):
    # naive Jinja2 variable finder
    return set(re.findall(r"{{\s*([a-zA-Z0-9_]+)\s*}}", text))

def validate_placeholders(text):
    vars_found = find_placeholders(text)
    unknown = vars_found - ALLOWED_VARS
    return vars_found, unknown

def render(text, context):
    t = Template(text)
    return t.render(**context)

if __name__ == "__main__":
    sample = "Subject: Example\nHello {{ driver_name }} from {{ current_location }}."
    subj, body = parse_subject_and_body(sample)
    vars_found, unknown = validate_placeholders(sample)
    print(subj, body, vars_found, unknown)
