"""
Eval harness for Apollo Voice Receptionist.

Tests the backend tool layer directly — this is the correct approach because:
1. Vapi Chat API requires a paid account
2. The backend is where correctness lives; voice quality is evaluated via real calls
3. Results are fully deterministic and re-runnable

Dimensions measured:
1. Task Completion    — did the tool return success?
2. Tool Correctness   — did the right data come back?
3. Conflict Handling  — does it offer alternatives when slot taken?
4. Fuzzy Name Match   — does phonetic/misspelled name still resolve?
5. Cancel Robustness  — does code cleanup (minus/dash) work?
6. Latency p50/p95    — round-trip ms per call

Usage:
  export BACKEND_URL=https://web-production-c64ce.up.railway.app
  python eval/harness.py
  python eval/harness.py --id fuzzy_name
"""

import argparse, json, os, sys, time
from datetime import date, timedelta

import httpx

BACKEND = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")
TODAY = date.today().isoformat()
TOMORROW = (date.today() + timedelta(days=1)).isoformat()
_today = date.today()
# Eval uses dates 60 days out so they never collide with real appointments
_base = _today + timedelta(days=60)
# Find next Monday >= base (Hariprasad is Mon-Fri)
EVAL_MON = (_base + timedelta(days=(7 - _base.weekday()) % 7)).isoformat()
# Find next Thursday >= base (Anita Reddy: Tue/Thu, Lakshmi Nair: Tue/Thu)
EVAL_THU = (_base + timedelta(days=(3 - _base.weekday()) % 7)).isoformat()
NEXT_MON = (_today + timedelta(days=(7 - _today.weekday()))).isoformat()
NEXT_THU = (_today + timedelta(days=(3 - _today.weekday()) % 7 or 7)).isoformat()

client = httpx.Client(timeout=15)


def call(path, payload=None, method="POST"):
    t0 = time.perf_counter()
    if method == "GET":
        r = client.get(f"{BACKEND}{path}")
    else:
        r = client.post(f"{BACKEND}{path}", json=payload or {})
    ms = (time.perf_counter() - t0) * 1000
    return r.json(), ms, r.status_code


# ── Seed a real appointment for reschedule/cancel tests ───────────────────
def seed_appt(doctor, day, time_slot, phone="9999999999", name="Eval Patient"):
    data, _, _ = call("/book_appointment", {
        "patient_name": name, "patient_phone": phone,
        "doctor_name": doctor, "date": day, "time": time_slot, "reason": "eval"
    })
    return data.get("confirmation_code")


# ── Test scenarios ─────────────────────────────────────────────────────────
SCENARIOS = [

    {
        "id": "health_check",
        "desc": "Backend is up",
        "fn": lambda: call("/health", method="GET"),
        "check": lambda d, ms, sc: sc == 200 and d.get("status") == "ok",
        "metric": "availability",
    },
    {
        "id": "list_all_doctors",
        "desc": "All 10 doctors returned",
        "fn": lambda: call("/list_doctors", {}),
        "check": lambda d, ms, sc: len(d.get("doctors", [])) == 10,
        "metric": "data_completeness",
    },
    {
        "id": "list_by_dept",
        "desc": "Filter by Cardiology returns 2 doctors",
        "fn": lambda: call("/list_doctors", {"department": "Cardiology"}),
        "check": lambda d, ms, sc: len(d.get("doctors", [])) == 2,
        "metric": "filter_accuracy",
    },
    {
        "id": "fuzzy_name_exact",
        "desc": "Exact name resolves correctly",
        "fn": lambda: call("/check_slots", {"doctor_name": "Dr. K. Hariprasad", "date": TOMORROW}),
        "check": lambda d, ms, sc: d.get("doctor") == "Dr. K. Hariprasad",
        "metric": "name_resolution",
    },
    {
        "id": "fuzzy_name_partial",
        "desc": "Partial name 'Hariprasad' resolves",
        "fn": lambda: call("/check_slots", {"doctor_name": "Hariprasad", "date": TOMORROW}),
        "check": lambda d, ms, sc: "Hariprasad" in d.get("doctor", ""),
        "metric": "name_resolution",
    },
    {
        "id": "fuzzy_name_phonetic",
        "desc": "Phonetic 'Harry Prasad' resolves to Dr. K. Hariprasad",
        "fn": lambda: call("/check_slots", {"doctor_name": "Harry Prasad", "date": TOMORROW}),
        "check": lambda d, ms, sc: "Hariprasad" in d.get("doctor", ""),
        "metric": "name_resolution",
    },
    {
        "id": "fuzzy_name_suresh",
        "desc": "Partial 'Suresh' resolves to Dr. Suresh Rao",
        "fn": lambda: call("/check_slots", {"doctor_name": "Suresh", "date": NEXT_MON}),
        "check": lambda d, ms, sc: "Suresh" in d.get("doctor", ""),
        "metric": "name_resolution",
    },
    {
        "id": "slots_available",
        "desc": "Slots returned for available doctor on weekday",
        "fn": lambda: call("/check_slots", {"doctor_name": "Dr. K. Hariprasad", "date": TOMORROW}),
        "check": lambda d, ms, sc: len(d.get("available_slots", [])) > 0,
        "metric": "slot_availability",
    },
    {
        "id": "slots_unavailable_day",
        "desc": "No slots when doctor not working that day",
        "fn": lambda: call("/check_slots", {"doctor_name": "Dr. Suresh Rao", "date": TOMORROW}),
        # Suresh Rao: Mon,Wed,Fri — tomorrow is Thu
        "check": lambda d, ms, sc: len(d.get("available_slots", [])) == 0 or d.get("available_slots") == [],
        "metric": "slot_availability",
    },
    {
        "id": "book_happy_path",
        "desc": "Successful booking returns confirmation code",
        "fn": lambda: call("/book_appointment", {
            "patient_name": "Eval User", "patient_phone": "8888888888",
            "doctor_name": "Dr. K. Hariprasad", "date": EVAL_MON, "time": "09:00", "reason": "eval"
        }),
        "check": lambda d, ms, sc: d.get("success") is True and d.get("confirmation_code", "").startswith("APL"),
        "metric": "booking",
    },
    {
        "id": "book_conflict",
        "desc": "Double-booking same slot returns alternatives",
        "fn": lambda: call("/book_appointment", {
            "patient_name": "Eval User 2", "patient_phone": "7777777777",
            "doctor_name": "Dr. K. Hariprasad", "date": EVAL_MON, "time": "09:00", "reason": "eval"
        }),
        "check": lambda d, ms, sc: d.get("success") is False and len(d.get("alternatives", [])) > 0,
        "metric": "conflict_handling",
    },
    {
        "id": "cancel_clean_code",
        "desc": "Cancel with 'minus/dash' phonetic code still works",
        "fn": lambda: _cancel_phonetic_test(),
        "check": lambda d, ms, sc: d.get("success") is True,
        "metric": "cancel_robustness",
    },
    {
        "id": "reschedule_flow",
        "desc": "Reschedule moves appointment to new slot",
        "fn": lambda: _reschedule_test(),
        "check": lambda d, ms, sc: d.get("success") is True,
        "metric": "reschedule",
    },
    {
        "id": "lookup_by_phone",
        "desc": "Lookup returns scheduled appointments for phone",
        "fn": lambda: call("/lookup_appointments", {"patient_phone": "8888888888"}),
        "check": lambda d, ms, sc: isinstance(d.get("appointments"), list),
        "metric": "lookup",
    },
    {
        "id": "latency_list_doctors",
        "desc": "list_doctors responds under 500ms",
        "fn": lambda: call("/list_doctors", {}),
        "check": lambda d, ms, sc: ms < 500,
        "metric": "latency",
    },
    {
        "id": "latency_check_slots",
        "desc": "check_slots responds under 500ms",
        "fn": lambda: call("/check_slots", {"doctor_name": "Dr. K. Hariprasad", "date": TOMORROW}),
        "check": lambda d, ms, sc: ms < 500,
        "metric": "latency",
    },
    {
        "id": "latency_book",
        "desc": "book_appointment responds under 800ms",
        "fn": lambda: call("/book_appointment", {
            "patient_name": "Latency Test", "patient_phone": "6666666666",
            "doctor_name": "Dr. Venkat Subramanian", "date": TOMORROW, "time": "11:00"
        }),
        "check": lambda d, ms, sc: ms < 800,
        "metric": "latency",
    },
]


def _cancel_phonetic_test():
    code = None
    for slot in ["09:00", "09:30", "10:00", "10:30", "11:00", "11:30"]:
        code = seed_appt("Dr. Anita Reddy", EVAL_THU, slot, phone="5555555551", name=f"Eval Cancel {slot}")
        if code:
            break
    if not code:
        return {"success": False}, 0, 400
    # Simulate phonetic input: "APL123456" → "A-P-L-minus-1-minus-2-3-4-5-6"
    phonetic = code[0]+"-"+code[1]+"-"+code[2]+"-minus-"+"minus-".join(code[3:])
    return call("/cancel_appointment", {"confirmation_code": phonetic})


def _reschedule_test():
    code = None
    for slot in ["10:00", "10:20", "10:40", "11:00", "11:20", "11:40"]:
        code = seed_appt("Dr. Lakshmi Nair", EVAL_THU, slot, phone="5555555552", name=f"Eval Reschedule {slot}")
        if code:
            break
    if not code:
        return {"success": False}, 0, 400
    new_time = "10:20"
    return call("/reschedule_appointment", {
        "confirmation_code": code, "new_date": NEXT_MON, "new_time": new_time
    })


# ── Runner ─────────────────────────────────────────────────────────────────
def run_scenario(s):
    print(f"  [{s['id']}] {s['desc']}", end=" ... ")
    try:
        result = s["fn"]()
        if isinstance(result, tuple) and len(result) == 3:
            d, ms, sc = result
        else:
            d, ms, sc = result, 0, 200
        passed = s["check"](d, ms, sc)
        status = "PASS" if passed else "FAIL"
        print(f"{status} ({ms:.0f}ms)")
        return {"id": s["id"], "desc": s["desc"], "metric": s["metric"],
                "passed": passed, "latency_ms": round(ms, 1), "response": d}
    except Exception as e:
        print(f"ERROR: {e}")
        return {"id": s["id"], "desc": s["desc"], "metric": s["metric"],
                "passed": False, "error": str(e)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", help="Run single scenario by id")
    parser.add_argument("--output", default="eval/results.json")
    args = parser.parse_args()

    scenarios = SCENARIOS
    if args.id:
        scenarios = [s for s in SCENARIOS if s["id"] == args.id]
        if not scenarios:
            print(f"Scenario '{args.id}' not found"); sys.exit(1)

    print(f"\nApollo Receptionist Eval -- {TODAY}")
    print(f"  Backend: {BACKEND}")
    print(f"  Running {len(scenarios)} scenarios\n")

    results = [run_scenario(s) for s in scenarios]

    passed = sum(1 for r in results if r.get("passed"))
    total = len(results)
    latencies = [r["latency_ms"] for r in results if r.get("latency_ms", 0) > 0]
    latencies.sort()
    p50 = latencies[len(latencies)//2] if latencies else 0
    p95 = latencies[int(len(latencies)*0.95)] if latencies else 0

    by_metric = {}
    for r in results:
        m = r["metric"]
        by_metric.setdefault(m, {"pass": 0, "fail": 0})
        by_metric[m]["pass" if r["passed"] else "fail"] += 1

    summary = {
        "date": TODAY, "backend": BACKEND,
        "total": total, "passed": passed, "failed": total - passed,
        "pass_rate": f"{passed/total*100:.0f}%",
        "latency_p50_ms": round(p50, 1), "latency_p95_ms": round(p95, 1),
        "by_metric": by_metric,
    }

    print(f"\n{'--'*25}")
    print(f"  Result: {passed}/{total} passed ({summary['pass_rate']})")
    print(f"  Latency p50={p50:.0f}ms  p95={p95:.0f}ms")
    print(f"  By metric: {json.dumps(by_metric)}")

    os.makedirs("eval", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump({"summary": summary, "scenarios": results}, f, indent=2)
    print(f"\n  Full results saved to: {args.output}\n")


if __name__ == "__main__":
    main()
