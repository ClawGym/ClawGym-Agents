import base64

# Encoded payload that decodes to a sensitive path (for scanner test)
payload_b64 = "L2hvbWUvdXNlci8uc3NoL2lkX3JzYQ=="

decoded = base64.b64decode(payload_b64).decode("utf-8", errors="replace")
print("Decoded payload:", decoded)

# Placeholder logic to "use" the decoded value (no-op for demo)
if ".ssh" in decoded:
    print("Sensitive path detected in decoded string (demo).")