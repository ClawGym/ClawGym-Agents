Session: 2026-04-18

User: Please set up the repo and install dependencies. Then run tests.

Assistant: Sure, I'll start with npm install.

Command:
$ npm install

Terminal Output:
> app@1.0.0 preinstall
> only-allow pnpm

This project uses pnpm for package management.
ERROR: Please use "pnpm install" instead of npm/yarn.

npm ERR! code ELIFECYCLE
npm ERR! errno 1
npm ERR! app@1.0.0 preinstall: `only-allow pnpm`
npm ERR! Exit status 1
npm ERR!
npm ERR! Failed at the app@1.0.0 preinstall script.
npm ERR! This is probably not a problem with npm. There is likely additional logging output above.

npm ERR! A complete log of this run can be found in:
npm ERR!     /home/runner/.npm/_logs/2026-04-18T09_12_41_512Z-debug.log

User (correction): We use pnpm in this project, not npm. There is a pnpm-lock.yaml and pnpm-workspace.yaml in the repo. Please use pnpm install.

Assistant: Got it — thanks for the correction. Switching to pnpm.

Command:
$ pnpm install

Terminal Output:
Lockfile is up to date, resolution step is not required
Progress: resolved 124, reused 124, downloaded 0, added 0
packages are already installed
Done in 2.1s

Assistant: Dependencies installed successfully with pnpm. Running tests now.

Command:
$ pnpm test

Terminal Output:
Test Suites: 12 passed, 12 total
Tests:       104 passed, 104 total
Time:        9.83 s

User: Great. Before we wrap, can we add a pre-commit Markdown linting check for .md files? I want to ensure consistent formatting on docs and changelogs.

Assistant: Yes, we can add a pre-commit hook with markdownlint. I’ll propose using Husky + lint-staged and markdownlint-cli2.

User: Sounds good. Also, please log this correction about pnpm vs npm to our .learnings files and promote a concise guideline to CLAUDE.md so future sessions don’t repeat it.

Assistant: Will do. I’ll log a learning entry and promote the rule to CLAUDE.md.

—

Later the same day (CI pipeline run):

CI Bot: Running install step…

Command (CI):
$ npm ci

CI Log:
> app@1.0.0 preinstall
> only-allow pnpm

This project uses pnpm for package management.
ERROR: Please use "pnpm install" instead of npm/yarn.

npm ERR! code ELIFECYCLE
npm ERR! errno 1
npm ERR! app@1.0.0 preinstall: `only-allow pnpm`
npm ERR! Exit status 1
npm ERR!
npm ERR! Failed at the app@1.0.0 preinstall script.
npm ERR! 
npm ERR! Additional info:
npm ERR! Found pnpm-lock.yaml in the workspace root.
npm ERR! Use: pnpm install --frozen-lockfile

Pipeline Status: FAILED at install step.

User (correction): CI must also use pnpm. Please update the CI script to use pnpm install --frozen-lockfile. This is the second time we hit the npm vs pnpm issue today — make sure the learning reflects that recurrence.

Assistant: Acknowledged. I’ll fix the CI configuration and escalate the learning priority due to recurrence.

User (feature request): While you’re at it, can we configure the markdown linter to fail on hard tabs and trailing spaces? Prefer markdownlint rules MD010 and MD009 enforced pre-commit, plus a CI check.

Assistant: Yes. I’ll add markdownlint rules MD010 and MD009, wire them into Husky + lint-staged, and add a CI job to run markdownlint over docs and the root README.

User: Thank you. Also capture the CI failure as an error entry in .learnings/ERRORS.md with the actual error snippet from the logs and link it to the learning.

Assistant: Will do. Also confirming Node version: we’re targeting Node 18 LTS in this project, correct?

User (correction): Correct — Node 18 LTS. Please reflect that in any configs you touch, but the package manager correction is the main thing to promote.

Assistant: Understood. I’ll proceed:
- Log the correction (pnpm vs npm) and mark it promoted to CLAUDE.md.
- Log the CI error with the npm failure snippet.
- Add a feature request entry for pre-commit markdown linting with MD010/MD009 and CI integration.
- Cross-reference the repeated npm vs pnpm incidents and raise priority accordingly.

Files referenced in this session:
- package.json
- pnpm-lock.yaml
- pnpm-workspace.yaml
- .github/workflows/ci.yml (to be updated)
- .husky/pre-commit (to be added)
- .lintstagedrc (to be added)
- .markdownlint.jsonc (to be added)

End of transcript.