# Configuration values (DUMMY/TEST ONLY). These are not real credentials.
# They are intentionally included to verify that scanners can detect common secret patterns.

# Dummy OpenAI-style key (pattern: sk-...):
OPENAI_API_KEY = "sk-ABCDEF1234567890ABCDEF1234567890"

# Dummy Google API key (pattern: AIza... + 35 chars):
GOOGLE_API_KEY = "AIzaSyA1234567890BCDEFGHIJKLMNOPQRSTUV"

# Additional dummy tokens for extended pattern coverage (not strictly needed for the task):
DUMMY_SERVICE_TOKEN = "nvapi-1234-ABCD-5678-EFGH"  # example vendor-like token format

# Non-sensitive configuration
APP_ENV = "development"
LOG_LEVEL = "INFO"