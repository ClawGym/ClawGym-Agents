# TaskFlow — Product Context

Product: TaskFlow
Description: TaskFlow is a SaaS for small and mid-sized teams to plan sprints, manage tasks, and automate team workflows. Core value: reduce coordination overhead and make work status visible without manual effort.

Target Users:
- Team leads managing 5–50 people
- Individual contributors tracking tasks and deadlines
- Admins overseeing workspace security and compliance

Business Model:
- Freemium + Pro subscription ($12/user/month)
- Focus on SMBs (10–250 seats); expansion into mid-market

Team Setup:
- Sprint length: 2 weeks
- Team size: 6 (3 engineers, 1 QA, 1 designer, 1 Product Owner)
- Development practices: code review required, trunk-based development, nightly staging deployments
- Velocity history: 18–22 points per sprint (last 3 sprints averaged 19.7)

Definition of Done:
- Code implemented with peer review (at least 1 approval)
- Unit tests cover critical paths (minimum coverage on changed modules)
- Acceptance criteria met and verified on staging
- Security checks pass (linting, dependency vulnerabilities addressed)
- Documentation updated (release notes and user-facing help if applicable)
- Feature flagged where appropriate and rollback plan exists
- QA passes regression suite; no high-severity defects open
- Product Owner accepts on staging before release

Constraints & Notes:
- GDPR compliance is mandatory for EU customers; consent management needed before new EU marketing campaign
- SSO issues are affecting enterprise trials; logout bug generating support load
- Email trust and deliverability improvements are prerequisites for growth experiments and onboarding
- We have early signs of rate limit abuse in the API; guardrails recommended

Key Metrics:
- Weekly Active Teams
- Time to First Value (TTFV)
- Support ticket volume related to auth/issues
- Conversion from signup to verified account

Upcoming Events:
- EU marketing campaign (in 3 weeks) — requires GDPR consent banner
- Security review scheduled next month — audit log and rate limiting helpful

Stakeholder Summary:
- Legal: Push for GDPR consent banner, audit log
- Customer Support: Fix SSO logout bug, reduce auth-related tickets
- Growth/Marketing: Email verification to stabilize onboarding metrics; confetti animation as a delighter (not critical)
- Security: API rate limiting; MFA preferred but not blocking
- Sales: Enterprise trials require reliable SSO session handling and admin audit visibility