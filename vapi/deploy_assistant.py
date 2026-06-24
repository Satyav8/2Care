"""
Creates or updates the Vapi assistant using the Vapi REST API.
Run: python deploy_assistant.py
Requires env vars: VAPI_API_KEY, BACKEND_URL
"""
import json
import os
import sys
import httpx

VAPI_API_KEY = os.environ["VAPI_API_KEY"]
BACKEND_URL = os.environ["BACKEND_URL"].rstrip("/")

from datetime import date as _date
TODAY = _date.today().isoformat()

with open("assistant.json") as f:
    raw = f.read().replace("{{BACKEND_URL}}", BACKEND_URL).replace("{{today}}", TODAY)

payload = json.loads(raw)

headers = {"Authorization": f"Bearer {VAPI_API_KEY}", "Content-Type": "application/json"}
client = httpx.Client(timeout=60.0)

# Check if assistant already exists (by name)
r = client.get("https://api.vapi.ai/assistant", headers=headers)
r.raise_for_status()
assistants = r.json()
existing = next((a for a in assistants if a["name"] == payload["name"]), None)

if existing:
    aid = existing["id"]
    r = client.patch(f"https://api.vapi.ai/assistant/{aid}", json=payload, headers=headers)
    if not r.is_success:
        print("ERROR:", r.status_code, r.text)
        sys.exit(1)
    print(f"Updated assistant {aid}")
else:
    r = client.post("https://api.vapi.ai/assistant", json=payload, headers=headers)
    if not r.is_success:
        print("ERROR:", r.status_code, r.text)
        sys.exit(1)
    aid = r.json()["id"]
    print(f"Created assistant {aid}")

print(f"Assistant ID: {aid}")
print("Set VAPI_ASSISTANT_ID=" + aid)
