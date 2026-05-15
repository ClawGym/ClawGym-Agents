Legacy Setup Notes (Background Only)

Overview
- The previous OpenClaw workspace grew organically and mixed agent prompts with project materials in the root directory.
- A deprecated “lab” agent remained configured but inactive, occasionally leaking outdated rules into the main prompt.
- Memory files were inconsistent: daily notes were saved under multiple date formats and scattered across subfolders.
- Automation used overlapping cron entries with unclear ownership and noisy outputs.

Known Issues
- Mixed responsibilities across multiple agents led to prompt bloat and duplicated behavior.
- Heartbeat jobs frequently produced long paragraphs instead of short health checks.
- Project truth lived partly in chat transcripts and partly in ad hoc markdown files.

Migration Considerations
- Consolidate to one strong main and one minimal rescue, no lab.
- Move historical research and reports into topic files or archives, keep root lean.
- Ensure scheduled tasks reference real files and explicit success criteria.

Note
This document provides background only and should not be injected into always-on root workspace files in the new architecture.