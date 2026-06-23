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

with open("assistant.json") as f:
    raw = f.read().replace("{{BACKEND_URL}}", BACKEND_URL)

payload = json.loads(raw)

headers = {"Authorization": f"Bearer {VAPI_API_KEY}", "Content-Type": "application/json"}

# Check if assistant already exists (by name)
r = httpx.get("https://api.vapi.ai/assistant", headers=headers)
r.raise_for_status()
assistants = r.json()
existing = next((a for a in assistants if a["name"] == payload["name"]), None)

if existing:
    aid = existing["id"]
    r = httpx.patch(f"https://api.vapi.ai/assistant/{aid}", json=payload, headers=headers)
    r.raise_for_status()
    print(f"Updated assistant {aid}")
else:
    r = httpx.post("https://api.vapi.ai/assistant", json=payload, headers=headers)
    r.raise_for_status()
    aid = r.json()["id"]
    print(f"Created assistant {aid}")

print(f"Assistant ID: {aid}")
print("Set VAPI_ASSISTANT_ID=" + aid)
