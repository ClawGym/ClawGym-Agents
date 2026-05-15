# FAQ

Q: How are my files encrypted?
A: Files are encrypted client-side using AES-256-GCM with per-file keys; only ciphertext leaves the device.

Q: What happens if I lose my device?
A: Revoke the device session from the admin console; tokens are invalidated and future syncs are blocked.

Q: How long do you retain deleted files?
A: Deleted files are retained for 30 days and then permanently purged.

Q: Can I self-host NebulaDrive?
A: Yes, we support self-hosted deployments on AWS, GCP, and Azure with Helm charts and Terraform modules.

Q: Do you support external sharing?
A: Yes, admins can enable external sharing with domain allowlists and expiration policies.