# SRE Runbook: Reliability Policies and Operational Procedures

This runbook outlines standard operating procedures for the on-call team and the practices we follow to maintain reliability across services.

## Service Level Objectives (SLOs)
- Target availability: 99.9% per monthly window.
- Our SLO is 99.9% monthly availability; the error budget is 0.1% downtime in the same period.
- Error budget policy: freeze releases when the error budget is exhausted until we recover stability.
- Monitor the error budget burn rate in Grafana using the SLO dashboard.
- If error budget remaining drops below 25%, escalate to the incident commander and schedule a reliability sprint.
- Post-incident reviews must reference the error budget and SLOs to determine corrective actions.

## Incident Response
1. Acknowledge page within 5 minutes.
2. Declare severity based on impact and blast radius.
3. Establish a bridge and assign roles (commander, comms, scribe).
4. Mitigation before root cause; do not delay rollback when user impact persists.

## Release Management
- Use progressive delivery for risky changes.
- Canary in a low-traffic region; halt if error rates exceed baseline by >3x.
- Freeze windows during peak traffic or events.

## On-Call Handover Checklist
- Review open incidents and follow-ups.
- Confirm alert noise levels and mute any known flapping alarms.
- Verify dashboards reflect current SLOs and recent changes.

## Postmortems
- Blameless and timely (within 5 business days).
- Include impact, timeline, contributing factors, and action items with owners and due dates.