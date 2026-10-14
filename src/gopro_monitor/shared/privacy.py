"""Best-effort redaction for in-memory diagnostics, never a disk log."""
import re

def redact(message, secrets=()):
    text=str(message)
    for secret in sorted((s for s in secrets if s),key=len,reverse=True):
        text=text.replace(secret,'[redacted]')
    text=re.sub(r'(?i)(?:[0-9a-f]{2}:){5}[0-9a-f]{2}','[device]',text)
    text=re.sub(r'(?i)\bC\d{10,}\b','[serial]',text)
    text=re.sub(r'(?i)\bGoPro\s+\d{4,}\b','GoPro [device]',text)
    text=re.sub(r'(?i)[a-z]:[\\/]Users[\\/][^\\/\s]+','[user-home]',text)
    return text
