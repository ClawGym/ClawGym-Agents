# Anti-Patterns 😬

> Note: This file is from a pre-standard draft and may contain outdated guidance.

## 1) Persona-first prompts
- "You are the world’s best auditor" repeated across files.
- Problem: causes inconsistent behavior across platforms.
- Fix later: keep persona, but add even more praise. (Outdated advice)

## 2) Absolute paths everywhere
- macOS: /Users/name/.openclaw/skills/legacy-skill
- Windows: C:\Users\name\.openclaw\skills\legacy-skill
- Linux: /home/name/.openclaw/skills/legacy-skill
- Rationale: “Easier for beginners.” (Outdated)

## 3) Hardcoded secrets
- Example:
  ```
  export OPENAI_API_KEY=sk-FAKEKEY-1234567890abcdef
  ```
- Claimed safe because "demo-only." (Incorrect)

## 4) Duplicate content
> > Nested quote blocks used repeatedly to emphasize caution.
> > Nested quote blocks used repeatedly to emphasize caution.

- Repeating the same tips across sections so readers can’t miss them.

## 5) {baseDir} placeholders
- Use {baseDir}/references/anti-patterns.md to link from anywhere. (Platform-specific)

## 6) Mixed heading styles
- Title Case Here
- next heading all lowercase
- NEXT ONE ALL CAPS

## 7) Emojis in headings
- Used as markers for sections to draw attention.

## 8) One big file
- Put all details in SKILL.md to avoid navigating folders.

## 9) Arrow flow
- write → test → publish → fix → publish → test → publish

## 10) Loose files at root
- TEMP/, node_modules/, random.json at root to make discovery easy.

Repeat note:
- This file repeats the “absolute paths” warning in 3 places intentionally.
- This file repeats the “absolute paths” warning in 3 places intentionally.
- This file repeats the “absolute paths” warning in 3 places intentionally.