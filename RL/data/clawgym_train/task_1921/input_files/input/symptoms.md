Incident window: 10:15–12:05 UTC, April 19, 2026

Summary of symptoms (reported by on-call and application logs):
- User-facing API requests intermittently timed out; some returned 502 from the load balancer.
- Probes showed repeated DNS resolution errors (EAI_AGAIN) when calling external APIs; apt update also failed with “Temporary failure in name resolution”.
- Server felt very slow over SSH; top showed high %wa (IO wait) and near-constant CPU saturation.
- Disk alerts fired for the root filesystem; shortly after, writes started failing with “Read-only file system”.
- NTP status reported “NTP synchronized: no”, and TLS requests to third parties started failing with certificate date errors.
- Connection storms observed; many sockets in TIME_WAIT and some CLOSE_WAIT.
- Journal logs grew rapidly; /var/log ballooned past 7 GB.
- Some background tasks appeared stuck (uninterruptible sleep “D” state).
- Locale-related garbled characters appeared in one cron report email.
- The headless browser used by a reporting job failed to launch due to missing libraries.

Operational impact:
- Elevated error rate and latency for end users
- Scheduled data export jobs failed
- Pager fatigue due to repeated alerts across CPU, disk, DNS, and time sync

Immediate mitigations attempted:
- Restarted failing pods (did not help)
- Cleared some old logs (temporary relief)
- Switched traffic to a standby instance (restored service reliability while primary was investigated)