"""Deterministic entity extraction from seller messages and context."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.models.messages import ConversationMessage

EntityValue = str | list[str]

_PRODUCT_PATTERN = re.compile(
    r"(?:محصول|product|شناسه\s+محصول)\s*:?\s*(\d+)",
    re.IGNORECASE,
)
_IBAN_PATTERN = re.compile(r"IR(\d{24})", re.IGNORECASE)
_SHEBA_LABELED_PATTERN = re.compile(
    r"(?:شبا|شماره\s+شبا|iban)\s*:?\s*(?:IR)?(\d{24})",
    re.IGNORECASE,
)
_INC_ORDER_PATTERN = re.compile(r"(?<!\d)INC[\s-]*(\d{7})(?!\d)", re.IGNORECASE)
_STANDALONE_DIGITS = re.compile(r"(?<!\d)(\d+)(?!\d)")


@dataclass(frozen=True)
class ExtractedEntities:
    order_id: str | None = None
    order_ids: list[str] = field(default_factory=list)
    tracking_code: str | None = None
    product_id: str | None = None
    product_ids: list[str] = field(default_factory=list)
    iban: str | None = None
    card_number: str | None = None
    mobile_number: str | None = None

    def to_dict(self) -> dict[str, EntityValue]:
        entities: dict[str, EntityValue] = {}
        if self.order_id:
            entities["order_id"] = self.order_id
        if self.order_ids:
            entities["order_ids"] = self.order_ids
        if self.tracking_code:
            entities["tracking_code"] = self.tracking_code
        if self.product_id:
            entities["product_id"] = self.product_id
        if len(self.product_ids) > 1:
            entities["product_ids"] = self.product_ids
        if self.iban:
            entities["iban"] = self.iban
        if self.card_number:
            entities["card_number"] = self.card_number
        if self.mobile_number:
            entities["mobile_number"] = self.mobile_number
        return entities


@dataclass(frozen=True)
class _Claim:
    start: int
    end: int
    kind: str
    value: str


def _overlaps_claims(start: int, end: int, claims: list[_Claim]) -> bool:
    return any(not (end <= claim.start or start >= claim.end) for claim in claims)


def _has_sheba_label(text: str) -> bool:
    return "شبا" in text or "شماره شبا" in text


def _extract_product_ids(text: str) -> list[str]:
    return list(dict.fromkeys(match.group(1) for match in _PRODUCT_PATTERN.finditer(text)))


def _extract_claims(text: str) -> list[_Claim]:
    claims: list[_Claim] = []

    for match in _IBAN_PATTERN.finditer(text):
        claims.append(
            _Claim(
                match.start(),
                match.end(),
                "iban",
                f"IR{match.group(1)}",
            )
        )

    for match in _SHEBA_LABELED_PATTERN.finditer(text):
        if _overlaps_claims(match.start(), match.end(), claims):
            continue
        claims.append(
            _Claim(
                match.start(),
                match.end(),
                "iban",
                f"IR{match.group(1)}",
            )
        )

    for match in _INC_ORDER_PATTERN.finditer(text):
        if _overlaps_claims(match.start(), match.end(), claims):
            continue
        claims.append(
            _Claim(
                match.start(),
                match.end(),
                "order",
                f"INC-{match.group(1)}",
            )
        )

    sheba_labeled = _has_sheba_label(text)
    for match in _STANDALONE_DIGITS.finditer(text):
        start, end = match.span(1)
        if _overlaps_claims(start, end, claims):
            continue

        digits = match.group(1)
        length = len(digits)

        if length == 11 and digits.startswith("09"):
            claims.append(_Claim(start, end, "mobile", digits))
        elif length == 16:
            claims.append(_Claim(start, end, "card", digits))
        elif length == 24 and sheba_labeled:
            claims.append(_Claim(start, end, "iban", f"IR{digits}"))
        elif 20 <= length <= 26:
            claims.append(_Claim(start, end, "tracking", digits))
        elif length == 7:
            claims.append(_Claim(start, end, "order", f"INC-{digits}"))

    return claims


def _extract_from_text(text: str) -> ExtractedEntities:
    claims = _extract_claims(text)
    product_ids = _extract_product_ids(text)

    order_ids = list(dict.fromkeys(claim.value for claim in claims if claim.kind == "order"))
    iban = next((claim.value for claim in claims if claim.kind == "iban"), None)
    card_number = next((claim.value for claim in claims if claim.kind == "card"), None)
    mobile_number = next((claim.value for claim in claims if claim.kind == "mobile"), None)
    tracking_code = next((claim.value for claim in claims if claim.kind == "tracking"), None)

    return ExtractedEntities(
        order_id=order_ids[0] if order_ids else None,
        order_ids=order_ids,
        tracking_code=tracking_code,
        product_id=product_ids[0] if product_ids else None,
        product_ids=product_ids,
        iban=iban,
        card_number=card_number,
        mobile_number=mobile_number,
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
        mobile_number=primary.mobile_number or secondary.mobile_number,
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
            or not result.mobile_number
        ):
            result = _merge_entities(result, backfill)
    return result
