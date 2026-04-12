"""Shared message bus for OutreachPilot multi-agent system."""
import json
import uuid
from datetime import datetime, timezone
from collections import defaultdict


def new_message(from_agent: str, to_agent: str, message_type: str,
                payload: dict, parent_message_id: str = None) -> dict:
    """Build a message dict conforming to the required schema."""
    return {
        "message_id": f"msg-{uuid.uuid4().hex[:8]}",
        "from_agent": from_agent,
        "to_agent": to_agent,
        "message_type": message_type,
        "payload": payload,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "parent_message_id": parent_message_id,
    }


class MessageBus:
    """Shared Python dict based message bus (Option A)."""

    def __init__(self):
        self._queues = defaultdict(list)
        self._log = []

    def send(self, message: dict):
        """Deliver a message to recipient queue and append to global log."""
        to_agent = message["to_agent"]
        self._queues[to_agent].append(message)
        self._log.append(message)
        self._print(message)

    def receive(self, agent_name: str) -> list:
        """Return and clear all pending messages for agent_name."""
        msgs = self._queues[agent_name]
        self._queues[agent_name] = []
        return msgs

    def get_full_log(self) -> list:
        return list(self._log)

    def save_log(self, filepath: str):
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self._log, f, indent=2, default=str)

    @staticmethod
    def _print(message: dict):
        ts = message["timestamp"]
        frm = message["from_agent"].upper()
        to = message["to_agent"].upper()
        mtype = message["message_type"]
        summary = MessageBus._summary(message["payload"])
        print(f"[{ts}] {frm} \u2192 {to} ({mtype}): {summary}")

    @staticmethod
    def _summary(payload: dict) -> str:
        if not isinstance(payload, dict):
            return str(payload)[:100]
        for key in ("summary", "task", "note", "verdict", "feedback", "tagline"):
            if key in payload and isinstance(payload[key], str):
                return payload[key][:120]
        keys = ", ".join(payload.keys())
        return f"<payload with keys: {keys}>"
