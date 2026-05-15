# Compliance: Data Retention and Deletion

Storage scope
- Local-only storage: Indices and embeddings are stored on the local machine.
- No external APIs or third-party services receive content by default.

Data retention
- Retention: Embeddings and index files are retained for 90 days by default.
- Logs: Operational logs are retained for 30 days for debugging and audits.
- Legal hold: Automatic deletion must be suspended if a legal hold is in place.

Deletion process
- Manual deletion: Remove ~/.openclaw/memory_index.json to delete the index.
- Embeddings deletion: If embeddings are stored separately, purge all “embeddings” artifacts in the same directory.
- Verification: After deletion, rebuild the index and confirm that previous results no longer appear.

User requests and right to erasure
- Procedure: On request, delete the relevant notes, purge related embeddings, and rebuild.
- Confirmation: Provide a deletion confirmation timestamp and before/after index checks.

Security considerations
- Encryption: Rely on OS-level disk encryption to protect local data at rest.
- Access control: Limit shell access to authorized personnel; rotate credentials for on-call machines.

Audit and reporting
- Tracking: Record retention and deletion actions in a local audit log (30-day retention).
- Review: Quarterly compliance review ensures retention and deletion policies remain current.