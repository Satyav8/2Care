"""
Eval harness for Apollo Voice Receptionist.

Approach: We simulate multi-turn conversations by sending messages to the
Vapi Chat API (text mode), then score each turn and the final outcome.

Why text mode (not live calls)?
- Deterministic, fast, re-runnable without phone numbers
- Evaluators can run `python harness.py` in < 2 minutes
- LLM judge scores quality; tool-call checks score correctness

Dimensions measured:
1. Task Completion Rate      — did the agent achieve the stated goal?
2. Tool Accuracy             — did it call the right tool(s)?
3. Slot Conflict Handling    — did it offer alternatives when slot taken?
4. Mid-flow Recovery         — did it handle intent changes gracefully?
5. Latency (p50/p95)         — round-trip time per turn (ms)
6. Verbosity                 — tokens per agent turn (lower = better)
7. Hallucination Check       — did agent invent doctor/slot not in DB?

Usage:
  export VAPI_API_KEY=...
  export VAPI_ASSISTANT_ID=...
  export BACKEND_URL=...          # for seeding pre-conditions
  python harness.py               # runs all scenarios
  python harness.py --id book_happy_path  # single scenario
"""

import argparse
import json
import os
import sys
import time
from datetime import date, timedelta, datetime
from typing import Any

import httpx

VAPI_API_KEY = os.environ.get("VAPI_API_KEY", "")
VAPI_ASSISTANT_ID = os.environ.get("VAPI_ASSISTANT_ID", "")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")

VAPI_CHAT_URL = "https://api.vapi.ai/chat"
HEADERS = {"Authorization": f"Bearer {VAPI_API_KEY}", "Content-Type": "application/json"}


# ── Helpers ────────────────────────────────────────────────────────────────

def _resolve_date(offset_days: int) -> str:
    return (date.today() + timedelta(days=offset_days)).isoformat()


def _seed_appointment(pre_seed: dict) -> str | None:
    """Book an appointment in the backend so we can test conflict/cancel flows."""
    payload = {
        "patient_name": pre_seed["patient_name"],
        "patient_phone": pre_seed["patient_phone"],
        "doctor_name": pre_seed["doctor"],
        "date": _resolve_date(pre_seed.get("date_offset_days", 1)),
        "time": pre_seed["time"],
        "reason": "pre-seeded for eval",
    }
    r = httpx.post(f"{BACKEND_URL}/book_appointment", json=payload, timeout=10)
    if r.status_code == 200 and r.json().get("success"):
        return r.json()["confirmation_code"]
    return None


def _chat_turn(thread_id: str | None, message: str) -> tuple[str, list[str], float, int]:
    """
    Send one user message to Vapi chat.
    Returns (thread_id, tool_calls_made, latency_ms, agent_tokens).
    """
    body: dict[str, Any] = {
        "assistantId": VAPI_ASSISTANT_ID,
        "input": message,
    }
    if thread_id:
        body["sessionId"] = thread_id

    t0 = time.perf_counter()
    r = httpx.post(VAPI_CHAT_URL, json=body, headers=HEADERS, timeout=30)
    latency = (time.perf_counter() - t0) * 1000

    r.raise_for_status()
    data = r.json()

    new_thread_id = data.get("sessionId", thread_id)
    reply = data.get("output", "")
    tool_calls = [m["name"] for m in data.get("toolCalls", [])]
    tokens = data.get("usage", {}).get("outputTokens", len(reply.split()))

    return new_thread_id, reply, tool_calls, latency, tokens


def _llm_judge(scenario_id: str, conversation_log: list[dict], expected: dict) -> dict:
    """
    Use Claude Haiku as a cheap judge to score conversation quality.
    Returns scores dict.
    """
    prompt = f"""You are evaluating a voice receptionist AI for a hospital.

Scenario: {scenario_id}
Expected outcome: {json.dumps(expected)}

Conversation:
{json.dumps(conversation_log, indent=2)}

Score each dimension 0-10:
1. task_completion: Did the agent achieve the patient's goal?
2. naturalness: Did responses sound like a real receptionist (concise, friendly)?
3. error_recovery: Did the agent handle problems gracefully?
4. no_hallucination: Did the agent avoid inventing doctors/slots? (10=no hallucination)

Reply with ONLY valid JSON: {{"task_completion": N, "naturalness": N, "error_recovery": N, "no_hallucination": N, "notes": "..."}}"""

    r = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": os.environ.get("ANTHROPIC_API_KEY", ""),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 300,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=20,
    )
    if r.status_code != 200:
        return {"task_completion": -1, "naturalness": -1, "error_recovery": -1, "no_hallucination": -1, "notes": "judge failed"}
    text = r.json()["content"][0]["text"]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"task_completion": -1, "naturalness": -1, "error_recovery": -1, "no_hallucination": -1, "notes": text}


# ── Scenario runner ────────────────────────────────────────────────────────

def run_scenario(scenario: dict) -> dict:
    sid = scenario["id"]
    print(f"\n{'='*60}")
    print(f"Running: {sid}")
    print(f"{'='*60}")

    confirmation_code = None

    # Pre-seed if needed
    if "pre_seed" in scenario:
        confirmation_code = _seed_appointment(scenario["pre_seed"])
        print(f"  Pre-seeded appointment: {confirmation_code}")

    thread_id = None
    all_tool_calls: list[str] = []
    latencies: list[float] = []
    token_counts: list[int] = []
    conversation_log: list[dict] = []

    for turn in scenario["conversation"]:
        msg = turn["content"]
        if confirmation_code:
            msg = msg.replace("{{confirmation_code}}", confirmation_code)

        print(f"  > USER: {msg}")
        try:
            thread_id, reply, tool_calls, latency, tokens = _chat_turn(thread_id, msg)
        except Exception as e:
            print(f"  ! ERROR: {e}")
            return {"scenario": sid, "error": str(e)}

        all_tool_calls.extend(tool_calls)
        latencies.append(latency)
        token_counts.append(tokens)
        conversation_log.append({"role": "user", "content": msg})
        conversation_log.append({"role": "assistant", "content": reply, "tool_calls": tool_calls})
        print(f"  < AGENT ({latency:.0f}ms, tools={tool_calls}): {reply[:120]}")

    # Structural checks
    expected = scenario["expected_outcome"]
    expected_tool = expected.get("tool_called")
    tool_accuracy = 1 if (expected_tool and expected_tool in all_tool_calls) else 0

    # LLM judge
    scores = _llm_judge(sid, conversation_log, expected)

    result = {
        "scenario": sid,
        "tool_accuracy": tool_accuracy,
        "tools_called": list(set(all_tool_calls)),
        "latency_p50_ms": sorted(latencies)[len(latencies) // 2],
        "latency_p95_ms": sorted(latencies)[int(len(latencies) * 0.95)] if len(latencies) > 1 else latencies[-1],
        "avg_tokens_per_turn": sum(token_counts) / len(token_counts) if token_counts else 0,
        "llm_scores": scores,
    }

    print(f"  Result: tool_acc={tool_accuracy}, scores={scores}")
    return result


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", help="Run only this scenario id")
    parser.add_argument("--output", default="eval/results.json")
    args = parser.parse_args()

    if not VAPI_API_KEY or not VAPI_ASSISTANT_ID:
        print("ERROR: Set VAPI_API_KEY and VAPI_ASSISTANT_ID env vars")
        sys.exit(1)

    with open("eval/scenarios.json") as f:
        scenarios = json.load(f)

    if args.id:
        scenarios = [s for s in scenarios if s["id"] == args.id]
        if not scenarios:
            print(f"Scenario '{args.id}' not found")
            sys.exit(1)

    results = [run_scenario(s) for s in scenarios]

    # Aggregate
    valid = [r for r in results if "error" not in r]
    if valid:
        avg_task = sum(r["llm_scores"].get("task_completion", 0) for r in valid) / len(valid)
        avg_tool_acc = sum(r["tool_accuracy"] for r in valid) / len(valid)
        all_latencies = [r["latency_p50_ms"] for r in valid]
        overall_p50 = sorted(all_latencies)[len(all_latencies) // 2]

        summary = {
            "total_scenarios": len(scenarios),
            "passed": len(valid),
            "avg_task_completion_score": round(avg_task, 2),
            "tool_accuracy_rate": round(avg_tool_acc, 2),
            "overall_latency_p50_ms": round(overall_p50, 1),
            "timestamp": datetime.utcnow().isoformat(),
        }
    else:
        summary = {"error": "All scenarios failed"}

    output = {"summary": summary, "scenarios": results}
    os.makedirs("eval", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(json.dumps(summary, indent=2))
    print(f"\nFull results written to {args.output}")


if __name__ == "__main__":
    main()
