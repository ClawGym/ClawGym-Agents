# Outreach Email Style Guide (Short Film & Theatre)

As I reach out to local actors and collaborators, I want emails that are friendly, clear, and concise. Please follow these rules when rewriting messages. Names may contain Estonian diacritics and must be preserved exactly.

Key points:
- Keep tone polite and professional.
- Be concise; avoid filler words and excessive punctuation.
- Never alter the spelling or diacritics of recipient_name or sender_name fields.

Rules (JSON):
```json
{
  "max_subject_length": 60,
  "require_subject": true,
  "forbidden_punctuation": ["!"],
  "preferred_signoff_template": "Best,\n{sender_name}",
  "normalize_slang": {
    "u": "you",
    "thx": "thanks"
  }
}
```

Notes:
- If subject is missing, create a concise, informative one that respects max_subject_length.
- Remove forbidden punctuation from both subject and body.
- Replace slang per normalize_slang.
- End with the preferred sign-off template.
- Trim leading/trailing whitespace in the body.