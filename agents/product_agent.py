"""Product Agent — generates the product specification."""
from llm_client import call_llm, parse_llm_json
from message_bus import new_message


SYSTEM_PROMPT = (
    "You are the Product Agent on a startup team building OutreachPilot, an AI-powered "
    "outreach automation tool for Pakistan-based freelancers targeting US clients. "
    "You produce concrete, specific product specifications — never generic."
)


def _build_user_prompt(startup_idea, service_focus, target_audience, feedback=None):
    base = f"""Startup idea:
{startup_idea}

Service focus: {service_focus}
Target audience: {target_audience}

Generate a product specification as a JSON object with EXACTLY these fields:
{{
  "value_proposition": "one sentence",
  "personas": [
    {{"name": "...", "role": "...", "pain_point": "specific measurable pain"}}
  ],
  "features": [
    {{"name": "...", "description": "...", "priority": 1}}
  ],
  "user_stories": ["As a ... I want ... so that ..."]
}}

Requirements:
- 2-3 personas with realistic names, specific roles, and concrete measurable pain points tied to the service/audience above.
- Exactly 5 features ranked priority 1 (highest) to 5.
- 3 user stories in "As a / I want / so that" form.
- All content must be specific to OutreachPilot, the service, and the target audience — no generic SaaS fluff.

Respond ONLY with a valid JSON object. No text before or after."""
    if feedback:
        base += f"\n\nIMPORTANT — a previous version of this spec was rejected. CEO feedback:\n{feedback}\n\nAddress every point of the feedback in the new version."
    return base


class ProductAgent:
    def __init__(self, message_bus):
        self.message_bus = message_bus
        self.last_task_payload = None

    def _generate(self, task_payload, feedback=None):
        prompt = _build_user_prompt(
            task_payload["startup_idea"],
            task_payload["service_focus"],
            task_payload["target_audience"],
            feedback=feedback,
        )
        raw = call_llm(SYSTEM_PROMPT, prompt)
        return parse_llm_json(raw)

    def handle_task(self, msg):
        """Handle an incoming task message from the CEO."""
        mtype = msg["message_type"]
        if mtype == "task":
            self.last_task_payload = msg["payload"]
            spec = self._generate(msg["payload"])
            self.message_bus.send(new_message(
                from_agent="product",
                to_agent="ceo",
                message_type="result",
                payload={"summary": "Initial product spec", "product_spec": spec},
                parent_message_id=msg["message_id"],
            ))
        elif mtype == "revision_request":
            feedback = msg["payload"].get("feedback", "")
            spec = self._generate(self.last_task_payload, feedback=feedback)
            self.message_bus.send(new_message(
                from_agent="product",
                to_agent="ceo",
                message_type="result",
                payload={"summary": "Revised product spec", "product_spec": spec, "revised": True},
                parent_message_id=msg["message_id"],
            ))
