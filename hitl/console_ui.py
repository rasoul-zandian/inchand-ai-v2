"""HTML/CSS rendering for the approved HITL review console."""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any

from app.config import settings

_CONSOLE_CSS = """
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@2.47.0/tabler-icons.min.css">
<style>
:root{
  --color-background-primary:#ffffff;
  --color-background-secondary:#f8fafc;
  --color-background-tertiary:#f1f5f9;
  --color-text-primary:#0f172a;
  --color-text-secondary:#64748b;
  --color-border-tertiary:#e2e8f0;
  --color-border-secondary:#cbd5e1;
  --border-radius-md:8px;
  --border-radius-lg:12px;
}
.hitl-wrap *{box-sizing:border-box;}
.hitl-wrap .hn{display:flex;align-items:center;justify-content:space-between;padding:9px 14px;border-right:3px solid transparent;transition:background .12s;color:#94a3b8;font-size:12px;}
.hitl-wrap .hn.a{background:#1e3a5f;border-right-color:#3b82f6;color:#60a5fa;}
.hitl-wrap .tb{padding:10px 14px;border:none;background:none;font-size:12px;color:var(--color-text-secondary);border-bottom:2px solid transparent;margin-bottom:-0.5px;display:inline-flex;align-items:center;gap:5px;white-space:nowrap;}
.hitl-wrap .tb.a{color:#185FA5;border-bottom-color:#185FA5;font-weight:500;}
.hitl-wrap .ab{padding:8px 10px;border-radius:var(--border-radius-md);border:0.5px solid var(--color-border-secondary);font-size:12px;font-weight:500;display:flex;align-items:center;justify-content:center;gap:5px;width:100%;background:var(--color-background-primary);color:var(--color-text-primary);}
.hitl-wrap .ab.pr{background:#185FA5;color:#fff;border-color:#185FA5;}
.hitl-wrap .ab.dn{background:#FCEBEB;color:#791F1F;border-color:#F09595;}
.hitl-wrap .chip{display:inline-block;padding:2px 7px;border-radius:var(--border-radius-md);font-size:11px;font-weight:500;}
.hitl-wrap .chip.p{background:#FAEEDA;color:#633806;border:0.5px solid #EF9F27;}
.hitl-wrap .chip.s{background:#EAF3DE;color:#27500A;border:0.5px solid #639922;}
.hitl-wrap .chip.rj{background:#FCEBEB;color:#791F1F;border:0.5px solid #F09595;}
.hitl-wrap .chip.b{background:#E6F1FB;color:#0C447C;border:0.5px solid #85B7EB;}
.hitl-wrap .bseller{background:#185FA5;color:#fff;padding:9px 13px;border-radius:12px 12px 3px 12px;font-size:13px;line-height:1.65;direction:rtl;max-width:74%;word-break:break-word;}
.hitl-wrap .badmin{background:var(--color-background-secondary);color:var(--color-text-primary);padding:9px 13px;border-radius:12px 12px 12px 3px;font-size:13px;line-height:1.65;direction:rtl;border:0.5px solid var(--color-border-tertiary);max-width:74%;word-break:break-word;}
.hitl-wrap .bai{background:#EAF3DE;color:#173404;padding:9px 13px;border-radius:12px 12px 12px 3px;font-size:13px;line-height:1.65;direction:rtl;border:0.5px solid #97C459;max-width:74%;word-break:break-word;}
.hitl-wrap .btarget{border:2px solid #EF9F27!important;background:#FAEEDA!important;color:#412402!important;}
.hitl-wrap .av{width:28px;height:28px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:12px;flex-shrink:0;}
.hitl-wrap .avseller{background:#E6F1FB;color:#185FA5;}
.hitl-wrap .avadmin{background:var(--color-background-secondary);color:var(--color-text-secondary);}
.hitl-wrap .avai{background:#EAF3DE;color:#27500A;}
.hitl-wrap .drow{display:flex;justify-content:space-between;align-items:center;padding:5px 0;border-bottom:0.5px solid var(--color-border-tertiary);font-size:12px;}
.hitl-wrap .drow:last-child{border:none;}
.hitl-wrap .st{font-size:10px;font-weight:500;color:var(--color-text-secondary);text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px;}
.hitl-wrap .cbar{height:4px;background:var(--color-border-tertiary);border-radius:2px;margin-top:4px;overflow:hidden;}
.hitl-wrap .cfill{height:100%;background:#639922;border-radius:2px;}
.hitl-wrap .csm{background:var(--color-background-secondary);border:0.5px solid var(--color-border-tertiary);border-radius:var(--border-radius-md);padding:8px 12px;}
</style>
"""

_ROLE_LABELS = {"shop": "فروشنده", "admin": "پشتیبانی سایت", "ai": "پاسخ AI"}
_ROLE_ICONS = {"shop": "ti-user", "admin": "ti-headset", "ai": "ti-robot"}
_ROLE_AVATAR = {"shop": "avseller", "admin": "avadmin", "ai": "avai"}


def _e(value: Any, default: str = "—") -> str:
    if value is None or value == "":
        return default
    return html.escape(str(value))


def _kind_to_role(kind: str) -> str:
    if kind == "seller":
        return "shop"
    if kind == "ai":
        return "ai"
    return "admin"


def _status_chip_class(status: str) -> str:
    if status in {"sent", "sent_both", "suggested"}:
        return "chip s"
    if status in {"rejected_local", "send_failed", "error"}:
        return "chip rj"
    if status == "pending_review":
        return "chip p"
    return "chip b"


def _nav_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "all": len(records),
        "pending_review": 0,
        "approved": 0,
        "needs_edit": 0,
        "sent": 0,
    }
    for record in records:
        status = str(record.get("status", ""))
        if status == "pending_review":
            counts["pending_review"] += 1
        elif status in {"sent", "sent_both", "suggested"}:
            counts["sent"] += 1
            counts["approved"] += 1
        elif status in {"send_failed", "error", "rejected_local"}:
            counts["needs_edit"] += 1
    return counts


def _confidence_percent(confidence: Any) -> int:
    try:
        value = float(confidence)
    except (TypeError, ValueError):
        return 0
    if value <= 1:
        value *= 100
    return max(0, min(100, int(round(value))))


def _order_rows(record: dict[str, Any]) -> list[dict[str, str]]:
    pipeline = record.get("pipeline", {})
    if "order_lookup" not in pipeline.get("selected_tools", []):
        return []
    rows: list[dict[str, str]] = []
    for item in record.get("tool_output", []):
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "order_id": str(item.get("order_id", "—")),
                "order_status": str(item.get("order_status", item.get("status", "—"))),
                "tracking_code": str(item.get("tracking_code", item.get("primary_parcel_tracking_code", "—"))),
                "payment_status": str(item.get("payment_status", "—")),
                "parcel_status": str(item.get("parcel_status", item.get("primary_parcel_status_name", "—"))),
            }
        )
    return rows


def render_chat_html(timeline: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for message in timeline:
        if message.get("kind") == "ai":
            continue
        role = _kind_to_role(str(message.get("kind", "admin")))
        content = _e(message.get("content", ""))
        is_target = bool(message.get("is_target"))
        timestamp = _e(message.get("timestamp", ""), "")
        is_seller = role == "shop"
        bubble = "bseller" if is_seller else ("bai" if role == "ai" else "badmin")
        target_class = " btarget" if is_target and is_seller else ""
        target_label = (
            '<div style="font-size:10px;background:#FAEEDA;color:#633806;border:0.5px solid #EF9F27;'
            'padding:2px 7px;border-radius:8px;display:inline-block;margin-bottom:4px;font-weight:500;">'
            "● پیام فعلی</div>"
            if is_target
            else ""
        )
        if is_seller:
            parts.append(
                f'<div id="target-message-{_e(message.get("message_id", ""), "")}" '
                'style="display:flex;flex-direction:row-reverse;align-items:flex-end;gap:7px;margin-bottom:12px;">'
                f'<div class="av {_ROLE_AVATAR[role]}"><i class="ti {_ROLE_ICONS[role]}" style="font-size:12px;" aria-hidden="true"></i></div>'
                '<div style="display:flex;flex-direction:column;align-items:flex-end;gap:2px;">'
                f'<span style="font-size:10px;color:var(--color-text-secondary);">{_ROLE_LABELS[role]}</span>'
                f"{target_label}"
                f'<div class="{bubble}{target_class}">{content}</div>'
                f'<span style="font-size:10px;color:var(--color-text-secondary);">{timestamp}</span>'
                "</div></div>"
            )
        else:
            parts.append(
                '<div style="display:flex;align-items:flex-end;gap:7px;margin-bottom:12px;">'
                f'<div class="av {_ROLE_AVATAR[role]}"><i class="ti {_ROLE_ICONS[role]}" style="font-size:12px;" aria-hidden="true"></i></div>'
                '<div style="display:flex;flex-direction:column;align-items:flex-start;gap:2px;">'
                f'<span style="font-size:10px;color:var(--color-text-secondary);">{_ROLE_LABELS[role]}</span>'
                f'<div class="{bubble}">{content}</div>'
                f'<span style="font-size:10px;color:var(--color-text-secondary);">{timestamp}</span>'
                "</div></div>"
            )
    return "".join(parts)


def render_console_html(
    record: dict[str, Any],
    *,
    records: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
    active_tab: str,
    active_nav: str,
    last_update: str,
    auto_refresh_on: bool,
) -> str:
    pipeline = record.get("pipeline", {})
    status = str(record.get("status", ""))
    counts = _nav_counts(records)
    order_rows = _order_rows(record)
    confidence = _confidence_percent(pipeline.get("confidence"))
    entities = pipeline.get("entities", {}) or {}
    evidence = pipeline.get("evidence", []) or []
    warnings = list(record.get("warnings", [])) + list(pipeline.get("warnings", []))
    should_send = pipeline.get("should_send")
    should_send_html = (
        '<span class="chip s">✓ بله</span>'
        if should_send is True
        else '<span class="chip rj">خیر</span>'
    )
    fallback_reason = pipeline.get("fallback_reason")
    classifier_provider = pipeline.get("classifier_provider", settings.intent_classifier_provider)
    processed_at = record.get("processed_at_jalali") or record.get("created_at_jalali", "—")
    date_label = _e(record.get("created_at_jalali", "—"))

    nav_defs = [
        ("all", "همه موارد", "ti-layout-list", counts["all"], True),
        ("pending_review", "در انتظار بررسی", "ti-clock", counts["pending_review"], counts["pending_review"] > 0),
        ("approved", "تأیید شده", "ti-circle-check", counts["approved"], False),
        ("needs_edit", "نیاز به ویرایش", "ti-pencil", counts["needs_edit"], False),
        ("sent", "ارسال شده", "ti-send", counts["sent"], False),
    ]
    nav_html = []
    for key, label, icon, count, highlight in nav_defs:
        active = " a" if key == active_nav else ""
        badge = (
            f'<span style="background:#185FA5;color:#E6F1FB;font-size:10px;padding:1px 6px;border-radius:8px;">{count}</span>'
            if highlight and count
            else f'<span style="color:#475569;font-size:10px;padding:1px 6px;">{count}</span>'
        )
        nav_html.append(
            f'<div class="hn{active}"><span style="display:flex;align-items:center;gap:8px;">'
            f'<i class="ti {icon}" style="font-size:13px;" aria-hidden="true"></i>{label}</span>{badge}</div>'
        )

    tabs = [
        ("conversation", "مکالمه", "ti-messages", ""),
        ("ai-reply", "پاسخ AI", "ti-robot", ""),
        (
            "order",
            "جستجوی سفارش",
            "ti-package",
            (
                f'<span style="background:#185FA5;color:#E6F1FB;font-size:9px;padding:1px 4px;border-radius:8px;margin-right:2px;">{len(order_rows)}</span>'
                if order_rows
                else ""
            ),
        ),
        ("metadata", "متادیتا", "ti-code", ""),
    ]
    tab_html = []
    for tab_id, label, icon, extra in tabs:
        active = " a" if tab_id == active_tab else ""
        tab_html.append(
            f'<span class="tb{active}"><i class="ti {icon}" style="font-size:12px;" aria-hidden="true"></i>{label}{extra}</span>'
        )

    entity_rows = ""
    for key, value in entities.items():
        if value in (None, "", []):
            continue
        entity_rows += (
            f'<div class="drow"><span style="color:var(--color-text-secondary);">{_e(key)}</span>'
            f'<span style="font-weight:500;font-family:monospace;font-size:12px;background:var(--color-background-secondary);padding:1px 6px;border-radius:4px;">{_e(value)}</span></div>'
        )
    if not entity_rows:
        entity_rows = '<div style="font-size:12px;color:var(--color-text-secondary);">—</div>'

    evidence_html = ""
    for item in evidence:
        evidence_html += (
            '<span style="background:var(--color-background-secondary);border:0.5px solid var(--color-border-tertiary);'
            f'padding:2px 8px;border-radius:var(--border-radius-md);font-size:11px;color:var(--color-text-secondary);">{_e(item)}</span>'
        )
    if not evidence_html:
        evidence_html = '<span style="font-size:12px;color:var(--color-text-secondary);">—</span>'

    if warnings:
        warnings_html = "".join(
            f'<div style="font-size:12px;color:#791F1F;margin-bottom:4px;">{_e(item)}</div>'
            for item in warnings
        )
    else:
        warnings_html = (
            '<div style="font-size:12px;color:var(--color-text-secondary);display:flex;align-items:center;gap:5px;">'
            '<i class="ti ti-circle-check" style="font-size:13px;color:#639922;" aria-hidden="true"></i>بدون هشدار</div>'
        )

    if order_rows:
        order_blocks = []
        for row in order_rows:
            order_blocks.append(
                '<div style="background:var(--color-background-secondary);border:0.5px solid var(--color-border-tertiary);border-radius:var(--border-radius-md);padding:10px 12px;margin-bottom:10px;">'
                f'<div class="drow"><span style="color:var(--color-text-secondary);">شناسه سفارش</span><span style="font-weight:500;font-family:monospace;font-size:12px;background:var(--color-background-primary);padding:1px 6px;border-radius:4px;">{_e(row["order_id"])}</span></div>'
                f'<div class="drow"><span style="color:var(--color-text-secondary);">وضعیت</span><span class="chip p">{_e(row["order_status"])}</span></div>'
                f'<div class="drow"><span style="color:var(--color-text-secondary);">کد رهگیری</span><span style="font-weight:500;font-family:monospace;font-size:12px;">{_e(row["tracking_code"])}</span></div>'
                f'<div class="drow"><span style="color:var(--color-text-secondary);">وضعیت مرسوله</span><span style="font-weight:500;">{_e(row["parcel_status"])}</span></div>'
                f'<div class="drow"><span style="color:var(--color-text-secondary);">وضعیت پرداخت</span><span style="font-weight:500;">{_e(row["payment_status"])}</span></div>'
                "</div>"
            )
        order_tab_body = (
            '<div style="background:var(--color-background-primary);border:0.5px solid var(--color-border-tertiary);border-radius:var(--border-radius-lg);padding:14px 16px;">'
            '<div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;">'
            '<span style="width:7px;height:7px;border-radius:50%;background:#22c55e;display:inline-block;"></span>'
            '<span style="font-weight:500;color:var(--color-text-primary);">order_lookup</span>'
            '<span class="chip s" style="font-size:10px;">موفق</span></div>'
            f'{"".join(order_blocks)}</div>'
        )
    else:
        order_tab_body = (
            '<div style="background:var(--color-background-primary);border:0.5px solid var(--color-border-tertiary);'
            'border-radius:var(--border-radius-lg);padding:14px 16px;font-size:13px;color:var(--color-text-secondary);">'
            "اطلاعات سفارش موجود نیست</div>"
        )

    history_html = (
        f'<div style="display:flex;align-items:center;gap:6px;font-size:11px;color:var(--color-text-secondary);">'
        f'<span style="width:6px;height:6px;border-radius:50%;background:#378ADD;flex-shrink:0;display:inline-block;"></span>'
        f"<span>{_e(status)} — {_e(record.get('created_at_jalali', '—'))}</span></div>"
    )
    for entry in record.get("send_log", []):
        if not isinstance(entry, dict):
            continue
        label = "ارسال" if entry.get("success") else "خطا"
        history_html += (
            '<div style="display:flex;align-items:center;gap:6px;font-size:11px;color:var(--color-text-secondary);margin-top:6px;">'
            f'<span style="width:6px;height:6px;border-radius:50%;background:#22c55e;flex-shrink:0;display:inline-block;"></span>'
            f"<span>{label} — {_e(entry.get('message_type', ''))}</span></div>"
        )

    def tab_style(tab_id: str) -> str:
        return "flex" if active_tab == tab_id else "none"

    return (
        _CONSOLE_CSS
        + '<div class="hitl-wrap" style="height:720px;display:flex;border:0.5px solid var(--color-border-tertiary);'
        'border-radius:var(--border-radius-lg);overflow:hidden;font-family:\'Tahoma\',\'Segoe UI\',Arial,sans-serif;font-size:13px;">'
        '<div style="width:196px;background:#1e293b;color:#94a3b8;display:flex;flex-direction:column;flex-shrink:0;">'
        '<div style="padding:14px;border-bottom:0.5px solid #334155;display:flex;align-items:center;gap:7px;">'
        '<i class="ti ti-robot" style="font-size:17px;color:#60a5fa;" aria-hidden="true"></i>'
        '<span style="font-size:13px;font-weight:500;color:#f1f5f9;">HITL Console</span>'
        '<span style="background:#22c55e;color:#052e16;font-size:9px;padding:2px 5px;border-radius:3px;font-weight:700;margin-right:auto;">LIVE</span>'
        "</div>"
        f'<nav style="padding:6px 0;flex:1;">{"".join(nav_html)}</nav>'
        '<div style="padding:10px 14px;border-top:0.5px solid #334155;font-size:10px;color:#64748b;">'
        f'<div style="display:flex;align-items:center;gap:5px;margin-bottom:3px;"><span style="width:5px;height:5px;border-radius:50%;background:#22c55e;display:inline-block;"></span>Last update: {_e(last_update)}</div>'
        f"<div>Auto refresh: {'ON (10s)' if auto_refresh_on else 'OFF'}</div></div></div>"
        '<div style="flex:1;display:flex;flex-direction:column;overflow:hidden;background:var(--color-background-tertiary);">'
        '<div style="background:var(--color-background-primary);border-bottom:0.5px solid var(--color-border-tertiary);padding:12px 18px;flex-shrink:0;">'
        '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:11px;">'
        '<span style="font-size:16px;font-weight:500;color:var(--color-text-primary);">Live HITL Review Console</span>'
        '<div style="display:flex;align-items:center;gap:8px;font-size:11px;color:var(--color-text-secondary);">'
        '<span style="width:6px;height:6px;border-radius:50%;background:#22c55e;display:inline-block;"></span>Auto refresh</div></div>'
        '<div style="display:flex;gap:8px;flex-wrap:wrap;">'
        f'<div class="csm"><div style="font-size:10px;color:var(--color-text-secondary);margin-bottom:3px;">Room ID</div><div style="font-size:15px;font-weight:500;color:var(--color-text-primary);">{_e(record.get("room_id"))}</div></div>'
        f'<div class="csm"><div style="font-size:10px;color:var(--color-text-secondary);margin-bottom:3px;">Shop ID</div><div style="font-size:15px;font-weight:500;color:var(--color-text-primary);">{_e(record.get("shop_id"))}</div></div>'
        f'<div class="csm"><div style="font-size:10px;color:var(--color-text-secondary);margin-bottom:3px;">Message ID</div><div style="font-size:15px;font-weight:500;color:var(--color-text-primary);">{_e(record.get("target_message_id"))}</div></div>'
        f'<div class="csm"><div style="font-size:10px;color:var(--color-text-secondary);margin-bottom:5px;">Status</div><span class="{_status_chip_class(status)}">{_e(status)}</span></div>'
        f'<div class="csm"><div style="font-size:10px;color:var(--color-text-secondary);margin-bottom:3px;">Created At</div><div style="font-size:12px;font-weight:500;color:var(--color-text-primary);direction:rtl;">{_e(record.get("created_at_jalali"))}</div></div>'
        f'<div class="csm"><div style="font-size:10px;color:var(--color-text-secondary);margin-bottom:3px;">Room Type</div><span class="chip b">{_e(record.get("room_type"))}</span></div>'
        "</div></div>"
        '<div style="background:var(--color-background-primary);border-bottom:0.5px solid var(--color-border-tertiary);padding:10px 18px;flex-shrink:0;display:flex;gap:10px;align-items:stretch;">'
        '<div style="flex:1;background:var(--color-background-secondary);border:0.5px solid var(--color-border-tertiary);border-radius:var(--border-radius-md);padding:10px 12px;">'
        '<div style="font-size:10px;color:var(--color-text-secondary);margin-bottom:5px;">پیام فروشنده</div>'
        f'<div style="font-size:13px;direction:rtl;color:var(--color-text-primary);line-height:1.6;">{_e(record.get("seller_message", ""))}</div></div>'
        '<div style="flex:1.5;background:#EAF3DE;border:0.5px solid #97C459;border-radius:var(--border-radius-md);padding:10px 12px;">'
        '<div style="font-size:10px;color:#3B6D11;margin-bottom:5px;">پاسخ پیشنهادی AI</div>'
        f'<div style="font-size:13px;direction:rtl;color:#173404;line-height:1.6;">{_e(pipeline.get("final_reply", ""))}</div></div>'
        '<div style="display:flex;flex-direction:column;gap:6px;justify-content:center;min-width:128px;">'
        '<div class="ab pr">ارسال پاسخ</div><div class="ab">پیشنهاد ویرایش</div></div></div>'
        '<div style="flex:1;display:flex;overflow:hidden;">'
        '<div style="flex:1;display:flex;flex-direction:column;overflow:hidden;">'
        '<div style="background:var(--color-background-primary);border-bottom:0.5px solid var(--color-border-tertiary);display:flex;padding:0 16px;flex-shrink:0;overflow-x:auto;">'
        f'{"".join(tab_html)}</div>'
        f'<div id="tab-conversation" style="flex:1;overflow-y:auto;padding:16px;display:{tab_style("conversation")};flex-direction:column;gap:0;" dir="rtl">'
        f'<div style="text-align:center;margin-bottom:12px;"><span style="font-size:11px;color:var(--color-text-secondary);background:var(--color-background-secondary);border:0.5px solid var(--color-border-tertiary);padding:2px 10px;border-radius:10px;">{date_label}</span></div>'
        f'<div id="chat-area">{render_chat_html(timeline)}</div>'
        '<div style="text-align:center;margin-top:12px;"><span style="font-size:10px;color:var(--color-text-secondary);background:var(--color-background-secondary);padding:2px 10px;border-radius:8px;">Start of conversation</span></div></div>'
        f'<div id="tab-ai-reply" style="flex:1;overflow-y:auto;padding:16px;display:{tab_style("ai-reply")};flex-direction:column;gap:12px;" dir="rtl">'
        '<div style="background:#EAF3DE;border:0.5px solid #97C459;border-radius:var(--border-radius-lg);padding:14px 16px;">'
        '<div style="font-size:10px;color:#3B6D11;font-weight:500;margin-bottom:8px;">پاسخ نهایی</div>'
        f'<div style="font-size:14px;color:#173404;line-height:1.7;">{_e(pipeline.get("final_reply", ""))}</div>'
        f'<div style="font-size:10px;color:#3B6D11;margin-top:8px;">منبع: {_e(pipeline.get("final_reply_source", "—"))}</div></div>'
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">'
        f'<div style="background:var(--color-background-primary);border:0.5px solid var(--color-border-tertiary);border-radius:var(--border-radius-md);padding:10px 12px;"><div style="font-size:10px;color:var(--color-text-secondary);margin-bottom:4px;">Intent</div><div style="font-size:12px;font-weight:500;color:var(--color-text-primary);">{_e(pipeline.get("primary_intent"))}</div></div>'
        f'<div style="background:var(--color-background-primary);border:0.5px solid var(--color-border-tertiary);border-radius:var(--border-radius-md);padding:10px 12px;"><div style="font-size:10px;color:var(--color-text-secondary);margin-bottom:4px;">Confidence</div><div style="font-size:13px;font-weight:500;color:var(--color-text-primary);">{_e(pipeline.get("confidence"))}</div><div class="cbar"><div class="cfill" style="width:{confidence}%;"></div></div></div>'
        f'<div style="background:var(--color-background-primary);border:0.5px solid var(--color-border-tertiary);border-radius:var(--border-radius-md);padding:10px 12px;"><div style="font-size:10px;color:var(--color-text-secondary);margin-bottom:5px;">Suggested Action</div><span class="chip s">{_e(pipeline.get("suggested_action"))}</span></div>'
        f'<div style="background:var(--color-background-primary);border:0.5px solid var(--color-border-tertiary);border-radius:var(--border-radius-md);padding:10px 12px;"><div style="font-size:10px;color:var(--color-text-secondary);margin-bottom:5px;">Should Send</div>{should_send_html}</div></div>'
        f'<div style="background:var(--color-background-primary);border:0.5px solid var(--color-border-tertiary);border-radius:var(--border-radius-md);padding:12px;"><div class="st">موجودیت‌ها</div>{entity_rows}</div>'
        f'<div style="background:var(--color-background-primary);border:0.5px solid var(--color-border-tertiary);border-radius:var(--border-radius-md);padding:12px;"><div class="st">Evidence</div><div style="display:flex;gap:5px;flex-wrap:wrap;">{evidence_html}</div></div>'
        f'<div style="background:var(--color-background-primary);border:0.5px solid var(--color-border-tertiary);border-radius:var(--border-radius-md);padding:12px;"><div class="st">هشدارها</div>{warnings_html}</div></div>'
        f'<div id="tab-order" style="flex:1;overflow-y:auto;padding:16px;display:{tab_style("order")};flex-direction:column;gap:12px;" dir="rtl">{order_tab_body}</div>'
        f'<div id="tab-metadata" style="flex:1;overflow-y:auto;padding:16px;display:{tab_style("metadata")};flex-direction:column;gap:12px;" dir="rtl">'
        '<div style="background:var(--color-background-primary);border:0.5px solid var(--color-border-tertiary);border-radius:var(--border-radius-lg);padding:14px 16px;">'
        '<div class="st">اطلاعات اتاق</div>'
        f'<div class="drow"><span style="color:var(--color-text-secondary);">room_id</span><span style="font-weight:500;font-family:monospace;font-size:12px;">{_e(record.get("room_id"))}</span></div>'
        f'<div class="drow"><span style="color:var(--color-text-secondary);">shop_id</span><span style="font-weight:500;font-family:monospace;font-size:12px;">{_e(record.get("shop_id"))}</span></div>'
        f'<div class="drow"><span style="color:var(--color-text-secondary);">room_type</span><span style="font-weight:500;">{_e(record.get("room_type"))}</span></div>'
        f'<div class="drow"><span style="color:var(--color-text-secondary);">target_message_id</span><span style="font-weight:500;font-family:monospace;font-size:12px;">{_e(record.get("target_message_id"))}</span></div>'
        f'<div class="drow"><span style="color:var(--color-text-secondary);">created_at_jalali</span><span style="font-weight:500;font-size:11px;">{_e(record.get("created_at_jalali"))}</span></div>'
        f'<div class="drow"><span style="color:var(--color-text-secondary);">processed_at_jalali</span><span style="font-weight:500;font-size:11px;">{_e(processed_at)}</span></div>'
        f'<div class="drow"><span style="color:var(--color-text-secondary);">final_reply_source</span><span style="font-weight:500;">{_e(pipeline.get("final_reply_source"))}</span></div>'
        f'<div class="drow"><span style="color:var(--color-text-secondary);">classifier_provider</span><span style="font-weight:500;">{_e(classifier_provider)}</span></div>'
        f'<div class="drow"><span style="color:var(--color-text-secondary);">fallback_reason</span><span style="color:var(--color-text-secondary);">{_e(fallback_reason)}</span></div>'
        f'<div class="drow"><span style="color:var(--color-text-secondary);">needs_human_review</span><span style="font-weight:500;">{_e(pipeline.get("needs_human_review"))}</span></div>'
        "</div></div></div>"
        '<div style="width:248px;background:var(--color-background-primary);border-left:0.5px solid var(--color-border-tertiary);overflow-y:auto;padding:14px;flex-shrink:0;display:flex;flex-direction:column;gap:14px;" dir="rtl">'
        '<div><div class="st">جزئیات</div>'
        f'<div class="drow"><span style="color:var(--color-text-secondary);">Room ID</span><span style="font-weight:500;">{_e(record.get("room_id"))}</span></div>'
        f'<div class="drow"><span style="color:var(--color-text-secondary);">Shop ID</span><span style="font-weight:500;">{_e(record.get("shop_id"))}</span></div>'
        f'<div class="drow"><span style="color:var(--color-text-secondary);">Message ID</span><span style="font-weight:500;">{_e(record.get("target_message_id"))}</span></div>'
        f'<div class="drow"><span style="color:var(--color-text-secondary);">Created At</span><span style="font-weight:500;font-size:11px;">{_e(record.get("created_at_jalali"))}</span></div>'
        f'<div class="drow"><span style="color:var(--color-text-secondary);">Room Type</span><span class="chip b">{_e(record.get("room_type"))}</span></div></div>'
        '<div><div class="st">اقدامات</div>'
        '<div class="ab pr">ارسال پاسخ به فروشنده</div>'
        '<div class="ab" style="margin-top:6px;">پیشنهاد ویرایش</div>'
        '<div class="ab dn" style="margin-top:6px;">رد کردن</div></div>'
        f'<div><div class="st">تاریخچه وضعیت</div><div id="status-history">{history_html}</div></div>'
        "</div></div></div></div></div>"
    )


def format_time_label() -> str:
    return datetime.now().strftime("%H:%M:%S")
