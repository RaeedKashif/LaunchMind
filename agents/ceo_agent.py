"""CEO Agent — orchestrator with feedback loops."""
import json
import os
import requests

from llm_client import call_llm, parse_llm_json
from message_bus import new_message


DECOMPOSE_SYSTEM = (
    "You are the CEO of the OutreachPilot startup. You decompose a startup idea into "
    "concrete, specific tasks for your Product, Engineer, and Marketing leads. "
    "Your task descriptions must always reference the specific service focus and "
    "target audience."
)

REVIEW_SYSTEM = (
    "You are a demanding startup CEO reviewing artifacts produced by your team. "
    "You insist on specificity, measurable outcomes, and relevance to the exact "
    "service/audience combination."
)

MAX_PRODUCT_REVISIONS = 2
MAX_QA_REVISIONS = 2


def _decompose_prompt(startup_idea, service_focus, target_audience):
    return f"""Startup idea:
{startup_idea}

Service focus: {service_focus}
Target audience: {target_audience}

Decompose this into three concrete task briefs, one for each of your leads. Each brief
must explicitly reference the service focus and target audience so outputs are specific.

Return ONLY a JSON object of the form:
{{
  "product_task": "detailed task brief for the Product Agent",
  "engineer_task": "detailed task brief for the Engineer Agent",
  "marketing_task": "detailed task brief for the Marketing Agent"
}}"""


def _review_prompt(product_spec, service_focus, target_audience):
    return f"""Service focus: {service_focus}
Target audience: {target_audience}

Review this product specification:
{json.dumps(product_spec, indent=2)}

Check:
1. Is the value proposition specific to THIS service and audience (not generic)?
2. Do the personas have concrete, measurable pain points?
3. Are the 5 features actionable and correctly prioritized?
4. Are the user stories in proper "As a / I want / so that" form?

Return ONLY JSON:
{{"verdict": "approve" or "revise", "feedback": "specific, actionable feedback if revise; short approval note if approve"}}"""


class CEOAgent:
    def __init__(self, message_bus, product_agent, engineer_agent, marketing_agent, qa_agent):
        self.message_bus = message_bus
        self.product_agent = product_agent
        self.engineer_agent = engineer_agent
        self.marketing_agent = marketing_agent
        self.qa_agent = qa_agent
        self.decisions_log = []

    def _log(self, decision: str):
        self.decisions_log.append(decision)
        print(f"  [CEO] {decision}")

    def _drain(self, agent_name: str):
        return self.message_bus.receive(agent_name)

    def _wait_for_result(self, agent_name: str, handler):
        """Poll the named agent's inbox and dispatch all messages via handler
        until a result (or confirmation) message arrives addressed to ceo."""
        while True:
            msgs = self._drain(agent_name)
            for m in msgs:
                handler(m)
            # Check CEO inbox now
            ceo_msgs = self._drain("ceo")
            if ceo_msgs:
                return ceo_msgs
            # If nothing happened this iteration, break to avoid infinite loop.
            if not msgs:
                return []

    def _post_final_slack(self, product_spec, marketing_copy, pr_url):
        try:
            payload = {
                "channel": os.environ["SLACK_CHANNEL"],
                "blocks": [
                    {"type": "header", "text": {"type": "plain_text",
                        "text": f"✅ OutreachPilot Launch Complete"}},
                    {"type": "section", "text": {"type": "mrkdwn",
                        "text": f"*{marketing_copy.get('tagline', 'OutreachPilot')}*\n{product_spec.get('value_proposition', '')}"}},
                    {"type": "section", "fields": [
                        {"type": "mrkdwn", "text": f"*GitHub PR:* <{pr_url}|View PR>"},
                        {"type": "mrkdwn", "text": "*Status:* All agents reported success"},
                    ]},
                    {"type": "context", "elements": [
                        {"type": "mrkdwn", "text": "Final summary posted by CEO Agent 🤖"}
                    ]},
                ],
            }
            r = requests.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {os.environ['SLACK_BOT_TOKEN']}"},
                json=payload,
            )
            print(f"  [Slack] CEO final post: {r.json().get('ok')}")
        except Exception as e:
            print(f"  [Slack] CEO final post failed: {e}")

    def run(self, startup_idea: str, service_focus: str, target_audience: str):
        # STEP 1 — decompose
        self._log("Decomposing startup idea via LLM")
        decomposition = parse_llm_json(call_llm(
            DECOMPOSE_SYSTEM,
            _decompose_prompt(startup_idea, service_focus, target_audience),
        ))

        base_payload = {
            "startup_idea": startup_idea,
            "service_focus": service_focus,
            "target_audience": target_audience,
        }

        self.message_bus.send(new_message(
            from_agent="ceo", to_agent="product", message_type="task",
            payload={**base_payload, "task": decomposition["product_task"],
                     "summary": "Build product spec"},
        ))

        # STEP 2 — product agent runs
        product_msgs = self._drain("product")
        for m in product_msgs:
            self.product_agent.handle_task(m)

        # STEP 3 — review + feedback loop
        product_spec = None
        for attempt in range(MAX_PRODUCT_REVISIONS + 1):
            ceo_inbox = self._drain("ceo")
            if not ceo_inbox:
                break
            result_msg = ceo_inbox[-1]
            product_spec = result_msg["payload"]["product_spec"]

            self._log(f"Reviewing product spec (attempt {attempt + 1})")
            verdict = parse_llm_json(call_llm(
                REVIEW_SYSTEM,
                _review_prompt(product_spec, service_focus, target_audience),
            ))
            self._log(f"Verdict: {verdict['verdict']}")

            if verdict["verdict"] == "approve" or attempt == MAX_PRODUCT_REVISIONS:
                break

            # Send revision request
            self.message_bus.send(new_message(
                from_agent="ceo", to_agent="product", message_type="revision_request",
                payload={"summary": "Revise product spec",
                         "feedback": verdict["feedback"]},
                parent_message_id=result_msg["message_id"],
            ))
            for m in self._drain("product"):
                self.product_agent.handle_task(m)

        # STEP 4 — forward to Engineer and Marketing
        self._log("Forwarding approved spec to Engineer and Marketing")
        eng_task = new_message(
            from_agent="ceo", to_agent="engineer", message_type="task",
            payload={"summary": "Build landing page + PR",
                     "task": decomposition["engineer_task"],
                     "product_spec": product_spec},
        )
        mkt_task = new_message(
            from_agent="ceo", to_agent="marketing", message_type="task",
            payload={"summary": "Generate marketing copy + email",
                     "task": decomposition["marketing_task"],
                     "product_spec": product_spec,
                     "service_focus": service_focus,
                     "target_audience": target_audience},
        )
        self.message_bus.send(eng_task)
        self.message_bus.send(mkt_task)

        # STEP 5 — both agents run
        for m in self._drain("engineer"):
            self.engineer_agent.handle_task(m)
        for m in self._drain("marketing"):
            self.marketing_agent.handle_task(m)

        # Collect results
        eng_result = None
        mkt_result = None
        for m in self._drain("ceo"):
            if m["from_agent"] == "engineer":
                eng_result = m
            elif m["from_agent"] == "marketing":
                mkt_result = m

        pr_url = eng_result["payload"]["pr_url"] if eng_result else ""
        pr_number = eng_result["payload"].get("pr_number") if eng_result else None
        html_content = eng_result["payload"].get("html_content", "") if eng_result else ""
        marketing_copy = dict(mkt_result["payload"]) if mkt_result else {}

        # STEP — Marketing Slack post with PR URL
        self._log("Forwarding PR URL to Marketing for Slack post")
        self.message_bus.send(new_message(
            from_agent="ceo", to_agent="marketing", message_type="task",
            payload={"summary": "Post launch message to Slack", "pr_url": pr_url},
        ))
        for m in self._drain("marketing"):
            self.marketing_agent.handle_task(m)
        _ = self._drain("ceo")  # confirmation

        # STEP 6 — QA review
        self._log("Sending artifacts to QA Agent")
        self.message_bus.send(new_message(
            from_agent="ceo", to_agent="qa", message_type="task",
            payload={
                "summary": "Review HTML + marketing copy",
                "product_spec": product_spec,
                "html_content": html_content,
                "pr_url": pr_url,
                "pr_number": pr_number,
                "marketing_copy": marketing_copy,
            },
        ))
        for m in self._drain("qa"):
            self.qa_agent.handle_task(m)

        # STEP 7 — handle QA verdict (second feedback loop)
        for attempt in range(MAX_QA_REVISIONS):
            ceo_inbox = self._drain("ceo")
            if not ceo_inbox:
                break
            qa_msg = ceo_inbox[-1]
            qa_payload = qa_msg["payload"]
            if qa_payload.get("verdict") == "pass":
                self._log("QA passed")
                break

            target = qa_payload.get("target_agent_for_revision") or "engineer"
            feedback = qa_payload.get("revision_feedback", "")
            self._log(f"QA failed — requesting revision from {target}")
            self.message_bus.send(new_message(
                from_agent="ceo", to_agent=target, message_type="revision_request",
                payload={"summary": f"Revise per QA feedback",
                         "feedback": feedback},
                parent_message_id=qa_msg["message_id"],
            ))

            agent_obj = {
                "engineer": self.engineer_agent,
                "marketing": self.marketing_agent,
            }.get(target)
            if agent_obj:
                for m in self._drain(target):
                    agent_obj.handle_task(m)

            # Refresh artifacts from CEO inbox
            for m in self._drain("ceo"):
                if m["from_agent"] == "engineer":
                    html_content = m["payload"].get("html_content", html_content)
                    pr_url = m["payload"].get("pr_url", pr_url)
                    pr_number = m["payload"].get("pr_number", pr_number)
                elif m["from_agent"] == "marketing":
                    marketing_copy = dict(m["payload"])

            # Re-run QA
            self.message_bus.send(new_message(
                from_agent="ceo", to_agent="qa", message_type="task",
                payload={
                    "summary": "Re-review after revision",
                    "product_spec": product_spec,
                    "html_content": html_content,
                    "pr_url": pr_url,
                    "pr_number": pr_number,
                    "marketing_copy": marketing_copy,
                },
            ))
            for m in self._drain("qa"):
                self.qa_agent.handle_task(m)

        # STEP 8 — final Slack summary
        self._log("Posting final summary to Slack")
        self._post_final_slack(product_spec, marketing_copy, pr_url)

        # STEP 9 — attach decision log to message bus log
        self.message_bus.send(new_message(
            from_agent="ceo", to_agent="ceo", message_type="confirmation",
            payload={"summary": "Pipeline complete", "decisions": self.decisions_log,
                     "pr_url": pr_url},
        ))
