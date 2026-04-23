# OutreachPilot — Multi-Agent System

## Startup Idea

**OutreachPilot** helps Pakistan-based freelancers automate US client outreach. Given a service focus (e.g., "AI Voice Call Agents") and a target audience (e.g., "Local US Business Owners"), a team of five AI agents collaboratively produces personalized LinkedIn messages, follow-up DMs, posts, cold emails, and social drafts — and takes real actions on real platforms (GitHub PR, Slack launch post, email).

## Agent Architecture

```
                    ┌──────────────────┐
   Startup Idea ──→ │    CEO Agent     │ ──→ Final Slack Summary
                    │  (Orchestrator)  │
                    └──┬───┬───┬───┬───┘
                       │   │   │   │
            ┌──────────┘   │   │   └──────────┐
            ▼              ▼   ▼              ▼
    ┌───────────┐  ┌──────────┐ ┌───────────┐ ┌──────────┐
    │  Product  │  │ Engineer │ │ Marketing │ │    QA    │
    │   Agent   │  │  Agent   │ │   Agent   │ │  Agent   │
    └───────────┘  └──────────┘ └───────────┘ └──────────┘
    Generates       Builds HTML   Sends email   Reviews
    product spec    + GitHub PR   + Slack post   all outputs
```

### Feedback Loops

1. **Product revision loop** — the CEO uses the LLM to review the Product Agent's spec. If the verdict is `revise`, a `revision_request` is sent back and the Product Agent regenerates (max 2 cycles).
2. **QA-triggered revision loop** — the QA Agent returns a `pass`/`fail` verdict; on `fail` the CEO forwards a revision request to Engineer or Marketing and re-runs QA (max 2 cycles).

## Setup

```bash
git clone https://github.com/RaeedKashif/LaunchMind.git
cd LaunchMind
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # then fill in your real keys
python main.py
```

### Required env vars

See [.env.example](.env.example):

- `GROQ_API_KEY` — primary Groq API key
- `GROQ_API_KEY_2` *(optional)* — fallback Groq API key (rotated to on rate limit)
- `GITHUB_TOKEN` + `GITHUB_REPO` — PAT with `repo` scope, repo as `user/repo`
- `SLACK_BOT_TOKEN` + `SLACK_CHANNEL` — Slack bot with `chat:write` (and ideally `chat:write.public`) in the channel
- `GMAIL_ADDRESS` + `GMAIL_APP_PASSWORD` + `TEST_EMAIL` — Gmail account with an [App Password](https://myaccount.google.com/apppasswords) for SMTP, plus a recipient inbox

## LLM (Groq, free tier)

[llm_client.py](llm_client.py) uses a tier-based fallback chain. Each tier is a `(model, key)` pair; on `429` / `401` / `403` / `413` it advances immediately to the next tier with no sleep. After every tier is exhausted, it falls back to exponential backoff on the last tier.

| Tier | Model | Key |
|---|---|---|
| 1 | `llama-3.3-70b-versatile` | `GROQ_API_KEY` |
| 2 | `llama-3.3-70b-versatile` | `GROQ_API_KEY_2` |
| 3 | `llama-3.1-8b-instant` | `GROQ_API_KEY` |
| 4 | `llama-3.1-8b-instant` | `GROQ_API_KEY_2` |

70b is preferred for output quality; 8b serves as a high-quota safety net once the 70b daily token budget is spent. Add more keys (`GROQ_API_KEY_3`, `_4`, ...) and the chain extends automatically.

## Platforms Used

- **GitHub** — Engineer Agent creates an issue, a branch (`agent-landing-page`), commits `index.html`, and opens a PR. QA Agent posts a review (or fallback issue comment) on that PR.
- **Slack** — Marketing Agent posts a Block Kit launch message; CEO posts the final summary.
- **Gmail SMTP** — Marketing Agent sends the generated cold outreach email via `smtp.gmail.com:465`.

## Message Schema

Every inter-agent message follows:

```json
{
  "message_id": "msg-xxxxxxxx",
  "from_agent": "ceo",
  "to_agent": "product",
  "message_type": "task",
  "payload": {},
  "timestamp": "ISO8601",
  "parent_message_id": "msg-xxxxxxxx"
}
```

`message_type` is one of `task`, `result`, `revision_request`, `confirmation`. All messages flow through [message_bus.py](message_bus.py) and are printed to the terminal in real time. A full JSON log is saved to `message_log.json` at the end of the run.

## File Layout

- [main.py](main.py) — entry point
- [message_bus.py](message_bus.py) — shared dict-based bus + logger
- [llm_client.py](llm_client.py) — Groq REST client with tier-based fallback + JSON parser
- [agents/ceo_agent.py](agents/ceo_agent.py) — orchestrator + feedback loops
- [agents/product_agent.py](agents/product_agent.py) — product spec generator
- [agents/engineer_agent.py](agents/engineer_agent.py) — HTML + real GitHub PR
- [agents/marketing_agent.py](agents/marketing_agent.py) — copy + Gmail SMTP + Slack
- [agents/qa_agent.py](agents/qa_agent.py) — LLM review + PR review comments
