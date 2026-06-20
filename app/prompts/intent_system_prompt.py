"""System prompt for intent classification (used when LLM integration is added)."""

from app.intent.taxonomy import INTENT_TAXONOMY


def build_intent_system_prompt() -> str:
    lines = [
        "You classify merchant support messages into exactly one intent.",
        "Respond with JSON matching IntentClassificationResult schema.",
        "",
        "Intents:",
    ]
    for item in INTENT_TAXONOMY:
        lines.append(f"- {item.id.value}: {item.description}")
        for example in item.examples:
            lines.append(f"  Example: {example}")
    return "\n".join(lines)


INTENT_SYSTEM_PROMPT = build_intent_system_prompt()
