from __future__ import annotations
from typing import Optional, List, Dict, Any


class CardBuilder:
    @staticmethod
    def _header(title: str, color: str = "blue") -> Dict[str, Any]:
        return {"title": {"tag": "plain_text", "content": title}, "template": color}

    @staticmethod
    def _text_block(content: str) -> Dict[str, Any]:
        return {"tag": "div", "text": {"tag": "lark_md", "content": content}}

    @staticmethod
    def _button(text: str, value: str, button_type: str = "default") -> Dict[str, Any]:
        return {"tag": "button", "text": {"tag": "plain_text", "content": text}, "type": button_type, "value": {"action": value}}

    @staticmethod
    def question_card(title: str, question: str, options: Optional[List[str]] = None, subtitle: Optional[str] = None) -> Dict[str, Any]:
        elements: List[Dict[str, Any]] = [CardBuilder._text_block(question)]
        if subtitle:
            elements.append(CardBuilder._text_block(subtitle))
        if options:
            buttons = [CardBuilder._button(opt, opt, "primary" if i == 0 else "default") for i, opt in enumerate(options)]
            elements.append({"tag": "action", "actions": buttons})
        return {"header": CardBuilder._header(title), "elements": elements}

    @staticmethod
    def confirm_card(title: str, summary: str, confirm_text: str = "Looks good", adjust_text: str = "Adjust") -> Dict[str, Any]:
        elements: List[Dict[str, Any]] = [CardBuilder._text_block(summary)]
        elements.append({"tag": "action", "actions": [CardBuilder._button(confirm_text, "confirm", "primary"), CardBuilder._button(adjust_text, "adjust", "default")]})
        return {"header": CardBuilder._header(title, "green"), "elements": elements}

    @staticmethod
    def plan_card(title: str, slots: List[Dict[str, str]], confirm_text: str = "Looks good", adjust_text: str = "Adjust") -> Dict[str, Any]:
        type_emoji = {"task": "📋", "habit": "🔄", "calendar_event": "📅", "break": "☕", "free": "⬜"}
        elements: List[Dict[str, Any]] = []
        for slot in slots:
            emoji = type_emoji.get(slot.get("type", ""), "▪️")
            elements.append(CardBuilder._text_block(f"**{slot['time']}**  {emoji} {slot['content']}"))
        elements.append({"tag": "hr"})
        elements.append({"tag": "action", "actions": [CardBuilder._button(confirm_text, "confirm_plan", "primary"), CardBuilder._button(adjust_text, "adjust_plan", "default")]})
        return {"header": CardBuilder._header(title, "blue"), "elements": elements}

    @staticmethod
    def reminder_card(task_title: str, message: str, actions: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
        elements: List[Dict[str, Any]] = [CardBuilder._text_block(f"**{task_title}**"), CardBuilder._text_block(message)]
        if actions is None:
            actions = [{"text": "Start", "value": "start_task"}, {"text": "Skip", "value": "skip_task"}]
        buttons = [CardBuilder._button(a["text"], a["value"]) for a in actions]
        if buttons:
            buttons[0]["type"] = "primary"
        elements.append({"tag": "action", "actions": buttons})
        return {"header": CardBuilder._header("⏰ Reminder", "orange"), "elements": elements}

    @staticmethod
    def summary_card(title: str, stats: Dict[str, Any], dashboard_url: Optional[str] = None) -> Dict[str, Any]:
        elements: List[Dict[str, Any]] = []
        lines = [f"**{k.replace('_', ' ').title()}:** {v}" for k, v in stats.items()]
        elements.append(CardBuilder._text_block("\n".join(lines)))
        if dashboard_url:
            elements.append({"tag": "hr"})
            elements.append(CardBuilder._text_block(f"[View full report]({dashboard_url})"))
        return {"header": CardBuilder._header(title, "purple"), "elements": elements}
