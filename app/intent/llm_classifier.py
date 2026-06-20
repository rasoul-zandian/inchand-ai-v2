"""OpenAI-backed intent classification adapter."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable

from app.config import settings
from app.intent.taxonomy import IntentId
from app.models.intent import IntentClassificationResult, SuggestedAction
from app.models.messages import ConversationMessage
from app.prompts.intent_system_prompt import INTENT_SYSTEM_PROMPT

RequestFn = Callable[[str, str, float, list[dict[str, str]]], str]

_VALID_INTENTS = {intent.value for intent in IntentId}
_VALID_ACTIONS = {action.value for action in SuggestedAction}


def _build_user_prompt(
    message: str,
    conversation_context: list[ConversationMessage] | None,
) -> str:
    parts = ["Seller message:", message]
    if conversation_context:
        parts.append("Conversation context:")
        for item in conversation_context:
            parts.append(f"- {item.role}: {item.content}")
    return "\n".join(parts)


def _default_request_openai(
    api_key: str,
    model: str,
    temperature: float,
    messages: list[dict[str, str]],
) -> str:
    payload = json.dumps(
        {
            "model": model,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "messages": messages,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.loads(response.read().decode("utf-8"))
    return body["choices"][0]["message"]["content"]


def _parse_llm_payload(raw: object) -> IntentClassificationResult:
    if not isinstance(raw, dict):
        raise ValueError("invalid_json")

    primary_intent = raw.get("primary_intent")
    if primary_intent not in _VALID_INTENTS:
        raise ValueError("unknown_intent")

    suggested_action = raw.get("suggested_action")
    if suggested_action not in _VALID_ACTIONS:
        raise ValueError("invalid_suggested_action")

    negative_raw = raw.get("negative_intents", [])
    if not isinstance(negative_raw, list):
        raise ValueError("invalid_negative_intents")

    negative_intents: list[IntentId] = []
    for item in negative_raw:
        if isinstance(item, str) and item in _VALID_INTENTS:
            negative_intents.append(IntentId(item))

    evidence = raw.get("evidence", [])
    if not isinstance(evidence, list) or not all(isinstance(x, str) for x in evidence):
        raise ValueError("invalid_evidence")

    entities = raw.get("entities", {})
    if not isinstance(entities, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in entities.items()
    ):
        raise ValueError("invalid_entities")

    context_flags = raw.get("context_flags", [])
    if not isinstance(context_flags, list) or not all(isinstance(x, str) for x in context_flags):
        raise ValueError("invalid_context_flags")

    confidence = raw.get("confidence")
    if not isinstance(confidence, (int, float)):
        raise ValueError("missing_required_fields")

    return IntentClassificationResult(
        primary_intent=IntentId(primary_intent),
        confidence=float(confidence),
        evidence=evidence,
        entities=entities,
        context_flags=context_flags,
        negative_intents=negative_intents,
        suggested_action=SuggestedAction(suggested_action),
    )


def try_classify_intent_with_openai(
    message: str,
    conversation_context: list[ConversationMessage] | None = None,
    *,
    request_fn: RequestFn | None = None,
) -> tuple[IntentClassificationResult | None, str | None]:
    if not settings.openai_api_key:
        return None, "missing_api_key"

    caller = request_fn or _default_request_openai
    messages = [
        {"role": "system", "content": INTENT_SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_prompt(message, conversation_context)},
    ]

    try:
        content = caller(
            settings.openai_api_key,
            settings.intent_classifier_model,
            settings.intent_classifier_temperature,
            messages,
        )
    except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError):
        return None, "api_error"

    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None, "invalid_json"

    try:
        return _parse_llm_payload(payload), None
    except ValueError as exc:
        return None, str(exc)
