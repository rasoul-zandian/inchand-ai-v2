"""Deterministic entity extraction from seller messages and context."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.models.messages import ConversationMessage

_INC_ORDER_PATTERN = re.compile(r"INC[\s-]*(\d+)", re.IGNORECASE)
_LABELED_ORDER_PATTERN = re.compile(
    r"(?:سفارش|شماره\s+سفارش)\s*:?\s*(\d{5,})",
    re.IGNORECASE,
)
_PRODUCT_PATTERN = re.compile(
    r"(?:محصول|product|شناسه\s+محصول)\s*:?\s*(\d+)",
    re.IGNORECASE,
)
_IBAN_PATTERN = re.compile(r"IR(\d{24})", re.IGNORECASE)
_SHEBA_LABELED_PATTERN = re.compile(
    r"(?:شبا|iban)\s*:?\s*(?:IR)?(\d{24})",
    re.IGNORECASE,
)
_DIGIT_RUNS = re.compile(r"\d+")


@dataclass(frozen=True)
class ExtractedEntities:
    order_id: str | None = None
    order_ids: list[str] = field(default_factory=list)
    tracking_code: str | None = None
    product_id: str | None = None
    product_ids: list[str] = field(default_factory=list)
    iban: str | None = None
    card_number: str | None = None

    def to_dict(self) -> dict[str, str]:
        entities: dict[str, str] = {}
        if self.order_id:
            entities["order_id"] = self.order_id
        if len(self.order_ids) > 1:
            entities["order_ids"] = ",".join(self.order_ids)
        if self.tracking_code:
            entities["tracking_code"] = self.tracking_code
        if self.product_id:
            entities["product_id"] = self.product_id
        if len(self.product_ids) > 1:
            entities["product_ids"] = ",".join(self.product_ids)
        if self.iban:
            entities["iban"] = self.iban
        if self.card_number:
            entities["card_number"] = self.card_number
        return entities


def _normalize_order_id(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    return f"INC-{digits}" if digits else raw


def _extract_order_ids(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for pattern in (_INC_ORDER_PATTERN, _LABELED_ORDER_PATTERN):
        for match in pattern.finditer(text):
            normalized = _normalize_order_id(match.group(1))
            if normalized not in seen:
                seen.add(normalized)
                found.append(normalized)
    return found


def _extract_product_ids(text: str) -> list[str]:
    return list(dict.fromkeys(match.group(1) for match in _PRODUCT_PATTERN.finditer(text)))


def _extract_iban(text: str) -> str | None:
    match = _IBAN_PATTERN.search(text)
    if match:
        return f"IR{match.group(1)}"
    match = _SHEBA_LABELED_PATTERN.search(text)
    if match:
        return f"IR{match.group(1)}"
    return None


def _iban_digit_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for match in _IBAN_PATTERN.finditer(text):
        spans.append(match.span())
    for match in _SHEBA_LABELED_PATTERN.finditer(text):
        spans.append(match.span())
    return spans


def _overlaps(span: tuple[int, int], spans: list[tuple[int, int]]) -> bool:
    start, end = span
    return any(not (end <= other_start or start >= other_end) for other_start, other_end in spans)


def _extract_card_and_tracking(text: str, iban: str | None) -> tuple[str | None, str | None]:
    iban_spans = _iban_digit_spans(text)
    card_number: str | None = None
    tracking_code: str | None = None
    order_digits = {re.sub(r"\D", "", order_id) for order_id in _extract_order_ids(text)}

    for match in _DIGIT_RUNS.finditer(text):
        digits = match.group(0)
        span = match.span()
        if _overlaps(span, iban_spans):
            continue
        if digits in order_digits:
            continue
        if iban and digits in iban:
            continue

        length = len(digits)
        if length == 16 and card_number is None:
            card_number = digits
            continue
        if 20 <= length <= 26 and tracking_code is None:
            tracking_code = digits

    return card_number, tracking_code


def _extract_from_text(text: str) -> ExtractedEntities:
    order_ids = _extract_order_ids(text)
    product_ids = _extract_product_ids(text)
    iban = _extract_iban(text)
    card_number, tracking_code = _extract_card_and_tracking(text, iban)

    return ExtractedEntities(
        order_id=order_ids[0] if order_ids else None,
        order_ids=order_ids,
        tracking_code=tracking_code,
        product_id=product_ids[0] if product_ids else None,
        product_ids=product_ids,
        iban=iban,
        card_number=card_number,
    )


def _merge_entities(
    primary: ExtractedEntities,
    secondary: ExtractedEntities,
) -> ExtractedEntities:
    order_ids = list(dict.fromkeys(primary.order_ids + secondary.order_ids))
    product_ids = list(dict.fromkeys(primary.product_ids + secondary.product_ids))
    return ExtractedEntities(
        order_id=primary.order_id or (order_ids[0] if order_ids else None),
        order_ids=order_ids,
        tracking_code=primary.tracking_code or secondary.tracking_code,
        product_id=primary.product_id or (product_ids[0] if product_ids else None),
        product_ids=product_ids,
        iban=primary.iban or secondary.iban,
        card_number=primary.card_number or secondary.card_number,
    )


def extract_entities(
    seller_message: str,
    conversation_context: list[ConversationMessage] | None = None,
) -> ExtractedEntities:
    result = _extract_from_text(seller_message)
    if not conversation_context:
        return result

    for message in conversation_context:
        backfill = _extract_from_text(message.content)
        if (
            not result.order_id
            or not result.tracking_code
            or not result.product_id
            or not result.iban
            or not result.card_number
        ):
            result = _merge_entities(result, backfill)
    return result
