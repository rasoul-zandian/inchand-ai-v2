"""System prompt for intent classification."""

from app.intent.taxonomy import INTENT_TAXONOMY


def build_intent_system_prompt() -> str:
    intent_lines = []
    for item in INTENT_TAXONOMY:
        intent_lines.append(f"- {item.id.value}: {item.description}")
        if item.examples:
            intent_lines.append(f"  Example: {item.examples[0]}")

    return (
        "Classify the seller message into exactly one primary_intent from the taxonomy.\n"
        "Return JSON only with keys: primary_intent, confidence, evidence, entities, "
        "context_flags, negative_intents, suggested_action.\n"
        "Rules:\n"
        "- primary_intent must be one of the taxonomy ids.\n"
        "- evidence must be short quoted phrases from the seller message or context.\n"
        "- do not include chain-of-thought or reasoning text.\n"
        "- if settlement is mentioned while changing bank/card/IBAN, use bank_account_change "
        "(not settlement_inquiry), set context_flags to include settlement_context, and add "
        "settlement_inquiry to negative_intents.\n"
        "- if both card number and IBAN/account-bank change are present, use "
        "bank_account_change, add card_provided to context_flags when a card number is "
        "provided, and add settlement_inquiry to negative_intents when settlement wording "
        "is present.\n"
        "- if admin/support context mentions an order complaint and the seller reports "
        "contacting the buyer, return, refund, replacement, or resolution, use "
        "complaint_order_followup (not return_refund_inquiry or bank_account_change).\n"
        "- phrases like 'به حسابشون برگشت داده بشه' in complaint followups refer to buyer "
        "refund, not seller bank account update.\n"
        "- suggested_action must be one of: reply_to_seller, request_missing_information, "
        "human_followup, escalate, close_request.\n"
        "- unknown values in negative_intents should be omitted.\n\n"
        "Taxonomy:\n"
        + "\n".join(intent_lines)
    )


INTENT_SYSTEM_PROMPT = build_intent_system_prompt()
