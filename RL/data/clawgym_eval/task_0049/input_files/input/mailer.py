# Minimal renderer reference for template compatibility. Do not execute; inspect only.
import re

ALLOWED_PLACEHOLDERS = {
    "student_name",
    "college",
    "deadline_date",
    "scholarship_name",
    "recommender_name",
}

# Templates may use only the placeholders above in double-brace form, e.g., {{ student_name }}.
PLACEHOLDER_PATTERN = re.compile(r"{{\s*(student_name|college|deadline_date|scholarship_name|recommender_name)\s*}}")

class TemplateRenderer:
    """
    Renders templates by replacing placeholders in ALLOWED_PLACEHOLDERS with values.
    Subject lines may be prefixed externally; keep subjects short. Bodies should avoid any
    placeholders not listed here. New placeholders will cause a runtime error in production.
    """
    def validate(self, text: str) -> bool:
        # Return True if all placeholders are allowed; False otherwise.
        for m in re.findall(r"{{\s*([a-zA-Z_]+)\s*}}", text):
            if m not in ALLOWED_PLACEHOLDERS:
                return False
        return True
