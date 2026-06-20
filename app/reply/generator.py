from app.models.intent import IntentClassificationResult
from app.models.messages import ConversationMessage
from app.models.reply import ReplyGenerationResult
from app.reply.templates import FORBIDDEN_ONBOARDING_PHRASES, render_template


def generate_reply(
    intent_result: IntentClassificationResult,
    conversation_context: list[ConversationMessage] | None = None,
) -> ReplyGenerationResult:
    del conversation_context

    text = render_template(intent_result)
    warnings: list[str] = []
    for phrase in FORBIDDEN_ONBOARDING_PHRASES:
        if phrase in text:
            warnings.append(f"forbidden_phrase:{phrase}")

    return ReplyGenerationResult(
        text=text,
        source="template",
        primary_intent=intent_result.primary_intent,
        suggested_action=intent_result.suggested_action,
        warnings=warnings,
    )
