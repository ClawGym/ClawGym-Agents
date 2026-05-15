Security Classification Guidelines — Chornomorsk Port

Purpose
- Provide a consistent method to assess port security posture (Normal, Warning, Alert) and generate appropriate alerts.

Baseline
- ISPS Level: 1 (routine) unless otherwise directed.
- Reference thresholds are defined in port_baseline.json.

Classification Matrix
1) Normal
- Weather and sea state within baseline thresholds.
- Vessel traffic follows declared routes and schedules.
- Minor AIS anomalies (< 60 min gap) with subsequent recovery.
- Security/news bulletins are general advisories without specific or credible local threat indicators.
- Routine maintenance/operations (e.g., dredging) with proper notifications.

2) Warning
- Weather: sustained winds ≥ 20 kt or visibility < 2000 m, or wave height ≥ 1.5 m.
- Vessel behavior: unverified loitering or AIS silence ≥ 60 minutes within approach or anchorage; repeated schedule deviations without notice; discrepancy between declared cargo and observed operations.
- Security/news: credible, time-bound bulletin naming Chornomorsk/Odesa Bay with potential impact (e.g., spoofing attempts tied to local area or time window) requiring enhanced procedures.
- Infrastructure issues: tug/pilot shortage affecting safety margins.

3) Alert
- Severe weather: gale conditions (≥ 34 kt), visibility < 1000 m, or sea state > 2.5 m within port limits.
- Confirmed security threat or incident: unauthorized approach to restricted zones, PFSA breach, explosive/drone threat, or directed interdiction affecting port waters.
- Multiple vessels exhibiting coordinated anomalies (AIS off, course deviations) in proximity.
- Critical infrastructure failure compromising port safety (e.g., VTS outage, spill, fire).

Alert Severity Mapping
- info: Situational awareness; no immediate operational risk; follow standard measures.
- warning: Elevated vigilance; adapt procedures; potential operational constraints.
- critical: Immediate action required; implement contingency/security protocols.

Assessment Method
- Cross-validate weather across at least two sources. If consistent within tolerance (temp ±1.5°C, wind ±3 kt, same general conditions), treat as confirmed.
- Reconcile vessel statuses with movements ledger; investigate any non-cancelled vessel lacking AIS or contact for ≥ 60 minutes.
- Review news feed; classify as Advisory, Watch, or Incident. Only Watch/Incident with local specificity should upgrade posture.
- Document rationale including references to input files and timestamps.

Recommended Actions (by posture)
- Normal: Routine monitoring, spot checks on AIS and credentials, communicate scheduled works (e.g., dredging) to all stakeholders.
- Warning: Increase watch frequency, verify AIS against pilotage/VTS logs, pre-position tugs/pilots, brief terminals on weather/traffic constraints.
- Alert: Suspend movements as necessary, activate ISPS procedures, coordinate with authorities, issue navigational warnings, and maintain incident log.