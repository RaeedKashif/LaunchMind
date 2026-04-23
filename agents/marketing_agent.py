"""Marketing Agent — generates copy, sends real email, posts to Slack."""
import json
import os
import smtplib
import ssl
from email.message import EmailMessage

import requests

from llm_client import call_llm, parse_llm_json
from message_bus import new_message


SYSTEM_PROMPT = (
    "You are the Marketing Agent on the OutreachPilot startup team. "
    "You write punchy, specific launch copy for a tool that helps Pakistan-based "
    "freelancers automate US client outreach. Never generic."
)


def _copy_prompt(product_spec: dict, service_focus: str, target_audience: str, feedback: str = None) -> str:
    base = f"""Generate launch marketing copy for OutreachPilot.

Product spec:
{json.dumps(product_spec, indent=2)}

Service focus: {service_focus}
Target audience: {target_audience}

Return a JSON object with EXACTLY these fields:
{{
  "tagline": "under 10 words",
  "description": "2-3 sentence landing page description",
  "email_subject": "cold outreach subject line",
  "email_body": "cold outreach email body addressed to a Pakistan-based freelancer; must have a clear CTA",
  "social_posts": {{
    "twitter": "under 280 chars",
    "linkedin": "professional, 3-5 sentences",
    "instagram": "casual with hashtag suggestions"
  }}
}}

Respond ONLY with valid JSON. No text before or after."""
    if feedback:
        base += f"\n\nIMPORTANT — revising per QA feedback:\n{feedback}\nAddress every issue."
    return base


class MarketingAgent:
    def __init__(self, message_bus):
        self.message_bus = message_bus
        self.current_copy = None
        self.current_task_payload = None

    def _generate(self, payload, feedback=None):
        prompt = _copy_prompt(
            payload["product_spec"],
            payload.get("service_focus", ""),
            payload.get("target_audience", ""),
            feedback=feedback,
        )
        return parse_llm_json(call_llm(SYSTEM_PROMPT, prompt))

    def _send_email(self, copy: dict) -> str:
        try:
            sender = os.environ["GMAIL_ADDRESS"]
            password = os.environ["GMAIL_APP_PASSWORD"]
            recipient = os.environ["TEST_EMAIL"]

            msg = EmailMessage()
            msg["From"] = sender
            msg["To"] = recipient
            msg["Subject"] = copy["email_subject"]
            msg.set_content(copy["email_body"])
            msg.add_alternative(
                f"<html><body>{copy['email_body']}</body></html>", subtype="html"
            )

            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as server:
                server.login(sender, password)
                server.send_message(msg)
            print(f"  [Gmail SMTP] sent to {recipient}")
            return "sent"
        except Exception as e:
            print(f"  [Gmail SMTP] failed: {e}")
            return f"error:{e}"

    def _post_to_slack(self, tagline: str, description: str, pr_url: str) -> str:
        try:
            payload = {
                "channel": os.environ["SLACK_CHANNEL"],
                "blocks": [
                    {"type": "header", "text": {"type": "plain_text", "text": f"🚀 New Launch: {tagline}"}},
                    {"type": "section", "text": {"type": "mrkdwn", "text": description}},
                    {"type": "section", "fields": [
                        {"type": "mrkdwn", "text": f"*GitHub PR:* <{pr_url}|View PR>"},
                        {"type": "mrkdwn", "text": "*Status:* Ready for review"},
                    ]},
                    {"type": "divider"},
                    {"type": "context", "elements": [
                        {"type": "mrkdwn", "text": "Posted by OutreachPilot Marketing Agent 🤖"}
                    ]},
                ],
            }
            r = requests.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {os.environ['SLACK_BOT_TOKEN']}"},
                json=payload,
            )
            ok = r.json().get("ok")
            print(f"  [Slack] posted: {ok}")
            return "posted" if ok else f"error:{r.json().get('error')}"
        except Exception as e:
            print(f"  [Slack] failed: {e}")
            return f"error:{e}"

    def handle_task(self, msg):
        mtype = msg["message_type"]
        payload = msg["payload"]

        if mtype == "task" and "pr_url" not in payload:
            # Phase 1: generate copy + send email
            self.current_task_payload = payload
            copy = self._generate(payload)
            self.current_copy = copy
            email_status = self._send_email(copy)

            self.message_bus.send(new_message(
                from_agent="marketing",
                to_agent="ceo",
                message_type="result",
                payload={
                    "summary": "Copy generated and email sent",
                    **copy,
                    "email_status": email_status,
                    "slack_status": "pending",
                },
                parent_message_id=msg["message_id"],
            ))

        elif mtype == "task" and "pr_url" in payload:
            # Phase 2: post to Slack with PR URL
            pr_url = payload["pr_url"]
            copy = self.current_copy or {}
            slack_status = self._post_to_slack(
                copy.get("tagline", "OutreachPilot"),
                copy.get("description", "AI outreach automation for Pakistan-based freelancers."),
                pr_url,
            )
            self.message_bus.send(new_message(
                from_agent="marketing",
                to_agent="ceo",
                message_type="confirmation",
                payload={"summary": "Slack launch post delivered", "slack_status": slack_status},
                parent_message_id=msg["message_id"],
            ))

        elif mtype == "revision_request":
            feedback = payload.get("feedback", "")
            copy = self._generate(self.current_task_payload, feedback=feedback)
            self.current_copy = copy
            self.message_bus.send(new_message(
                from_agent="marketing",
                to_agent="ceo",
                message_type="result",
                payload={
                    "summary": "Revised marketing copy",
                    **copy,
                    "revised": True,
                },
                parent_message_id=msg["message_id"],
            ))
