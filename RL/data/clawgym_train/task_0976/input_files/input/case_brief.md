Case: WIN10-CLIENT05 Suspected Compromise
Date: 2026-04-18

Executive Summary
- SOC observed unusual outbound traffic from WIN10-CLIENT05 (user: CONTOSO\jdoe) to 185.231.223.88 over TCP/443. EDR flagged a rundll32.exe invocation with a non-standard DLL path under C:\ProgramData\Intel\cache\.
- A live memory acquisition was performed and triaged with Volatility 3. The following extracts are provided for deeper analysis: memory_pslist.csv (process listing), memory_netscan.csv (network artifacts), memory_malfind.txt (injection indicators), yara_hits.json (rule-based detections).
- Objective: Validate compromise, identify suspicious processes and behaviors, enumerate Indicators of Compromise (IOCs), and recommend containment and eradication steps.

Scope and Constraints
- Scope limited to artifacts in input/. No disk image or full registry hive available.
- Host is Windows 10 (22H2) client. Single user active session (CONTOSO\jdoe).
- No internet lookups permitted during analysis. Rely only on provided evidence and conservative inference.

Key Questions
1) Which processes appear compromised or abused (e.g., rundll32, svchost, powershell, others)?
2) Do memory artifacts support code injection or beaconing behavior?
3) What C2 endpoints or domains are indicated?
4) What persistence or lateral movement hints are present in memory?
5) What concrete IOCs can be extracted for detection and blocking?

Deliverables
- A verification-heavy incident report with multi-stage reasoning.
- A CSV of suspicious processes with detection sources.
- A JSON list of IOCs (>=12) covering domains, IPs, hashes, registry or mutexes, and paths.
- Mock user seed data (50 records) for downstream testing.
- An investigation notes export capturing workflow steps.

Assumptions
- Times in logs are local to the host (approx UTC-05:00). Minor drift is acceptable.
- YARA rules are representative; treat them as leads requiring corroboration from other artifacts.
- Absence of evidence in a given artifact is not evidence of absence; favor conservative, evidence-backed conclusions.