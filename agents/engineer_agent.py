"""Engineer Agent — builds HTML landing page and opens a real GitHub PR."""
import base64
import json
import os
import requests

from llm_client import call_llm
from message_bus import new_message


SYSTEM_PROMPT = (
    "You are the Engineer Agent on the OutreachPilot startup team. "
    "You produce production-quality HTML/CSS landing pages tailored to the exact "
    "product specification you are given — never generic marketing boilerplate."
)


def _html_prompt(product_spec: dict, feedback: str = None) -> str:
    base = f"""Generate a complete, production-quality HTML file for the OutreachPilot landing page.

Product specification:
{json.dumps(product_spec, indent=2)}

Requirements:
- Single self-contained HTML file with inline <style> CSS (mobile-responsive).
- Hero section whose headline matches the value_proposition above.
- Subheadline clarifying the value proposition.
- A features grid showing ALL 5 features from the spec (use emoji/icons).
- A prominent call-to-action button ("Get Early Access" or similar).
- Footer with a short tagline.
- Modern color scheme, clean typography, looks like a real SaaS landing page.
- Content must be SPECIFIC to OutreachPilot — freelancers in Pakistan targeting US clients.

Return ONLY the raw HTML document starting with <!DOCTYPE html>. No markdown fences, no commentary."""
    if feedback:
        base += f"\n\nIMPORTANT — this is a revision. Previous QA feedback:\n{feedback}\nAddress every point."
    return base


def _strip_fences(html: str) -> str:
    html = html.strip()
    if html.startswith("```"):
        lines = html.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        html = "\n".join(lines)
    return html.strip()


class EngineerAgent:
    def __init__(self, message_bus):
        self.message_bus = message_bus
        self.github_token = os.environ.get("GITHUB_TOKEN", "")
        self.repo = os.environ.get("GITHUB_REPO", "")
        self.headers = {
            "Authorization": f"token {self.github_token}",
            "Accept": "application/vnd.github+json",
        }
        self.branch = "agent-landing-page"
        self.current_spec = None
        self.current_pr_number = None
        self.current_pr_url = None
        self.current_issue_url = None

    # ---------- GitHub helpers ----------
    def _api(self, method, path, **kwargs):
        url = f"https://api.github.com{path}"
        r = requests.request(method, url, headers=self.headers, **kwargs)
        print(f"  [GitHub] {method} {path} -> {r.status_code}")
        return r

    def _ensure_branch(self):
        # Delete existing branch if present, then recreate from main.
        r = self._api("GET", f"/repos/{self.repo}/git/ref/heads/main")
        r.raise_for_status()
        main_sha = r.json()["object"]["sha"]

        r = self._api("GET", f"/repos/{self.repo}/git/ref/heads/{self.branch}")
        if r.status_code == 200:
            self._api("DELETE", f"/repos/{self.repo}/git/refs/heads/{self.branch}")

        r = self._api(
            "POST",
            f"/repos/{self.repo}/git/refs",
            json={"ref": f"refs/heads/{self.branch}", "sha": main_sha},
        )
        if r.status_code not in (200, 201):
            print(f"  [GitHub] branch creation response: {r.text[:300]}")
            r.raise_for_status()

    def _commit_html(self, html: str, message: str):
        content_b64 = base64.b64encode(html.encode("utf-8")).decode("ascii")
        body = {
            "message": message,
            "content": content_b64,
            "branch": self.branch,
            "committer": {"name": "EngineerAgent", "email": "agent@outreachpilot.ai"},
        }
        # Check if file exists on this branch to get sha (for updates).
        r = self._api(
            "GET",
            f"/repos/{self.repo}/contents/index.html",
            params={"ref": self.branch},
        )
        if r.status_code == 200:
            body["sha"] = r.json()["sha"]
        r = self._api("PUT", f"/repos/{self.repo}/contents/index.html", json=body)
        if r.status_code not in (200, 201):
            print(f"  [GitHub] commit response: {r.text[:300]}")
            r.raise_for_status()

    def _create_issue(self, spec: dict) -> str:
        desc = call_llm(
            SYSTEM_PROMPT,
            "Write a short GitHub issue body (3-5 sentences) announcing that the "
            "OutreachPilot landing page has been built, referencing the value "
            f"proposition: {spec['value_proposition']}. Plain text only.",
            max_tokens=400,
        )
        r = self._api(
            "POST",
            f"/repos/{self.repo}/issues",
            json={"title": "Initial landing page for OutreachPilot", "body": desc},
        )
        if r.status_code not in (200, 201):
            print(f"  [GitHub] issue response: {r.text[:300]}")
            return ""
        return r.json().get("html_url", "")

    def _open_pr(self, spec: dict) -> tuple:
        title_body = call_llm(
            SYSTEM_PROMPT,
            "Write a GitHub PR title (one line) and a short markdown body "
            "describing the OutreachPilot landing page work. Product value prop: "
            f"{spec['value_proposition']}. "
            "Return as JSON: {\"title\": \"...\", \"body\": \"...\"}. JSON only.",
            max_tokens=500,
        )
        from llm_client import parse_llm_json
        try:
            parsed = parse_llm_json(title_body)
            title = parsed.get("title", "Add OutreachPilot landing page")
            body = parsed.get("body", "Initial landing page built by EngineerAgent.")
        except Exception:
            title = "Add OutreachPilot landing page"
            body = "Initial landing page built by EngineerAgent."

        r = self._api(
            "POST",
            f"/repos/{self.repo}/pulls",
            json={"title": title, "body": body, "head": self.branch, "base": "main"},
        )
        if r.status_code not in (200, 201):
            print(f"  [GitHub] PR response: {r.text[:300]}")
            return "", None
        data = r.json()
        return data.get("html_url", ""), data.get("number")

    # ---------- Agent actions ----------
    def handle_task(self, msg):
        mtype = msg["message_type"]
        if mtype == "task":
            spec = msg["payload"]["product_spec"]
            self.current_spec = spec
            html = _strip_fences(call_llm(SYSTEM_PROMPT, _html_prompt(spec)))

            try:
                self.current_issue_url = self._create_issue(spec)
                self._ensure_branch()
                self._commit_html(html, "Add OutreachPilot landing page")
                pr_url, pr_number = self._open_pr(spec)
                self.current_pr_url = pr_url
                self.current_pr_number = pr_number
                status = "ok"
            except Exception as e:
                print(f"  [EngineerAgent] GitHub flow failed: {e}")
                status = f"error: {e}"

            self.message_bus.send(new_message(
                from_agent="engineer",
                to_agent="ceo",
                message_type="result",
                payload={
                    "summary": "Landing page built and PR opened",
                    "pr_url": self.current_pr_url,
                    "pr_number": self.current_pr_number,
                    "issue_url": self.current_issue_url,
                    "html_content": html,
                    "status": status,
                },
                parent_message_id=msg["message_id"],
            ))

        elif mtype == "revision_request":
            feedback = msg["payload"].get("feedback", "")
            html = _strip_fences(call_llm(
                SYSTEM_PROMPT, _html_prompt(self.current_spec, feedback=feedback)
            ))
            try:
                self._commit_html(html, f"Revise landing page: {feedback[:60]}")
                status = "ok"
            except Exception as e:
                print(f"  [EngineerAgent] revision commit failed: {e}")
                status = f"error: {e}"

            self.message_bus.send(new_message(
                from_agent="engineer",
                to_agent="ceo",
                message_type="result",
                payload={
                    "summary": "Revised landing page committed",
                    "pr_url": self.current_pr_url,
                    "pr_number": self.current_pr_number,
                    "issue_url": self.current_issue_url,
                    "html_content": html,
                    "status": status,
                    "revised": True,
                },
                parent_message_id=msg["message_id"],
            ))
