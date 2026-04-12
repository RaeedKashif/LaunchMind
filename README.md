# OutreachPilot — Multi-Agent System

## Startup Idea

**OutreachPilot** helps Pakistan-based freelancers automate US client outreach. Given a service focus (e.g., "AI Voice Call Agents") and a target audience (e.g., "Local US Business Owners"), a team of five AI agents collaboratively produces personalized LinkedIn messages, follow-up DMs, posts, cold emails, and social drafts — and takes real actions on real platforms (GitHub PR, Slack launch post, SendGrid email).

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
git clone <this repo>
cd outreachpilot
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # then fill in your real keys
python main.py
```

### Required env vars

See [.env.example](.env.example):

- `GROQ_API_KEY` — Groq API key (free tier, used with `llama-3.3-70b-versatile`)
- `GITHUB_TOKEN` + `GITHUB_REPO` — PAT with `repo` scope and target repo (format `user/repo`)
- `SLACK_BOT_TOKEN` + `SLACK_CHANNEL` — Slack bot with `chat:write` in the channel
- `SENDGRID_API_KEY` + `SENDGRID_FROM_EMAIL` + `TEST_EMAIL`

## Platforms Used

- **GitHub** — Engineer Agent creates an issue, a branch, commits `index.html`, opens a PR. QA Agent posts an automated review on that PR.
- **Slack** — Marketing Agent posts a Block Kit launch message; CEO posts the final summary.
- **SendGrid** — Marketing Agent sends the generated cold outreach email.

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

All messages flow through [message_bus.py](message_bus.py) and are printed to the terminal in real time. A full JSON log is saved to `message_log.json` at the end of the run.

## File Layout

- [main.py](main.py) — entry point
- [message_bus.py](message_bus.py) — shared dict-based bus + logger
- [llm_client.py](llm_client.py) — shared Claude client and JSON parser
- [agents/ceo_agent.py](agents/ceo_agent.py) — orchestrator + feedback loops
- [agents/product_agent.py](agents/product_agent.py) — product spec generator
- [agents/engineer_agent.py](agents/engineer_agent.py) — HTML + real GitHub PR
- [agents/marketing_agent.py](agents/marketing_agent.py) — copy + real email + Slack
- [agents/qa_agent.py](agents/qa_agent.py) — LLM review + PR review comments
