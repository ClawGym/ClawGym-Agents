Title: Project Beacon — Early Warning for At‑Risk Students

Overview
Project Beacon proposes a privacy‑respectful, early‑warning feature to help advisors identify undergraduate students who may be at risk of academic disengagement. The feature analyzes patterns in LMS activity, assignment timing, and limited email metadata to trigger human advisor outreach. No grades are changed, no disciplinary actions are taken, and all interventions are supportive and optional for students.

Goals
- Detect disengagement signals early enough (weeks 2–6) to enable supportive outreach.
- Reduce DFW rates and improve term‑to‑term persistence.
- Minimize privacy impact by collecting only necessary signals and limiting access to authorized advisors.

Scope and Non‑Goals
- In scope: Undergraduate courses using the University LMS (Canvas-based), advisor outreach by the Student Success Office, and pilot departments (Biology, Psychology).
- Out of scope: Instructor‑facing alerts (unless separately requested by student), disciplinary referrals, financial holds, or automated eligibility decisions.

Data Sources
1) LMS Activity (Canvas API)
   - Login timestamps (first/last per day)
   - Session counts per week (aggregated)
   - Course page access counts per week (aggregated)
   - Assignment submission timestamps and on‑time/late indicators
   - Course due dates and module availability windows
   - NOTE: No assignment content, no discussion/body text, no file uploads or grading comments are ingested.

2) Limited Email Metadata (University email, Exchange/Office365)
   - Internal (.edu to .edu) to/from identifiers
   - Send timestamps
   - Thread count (messages per conversation)
   - NOTE: No subject lines, no email bodies, and no external (.com, etc.) messages are ingested.

3) Student Information (SIS, minimal read)
   - Term enrollment status, declared major(s), class level
   - Advisor assignment
   - FERPA directory‑information opt‑out flag
   - Approved accommodations flags (yes/no only; no diagnosis or details)

Processing and Scoring
- Weekly batch job computes a disengagement score per course and student based on:
  - Reduced LMS logins over sliding two‑week window relative to week 1 baseline
  - Missing or late submissions relative to due dates
  - Drop in course page accesses relative to peers in the same section
  - Reduced internal email thread count with instructors/advisors (if previously present)
- Scores are normalized per course section to reduce cross‑course bias.
- Risk thresholds: “watch” (advisors may monitor) and “contact” (advisors review and decide whether to reach out).

Outputs
- Advisor Dashboard (Student Success Portal)
  - List of students above “contact” threshold with contributing factors (e.g., “2 late submissions; 60% drop in logins”).
  - No visibility of raw emails; only aggregate counts and timestamps.
  - Status workflow: Review → Attempted Outreach → Connected → Resolved.
- Notifications
  - Weekly digest to assigned advisor; no notifications to instructors by default.

Access Controls and Governance
- Access restricted to academic advisors and Student Success leadership with documented legitimate educational interest; role‑based access enforced by the portal.
- Data retention:
  - Raw event aggregates retained for 1 academic term + 30 days.
  - Derived risk flags retained for 2 years for longitudinal evaluation.
- Audit logging:
  - All dashboard views and exports are logged.
  - Quarterly access review by IT Security and Registrar.

Student Experience
- Outreach is supportive and voluntary (e.g., “We noticed you might need support—resources available here”).
- Students can request their engagement report from advisors.
- Transparency page on the Student Success site explains signals, use, and safeguards.

Privacy and Compliance Constraints
- No sharing of risk scores outside Student Success advising teams without Registrar approval.
- Directory‑information opt‑out does not restrict internal use for student success where legitimate educational interest applies.
- Vendor considerations: The LMS and email systems are provided under existing DPAs; vendors act as school officials under contract and direct control.

Equity and Bias Controls (Pilot)
- Section‑level normalization to avoid punishing courses with heavier LMS use.
- Accommodation‑aware logic: On‑time/late indicators adjust for approved extended time windows.
- Monitoring for disparate impact by major, class level, and first‑gen status; monthly fairness review.

Open Questions for Steering Committee
- Should students be proactively notified during orientation that engagement signals may be used for advising? If so, proposed language and timing.
- Should instructors be able to opt in to receive alerts for their own sections?
- What minimum sample sizes are required to compute peer benchmarks without overfitting small sections?
- Should we provide an individual “pause” option for students who request no outreach for a defined period?

Operational Timeline (Proposed)
- Design review: Month 1
- Pilot build & internal testing: Months 2–3
- Pilot in Biology & Psychology: Months 4–5
- Evaluation & decision on expansion: Month 6

Risks Identified by Team
- False positives prompting unwanted contact
- Chilling effects if students perceive surveillance
- Disparate impact on students balancing work/caregiving
- Re‑identification risk if small sections are benchmarked without thresholds

Assumptions
- Advisors, as school officials, have legitimate educational interest in student success.
- Subject lines and bodies of emails are never processed or stored.
- Outreach content is standardized and non‑punitive.