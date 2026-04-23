"""QA / Reviewer Agent — reviews HTML + marketing copy and posts GitHub review comments."""
import json
import os
import requests

from llm_client import call_llm, parse_llm_json
from message_bus import new_message


SYSTEM_PROMPT = (
    "You are the QA Agent on the OutreachPilot startup team. "
    "You are a strict but constructive reviewer of both product artifacts and marketing copy. "
    "You always return structured JSON verdicts."
)


def _review_prompt(product_spec, html, marketing_copy):
    return f"""Review the following artifacts produced for OutreachPilot.

Product spec:
{json.dumps(product_spec, indent=2)}

HTML landing page:
{html[:4000]}

Marketing copy:
{json.dumps(marketing_copy, indent=2)}

Evaluate:
HTML — does the headline match value_proposition? Are ALL 5 features present? Is there a CTA? Is the CSS professional? Is content specific to OutreachPilot?
Marketing — tagline under 10 words and compelling? Email has clear CTA? Tone right for Pakistan-based freelancers? Social posts platform-appropriate?

Return a JSON object EXACTLY:
{{
  "verdict": "pass" or "fail",
  "html_review": {{
    "headline_match": true/false,
    "features_present": true/false,
    "cta_present": true/false,
    "issues": ["..."]
  }},
  "marketing_review": {{
    "tagline_quality": "good"/"weak",
    "email_cta_present": true/false,
    "issues": ["..."]
  }},
  "target_agent_for_revision": "engineer" or "marketing" or null,
  "revision_feedback": "concrete instructions if fail, else empty"
}}

Respond ONLY with valid JSON."""


class QAAgent:
    def __init__(self, message_bus):
        self.message_bus = message_bus
        self.github_token = os.environ.get("GITHUB_TOKEN", "")
        self.repo = os.environ.get("GITHUB_REPO", "")
        self.headers = {
            "Authorization": f"token {self.github_token}",
            "Accept": "application/vnd.github+json",
        }

    def _post_pr_review(self, pr_number, review):
        if not pr_number:
            return False
        # Try a formal review with inline comments first.
        inline_comments = []
        html_issues = review.get("html_review", {}).get("issues", [])
        if html_issues:
            inline_comments.append({
                "path": "index.html",
                "position": 1,
                "body": f"QA: {html_issues[0]}",
            })
        if len(html_issues) > 1:
            inline_comments.append({
                "path": "index.html",
                "position": 5,
                "body": f"QA: {html_issues[1]}",
            })
        event = "REQUEST_CHANGES" if review.get("verdict") == "fail" else "COMMENT"
        body = {
            "body": f"QA Agent automated review — verdict: {review.get('verdict')}",
            "event": event,
        }
        if inline_comments:
            body["comments"] = inline_comments
        try:
            r = requests.post(
                f"https://api.github.com/repos/{self.repo}/pulls/{pr_number}/reviews",
                headers=self.headers,
                json=body,
            )
            print(f"  [GitHub] QA review POST -> {r.status_code}")
            if r.status_code in (200, 201):
                return True
            # Fallback to simple issue comment
            r2 = requests.post(
                f"https://api.github.com/repos/{self.repo}/issues/{pr_number}/comments",
                headers=self.headers,
                json={"body": f"QA Agent review (verdict: {review.get('verdict')}): "
                              + "; ".join(html_issues or ["no issues"])},
            )
            print(f"  [GitHub] QA fallback comment -> {r2.status_code}")
            return r2.status_code in (200, 201)
        except Exception as e:
            print(f"  [QA] GitHub review failed: {e}")
            return False

    def handle_task(self, msg):
        payload = msg["payload"]
        spec = payload["product_spec"]
        html = payload.get("html_content", "")
        marketing = payload.get("marketing_copy", {})
        pr_number = payload.get("pr_number")

        raw = call_llm(SYSTEM_PROMPT, _review_prompt(spec, html, marketing))
        try:
            review = parse_llm_json(raw)
        except Exception as e:
            print(f"  [QA] parse failed: {e}")
            review = {"verdict": "pass", "html_review": {}, "marketing_review": {},
                      "target_agent_for_revision": None, "revision_feedback": ""}

        posted = self._post_pr_review(pr_number, review)
        review["github_review_posted"] = posted
        review["summary"] = f"QA verdict: {review.get('verdict')}"

        self.message_bus.send(new_message(
            from_agent="qa",
            to_agent="ceo",
            message_type="result",
            payload=review,
            parent_message_id=msg["message_id"],
        ))
