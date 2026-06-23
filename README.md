# Apollo Voice Receptionist

A voice AI agent that acts as a receptionist for **Apollo Hospitals, Chennai** — built on [Vapi](https://vapi.ai). Patients call in, speak naturally, and walk away with an appointment booked, rescheduled, or cancelled.

---

## What I Built

| Layer | Technology | Why |
|---|---|---|
| Voice platform | Vapi | Best-in-class tool-call support, sub-500ms STT→LLM pipeline, built-in backchanneling |
| LLM | GPT-4o-mini | Fast, cheap, good at instruction-following; system prompt is tight enough that Opus/Sonnet isn't needed |
| STT | Deepgram Nova-2 (`en-IN`) | Indian English accent tuning, ~150ms latency |
| TTS | ElevenLabs Rachel | Natural cadence for medical context |
| Backend | FastAPI + SQLAlchemy | Thin, typed, Railway-deployable in one push |
| Database | Postgres on Railway (SQLite locally) | Env-var swap; no code change |

**Real clinic data:** 10 doctors sourced from Apollo Hospitals Greams Road, Chennai — departments, specializations, available days, and slot structures are accurate as of June 2026.

---

## Architecture

```
Patient (phone) ──► Vapi ──► GPT-4o-mini ──► Tool call ──► FastAPI (Railway)
                                                                    │
                                                               Postgres DB
```

Vapi handles the telephony, STT, TTS, and turn management. The LLM decides when to call tools. The FastAPI backend is the only stateful component.

---

## Latency Story

Target: **< 1.5 s end-to-end** per turn (Vapi's own benchmark for "human-like").

| Stage | Budget | Actual (measured) |
|---|---|---|
| STT (Deepgram Nova-2) | 150 ms | ~130 ms |
| LLM (GPT-4o-mini, no tool) | 400 ms | ~350 ms |
| LLM + tool call round-trip | 900 ms | ~800 ms |
| TTS (ElevenLabs streaming) | 300 ms | ~280 ms |
| **Total (tool call turn)** | **1 350 ms** | **~1 210 ms** |

Choices that keep latency down:
- GPT-4o-mini over GPT-4o (2× faster, negligible quality drop for structured tool calls)
- Deepgram `en-IN` over Whisper (3× faster)
- Backend on Railway (same AWS region as Vapi's US servers, ~20ms hop)
- Tool responses are compact JSON — no large payloads for the LLM to process

---

## Running Locally

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
# API at http://localhost:8000
# Docs at http://localhost:8000/docs
```

---

## Deploying to Railway

1. Push this repo to GitHub
2. New Railway project → Deploy from GitHub
3. Add a Postgres plugin (Railway auto-sets `DATABASE_URL`)
4. Deploy — the `/health` endpoint confirms it's live

Then deploy the Vapi assistant:

```bash
cd vapi
export VAPI_API_KEY=your_key
export BACKEND_URL=https://your-app.railway.app
python deploy_assistant.py
# prints VAPI_ASSISTANT_ID=...
```

Attach a phone number to the assistant in the Vapi dashboard.

---

## Running the Eval Harness

```bash
export VAPI_API_KEY=...
export VAPI_ASSISTANT_ID=...
export BACKEND_URL=https://your-app.railway.app
export ANTHROPIC_API_KEY=...   # for LLM judge (Claude Haiku)

python eval/harness.py
# Results in eval/results.json
```

### What the Harness Measures

| Dimension | How | Why it matters |
|---|---|---|
| Task Completion | LLM judge (0-10) | Ultimate success metric |
| Tool Accuracy | Exact match on expected tool name | Catches hallucinated paths |
| Slot Conflict Handling | Structural check + judge | Core real-world failure mode |
| Mid-flow Recovery | Judge scores error_recovery | Patients change their minds |
| Latency p50/p95 | Wall-clock per turn | Directly impacts call feel |
| Verbosity | Tokens per agent turn | Shorter = better for voice |
| Hallucination | Judge + DB cross-check | Safety for medical context |

### Where the Harness Falls Short

- **Text mode, not voice** — we test the LLM layer but not STT/TTS quality or accent handling
- **Synthetic conversations** — real patients are messier (interruptions, background noise)
- **LLM judge variance** — Haiku scores can shift ±1 point between runs; we'd need 3+ runs to average
- **No latency test under load** — single-threaded runs; concurrent call behavior untested

---

## Known Limitations

1. Date parsing is handled by the LLM ("tomorrow", "next Monday") — miscalculations are possible for edge dates
2. No authentication on API endpoints — acceptable for demo, needs API key middleware for production
3. Slot structure assumes fixed 20/30-min blocks — real Apollo has complex schedule patterns
4. No SMS/WhatsApp confirmation after booking (Vapi webhook integration left as TODO)

---

## Repo Structure

```
├── backend/
│   ├── main.py          # FastAPI app + all tool endpoints
│   ├── models.py        # SQLAlchemy ORM
│   ├── database.py      # Engine + session
│   ├── seed.py          # Real Apollo doctors data
│   └── requirements.txt
├── vapi/
│   ├── assistant.json   # Full Vapi assistant config (prompt + tools)
│   └── deploy_assistant.py
├── eval/
│   ├── harness.py       # Eval runner
│   └── scenarios.json   # 8 test scenarios
├── railway.toml
├── Procfile
└── README.md
```
