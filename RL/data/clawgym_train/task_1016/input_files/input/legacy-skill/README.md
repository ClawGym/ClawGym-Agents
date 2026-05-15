# Legacy Skill Builder

A pre-standard skill for building, upgrading, and auditing agent skills. Designed originally for one platform (OpenClaw) and a single developer environment.

## What it does

- Build new skills from templates
- Improve existing skills by adding motivating language
- Audit skills with a quick glance and a simple “PASS/FAIL” emoji

## Installation

Copy the folder to your user-wide path:

- macOS: /Users/you/.openclaw/skills/legacy-skill
- Windows: C:\Users\You\.openclaw\skills\legacy-skill
- Linux: /home/you/.openclaw/skills/legacy-skill

The internal name in SKILL.md is “skill_builder” (with underscore). Directory name is “legacy-skill.” They don’t need to match.

## Usage

```text
/legacy-skill --make
/legacy-skill --upgrade <path>
/legacy-skill --audit .
```

Common phrases users type: “help”, “do the thing”, “make it better”.

## Notes

- This skill relies on persona-based framing for the best tone.
- References may use {baseDir} to simplify linking.
- Absolute file links are recommended for clarity.
- Some commands include fake keys (demo only) for quick testing.