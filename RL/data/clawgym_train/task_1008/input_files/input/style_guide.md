# Hostel Caption Style Guide

Brand voice: Friendly, warm, and visual-forward. Use plain language, present tense, and focus on what guests can see and do. Avoid hype and superlatives.

Must-haves:
- Include one approved call-to-action (CTA) phrase verbatim.
- Mention at least one concrete feature that appears on our site.
- Keep it concise; aim for a snappy, scannable line.

Avoid:
- Jargon, over-promises, or superlatives like "best ever".
- Banned words listed in the rules block below.

Rules (parsed by the validator):
```yaml name=rules
char_limit: 220
cta_required: true
require_feature_mention: true
case_insensitive: true
allowed_ctas:
  - Book direct
  - Reserve your bed
  - Message us
  - See availability
banned_words:
  - cheap
  - cheapest
  - guarantee
  - freebie
```
