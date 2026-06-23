"""Streamlit live HITL review console."""

from __future__ import annotations

import html
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import streamlit as st

from hitl.jalali import to_jalali
from hitl.sender import parse_refer_to, send_both, send_reply, send_suggestion
from hitl.state import (
    FEEDBACK_LABELS,
    can_send,
    load_records,
    get_record,
    update_record,
)

_SELLER_SENDERS = {"shop", "seller"}
_SUPPORT_SENDERS = {"admin", "support", "system"}
_TIMELINE_LABELS = {
    "seller": "فروشنده",
    "support": "پشتیبانی",
    "ai": "AI",
}
_NAV_ITEMS = (
    ("all", "▤", "همه بررسی‌ها"),
    ("pending", "⏳", "در انتظار بررسی"),
    ("approved", "✔", "تایید شده"),
    ("needs_edit", "✎", "نیاز به ویرایش"),
    ("sent", "➤", "ارسال شده"),
    ("rejected", "⊘", "رد شده"),
)
_FEEDBACK_OPTIONS = (
    ("wrong_reply", "❌ اشتباه در پاسخ"),
    ("wrong_intent", "⚠ اشتباه در قصد"),
    ("correct", "👍 صحیح"),
    ("wrong_tool", "✂ ابزار نادرست"),
    ("missing_tool", "🔧 ابزار استفاده نشده"),
)

_HITL_CSS = """
<style>
:root{
  --sidebar-bg:#0f1722;--sidebar-bg2:#0b121b;--sidebar-active:#1d4ed8;
  --sidebar-text:#c7d2e0;--sidebar-muted:#6b7a90;--page-bg:#f3f5f9;
  --card-bg:#ffffff;--border:#e3e8ef;--border-2:#eef1f6;--text:#1f2a37;
  --text-muted:#6b7280;--blue:#2563eb;--blue-soft:#dbe7fb;--blue-bubble:#eaf1fd;
  --gray-bubble:#f3f4f6;--green:#16a34a;--green-soft:#dcfce7;--green-bubble:#e7f7ec;
  --amber:#f59e0b;--amber-soft:#fef3c7;--red:#dc2626;--red-soft:#fde7e7;
  --live:#22c55e;--radius:12px;
  --shadow:0 1px 3px rgba(16,24,40,.06),0 1px 2px rgba(16,24,40,.04);
}
.hitl-app{font-family:Tahoma,"Segoe UI",Arial,sans-serif;background:var(--page-bg);color:var(--text);font-size:13px;}
.hitl-shell{display:flex;min-height:calc(100vh - 2rem);gap:0;}
.hitl-sidebar{width:300px;flex-shrink:0;background:linear-gradient(180deg,var(--sidebar-bg),var(--sidebar-bg2));color:var(--sidebar-text);direction:rtl;display:flex;flex-direction:column;}
.sidebar-head{padding:22px 20px 18px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid rgba(255,255,255,.06);}
.sidebar-title{font-size:18px;font-weight:700;color:#fff;}
.live-badge{background:var(--live);color:#05230f;font-size:11px;font-weight:800;padding:3px 10px;border-radius:6px;letter-spacing:1px;}
.nav{padding:14px 12px;display:flex;flex-direction:column;gap:4px;flex:1;}
.nav-item{display:flex;align-items:center;justify-content:space-between;padding:11px 14px;border-radius:9px;color:var(--sidebar-text);}
.nav-item.active{background:var(--sidebar-active);color:#fff;box-shadow:0 4px 12px rgba(29,78,216,.4);}
.nav-left{display:flex;align-items:center;gap:11px;font-size:13.5px;}
.nav-ico{width:18px;text-align:center;opacity:.9;}
.nav-count{background:rgba(255,255,255,.12);color:#fff;font-size:12px;font-weight:700;min-width:26px;text-align:center;padding:2px 7px;border-radius:7px;}
.nav-item.active .nav-count{background:rgba(255,255,255,.22);}
.nav-item .nav-count.zero{background:rgba(255,255,255,.06);color:var(--sidebar-muted);}
.sidebar-foot{border-top:1px solid rgba(255,255,255,.06);padding:14px 18px 18px;font-size:12px;color:var(--sidebar-muted);}
.foot-line{margin-top:8px;line-height:1.7;}
.foot-line b{color:#aab6c6;font-weight:600;}
.hitl-main{flex:1;min-width:0;padding:18px 22px;}
.content{display:grid;grid-template-columns:1fr 400px;grid-template-rows:auto 1fr;gap:16px;align-content:start;}
.header-cards{grid-column:1/-1;background:var(--card-bg);border:1px solid var(--border);border-radius:var(--radius);box-shadow:var(--shadow);display:flex;direction:rtl;}
.hc{flex:1;padding:14px 18px;display:flex;align-items:center;gap:12px;border-left:1px solid var(--border-2);}
.hc:last-child{border-left:none;}
.hc-ico{font-size:20px;opacity:.85;}
.hc-body{display:flex;flex-direction:column;gap:3px;}
.hc-label{font-size:11.5px;color:var(--text-muted);}
.hc-value{font-size:15px;font-weight:700;color:var(--text);}
.hc-value.small{font-size:13px;}
.status-pill{background:var(--amber-soft);color:#b45309;font-weight:700;font-size:12px;padding:4px 10px;border-radius:7px;display:inline-block;}
.left-col{grid-column:1;grid-row:2;}
.right-panel{grid-column:2;grid-row:1/span 2;display:flex;flex-direction:column;gap:16px;direction:rtl;}
.conversation{background:var(--card-bg);border:1px solid var(--border);border-radius:var(--radius);box-shadow:var(--shadow);display:flex;flex-direction:column;direction:rtl;min-height:560px;}
.conv-head{display:flex;align-items:center;justify-content:space-between;padding:14px 18px;border-bottom:1px solid var(--border-2);}
.conv-title{font-size:13.5px;font-weight:700;color:var(--text);}
.conv-jump{font-size:12.5px;color:var(--text-muted);border:1px solid var(--border);border-radius:8px;padding:7px 12px;background:#fff;text-decoration:none;display:inline-flex;align-items:center;gap:7px;}
.conv-body{flex:1;padding:18px;overflow-y:auto;max-height:560px;display:flex;flex-direction:column;gap:14px;background:#fcfcfd;}
.conv-start{text-align:center;color:var(--text-muted);font-size:12px;margin:4px 0 2px;}
.conv-start span{background:#fff;border:1px solid var(--border-2);padding:4px 14px;border-radius:20px;}
.msg{display:flex;gap:10px;max-width:78%;}
.msg.left{align-self:flex-start;flex-direction:row;}
.msg.right{align-self:flex-end;flex-direction:row-reverse;}
.avatar{width:34px;height:34px;border-radius:9px;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:16px;}
.av-seller{background:var(--blue-soft);color:var(--blue);}
.av-support{background:#eceff3;color:#64748b;}
.av-ai{background:var(--green-soft);color:var(--green);}
.av-label{font-size:10px;text-align:center;color:var(--text-muted);margin-top:3px;}
.avatar-col{display:flex;flex-direction:column;align-items:center;}
.bubble{border-radius:14px;padding:10px 13px;line-height:1.75;font-size:13px;position:relative;}
.bubble .time{font-size:11px;color:var(--text-muted);margin-bottom:5px;display:block;}
.b-seller{background:var(--blue-bubble);color:#1e3a8a;}
.b-support{background:var(--gray-bubble);color:#374151;}
.b-ai{background:var(--green-bubble);color:#14532d;}
.bubble.current{border:2px solid var(--amber);background:#fffdf5;}
.current-badge{display:inline-flex;align-items:center;gap:4px;background:var(--amber);color:#3d2c02;font-size:10.5px;font-weight:700;padding:2px 9px;border-radius:6px;margin-top:7px;}
.legend{display:flex;align-items:center;justify-content:center;gap:22px;padding:13px 18px;border-top:1px solid var(--border-2);font-size:12px;color:var(--text-muted);}
.legend-item{display:flex;align-items:center;gap:7px;}
.dot{width:10px;height:10px;border-radius:50%;}
.dot.blue{background:var(--blue);}.dot.gray{background:#9aa5b4;}.dot.green{background:var(--green);}
.card{background:var(--card-bg);border:1px solid var(--border);border-radius:var(--radius);box-shadow:var(--shadow);padding:16px;}
.card-title{display:flex;align-items:center;gap:8px;font-size:13.5px;font-weight:700;margin-bottom:14px;color:var(--text);}
.ai-final{background:var(--green-bubble);border:1px solid #c6ecd2;border-radius:10px;padding:12px 13px;margin-bottom:14px;}
.ai-final-label{font-size:11.5px;color:var(--green);font-weight:700;margin-bottom:6px;}
.ai-final-text{font-size:13px;line-height:1.85;color:#14532d;}
.kv{display:flex;align-items:center;justify-content:space-between;padding:9px 0;border-bottom:1px solid var(--border-2);font-size:12.5px;}
.kv:last-child{border-bottom:none;}
.kv-label{color:var(--text-muted);}.kv-val{font-weight:700;color:var(--text);}
.kv-val.green{color:var(--green);}.kv-val.muted{color:var(--text-muted);}
.confidence-row{padding:9px 0;border-bottom:1px solid var(--border-2);}
.confidence-top{display:flex;justify-content:space-between;font-size:12.5px;margin-bottom:7px;}
.bar{height:7px;background:#eef1f6;border-radius:5px;overflow:hidden;}
.bar-fill{height:100%;background:linear-gradient(90deg,#22c55e,#16a34a);border-radius:5px;}
.tab-pane-card{background:var(--card-bg);border:1px solid var(--border);border-radius:var(--radius);box-shadow:var(--shadow);padding:16px;direction:rtl;text-align:right;line-height:1.8;font-size:13px;}
.tab-pre{white-space:pre-wrap;word-break:break-word;font-family:inherit;font-size:12.5px;direction:ltr;text-align:left;background:#f8fafc;border:1px solid var(--border-2);border-radius:8px;padding:12px;margin-top:8px;}
.fund-warn{display:flex;gap:11px;background:var(--amber-soft);border:1px solid #fde68a;border-radius:10px;padding:12px;margin-top:4px;font-size:12px;line-height:1.7;color:#92400e;}
.record-picker{padding:0 12px 12px;}
div[data-testid="stSidebar"],#MainMenu,footer,header{visibility:hidden;height:0;}
.block-container{padding-top:0!important;padding-bottom:1rem!important;max-width:100%!important;}
.stTabs [data-baseweb="tab-list"]{direction:rtl;gap:4px;}
.stTabs [data-baseweb="tab"]{font-size:13.5px;}
</style>
"""

_STREAMLIT_HIDE = """
<style>
#MainMenu,footer,header{visibility:hidden;}
.block-container{padding-top:0!important;max-width:100%!important;}
</style>
"""


@st.cache_data(ttl=10)
def _cached_records(state_path: str) -> list[dict[str, Any]]:
    return load_records(Path(state_path))


def _classify_timeline_kind(item: dict[str, Any]) -> str:
    sender = str(item.get("sender", "")).lower()
    role = str(item.get("role", "")).lower()
    if sender in _SELLER_SENDERS or role == "user":
        return "seller"
    if sender in _SUPPORT_SENDERS or role == "assistant":
        return "support"
    if role == "ai" or str(item.get("kind", "")).lower() == "ai":
        return "ai"
    return "support"


def _item_timestamp(item: dict[str, Any], fallback: str | None = None) -> str | None:
    for key in ("created_at_jalali", "timestamp", "created_at"):
        value = item.get(key)
        if value:
            return str(value)
    return fallback


def _short_time(value: str | None) -> str:
    if not value:
        return ""
    text = str(value)
    if " " in text:
        return text.split(" ", 1)[1]
    return text


def build_timeline_messages(record: dict[str, Any]) -> list[dict[str, Any]]:
    target_id = str(record.get("target_message_id", ""))
    stored = record.get("timeline_messages")
    if isinstance(stored, list) and stored:
        timeline: list[dict[str, Any]] = []
        for index, item in enumerate(stored):
            message_id = item.get("id")
            item_id = str(message_id) if message_id is not None else f"timeline-{index}"
            kind = _classify_timeline_kind(item)
            timeline.append(
                {
                    "message_id": item_id,
                    "kind": kind,
                    "label": _TIMELINE_LABELS[kind],
                    "content": str(item.get("content", "")),
                    "timestamp": _item_timestamp(item),
                    "is_target": bool(item.get("is_target"))
                    or (target_id and item_id == target_id),
                }
            )
    else:
        timeline = []
        seen_ids: set[str] = set()
        for index, item in enumerate(record.get("conversation_context", [])):
            message_id = item.get("id")
            item_id = str(message_id) if message_id is not None else f"context-{index}"
            kind = _classify_timeline_kind(item)
            timeline.append(
                {
                    "message_id": item_id,
                    "kind": kind,
                    "label": _TIMELINE_LABELS[kind],
                    "content": str(item.get("content", "")),
                    "timestamp": _item_timestamp(item),
                    "is_target": item_id == target_id,
                }
            )
            seen_ids.add(item_id)
        if target_id and target_id not in seen_ids:
            timeline.append(
                {
                    "message_id": target_id,
                    "kind": "seller",
                    "label": _TIMELINE_LABELS["seller"],
                    "content": str(record.get("seller_message", "")),
                    "timestamp": record.get("created_at_jalali") or record.get("created_at"),
                    "is_target": True,
                }
            )
        else:
            for message in timeline:
                if str(message["message_id"]) == target_id:
                    message["is_target"] = True

    final_reply = str(record.get("pipeline", {}).get("final_reply", "")).strip()
    has_ai = any(message["kind"] == "ai" for message in timeline)
    if final_reply and not has_ai:
        timeline.append(
            {
                "message_id": f"ai-{target_id or record.get('record_id', 'reply')}",
                "kind": "ai",
                "label": _TIMELINE_LABELS["ai"],
                "content": final_reply,
                "timestamp": record.get("created_at_jalali") or record.get("created_at"),
                "is_target": False,
            }
        )
    return timeline


def _compute_sidebar_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    edit_labels = {"wrong_intent", "wrong_reply", "wrong_tool", "missing_tool"}
    return {
        "all": len(records),
        "pending": sum(1 for r in records if r.get("status") == "pending_review"),
        "approved": sum(
            1 for r in records if r.get("feedback", {}).get("label") == "correct"
        ),
        "needs_edit": sum(
            1 for r in records if r.get("feedback", {}).get("label") in edit_labels
        ),
        "sent": sum(
            1
            for r in records
            if r.get("status") in {"sent", "sent_both", "suggested"}
        ),
        "rejected": sum(1 for r in records if r.get("status") == "rejected_local"),
    }


def _filter_by_nav(records: list[dict[str, Any]], nav: str) -> list[dict[str, Any]]:
    edit_labels = {"wrong_intent", "wrong_reply", "wrong_tool", "missing_tool"}
    if nav == "pending":
        return [r for r in records if r.get("status") == "pending_review"]
    if nav == "approved":
        return [r for r in records if r.get("feedback", {}).get("label") == "correct"]
    if nav == "needs_edit":
        return [r for r in records if r.get("feedback", {}).get("label") in edit_labels]
    if nav == "sent":
        return [r for r in records if r.get("status") in {"sent", "sent_both", "suggested"}]
    if nav == "rejected":
        return [r for r in records if r.get("status") == "rejected_local"]
    return records


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _bool_fa(value: Any) -> str:
    if value is True:
        return "بله"
    if value is False:
        return "خیر"
    return "—"


def _confidence_percent(pipeline: dict[str, Any]) -> tuple[str, int]:
    raw = pipeline.get("confidence")
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return "—", 0
    if number <= 1:
        number *= 100
    percent = max(0, min(100, int(round(number))))
    return f"{percent}%", percent


def _order_tool_count(record: dict[str, Any]) -> int:
    tools = record.get("pipeline", {}).get("selected_tools", []) or []
    outputs = record.get("tool_output", []) or []
    if "order_lookup" in tools or outputs:
        return max(1, len(outputs))
    return 0


def _render_sidebar_nav(counts: dict[str, int], active: str) -> None:
    items = []
    for key, icon, label in _NAV_ITEMS:
        count = counts.get(key, 0)
        zero = " zero" if count == 0 else ""
        active_cls = " active" if key == active else ""
        items.append(
            f'<div class="nav-item{active_cls}">'
            f'<div class="nav-left"><span class="nav-ico">{icon}</span><span>{_esc(label)}</span></div>'
            f'<span class="nav-count{zero}">{count}</span></div>'
        )
    st.markdown("".join(items), unsafe_allow_html=True)


def _header_cards_html(record: dict[str, Any]) -> str:
    status = _esc(record.get("status", ""))
    created = _esc(record.get("created_at_jalali", ""))
    return f"""
    <div class="header-cards">
      <div class="hc"><span class="hc-ico">💬</span><div class="hc-body"><span class="hc-label">شناسه روم</span><span class="hc-value">{_esc(record.get("room_id"))}</span></div></div>
      <div class="hc"><span class="hc-ico">🏪</span><div class="hc-body"><span class="hc-label">شناسه فروشگاه</span><span class="hc-value">{_esc(record.get("shop_id"))}</span></div></div>
      <div class="hc"><span class="hc-ico">🆔</span><div class="hc-body"><span class="hc-label">شناسه پیام</span><span class="hc-value">{_esc(record.get("target_message_id"))}</span></div></div>
      <div class="hc"><span class="hc-ico">⚑</span><div class="hc-body"><span class="hc-label">وضعیت</span><span class="status-pill">{status}</span></div></div>
      <div class="hc"><span class="hc-ico">📅</span><div class="hc-body"><span class="hc-label">ایجاد شده در</span><span class="hc-value small">{created}</span></div></div>
      <div class="hc"><span class="hc-ico">🎧</span><div class="hc-body"><span class="hc-label">نوع روم</span><span class="hc-value">{_esc(record.get("room_type"))}</span></div></div>
    </div>
    """


def _message_html(message: dict[str, Any], target_anchor: str) -> str:
    kind = message["kind"]
    is_target = bool(message.get("is_target"))
    side = "right" if kind == "seller" else "left"
    if kind == "seller":
        av_class, bubble_class, icon = "av-seller", "b-seller", "👤"
    elif kind == "ai":
        av_class, bubble_class, icon = "av-ai", "b-ai", "🤖"
    else:
        av_class, bubble_class, icon = "av-support", "b-support", "🎧"
    current = " current" if is_target else ""
    anchor = target_anchor if is_target else f'timeline-{_esc(message["message_id"])}'
    badge = (
        '<div><span class="current-badge">↻ پیام فعلی</span></div>'
        if is_target
        else ""
    )
    content = _esc(message.get("content", "")).replace("\n", "<br>")
    time_text = _esc(_short_time(message.get("timestamp")))
    return f"""
    <div class="msg {side}" id="{anchor}">
      <div class="avatar-col">
        <div class="avatar {av_class}">{icon}</div>
        <div class="av-label">{_esc(message["label"])}</div>
      </div>
      <div class="bubble {bubble_class}{current}">
        <span class="time">{time_text}</span>
        {content}
        {badge}
      </div>
    </div>
    """


def _conversation_html(record: dict[str, Any]) -> str:
    messages = build_timeline_messages(record)
    target_id = _esc(record.get("target_message_id", ""))
    target_anchor = f"target-message-{target_id}"
    body = "".join(_message_html(message, target_anchor) for message in reversed(messages))
    return f"""
    <div class="conversation">
      <div class="conv-head">
        <div class="conv-title">مکالمه روم (همه پیام‌ها از ابتدا تا کنون)</div>
        <a class="conv-jump" href="#{target_anchor}"><span>↻</span><span>رفتن به پیام فعلی</span></a>
      </div>
      <div class="conv-body" id="convBody">
        {body}
        <div class="conv-start"><span>۞ شروع مکالمه ۞</span></div>
      </div>
      <div class="legend">
        <div class="legend-item"><span class="dot blue"></span> پیام فروشنده</div>
        <div class="legend-item"><span class="dot gray"></span> پیام پشتیبانی</div>
        <div class="legend-item"><span class="dot green"></span> پیام AI</div>
      </div>
    </div>
  """


def _ai_summary_html(record: dict[str, Any]) -> str:
    pipeline = record.get("pipeline", {})
    final_reply = _esc(pipeline.get("final_reply", "")).replace("\n", "<br>")
    conf_text, conf_pct = _confidence_percent(pipeline)
    warnings = pipeline.get("warnings", []) or record.get("warnings", [])
    warning_text = _esc(", ".join(str(item) for item in warnings)) if warnings else "—"
    review_class = "green" if pipeline.get("needs_human_review") is False else ""
    send_class = "green" if pipeline.get("should_send") is True else ""
    return f"""
    <div class="card">
      <div class="card-title"><span>🤖</span> خلاصه پاسخ AI</div>
      <div class="ai-final">
        <div class="ai-final-label">پاسخ نهایی</div>
        <div class="ai-final-text">{final_reply or "—"}</div>
      </div>
      <div class="kv"><span class="kv-label">قصد اصلی</span><span class="kv-val">{_esc(pipeline.get("primary_intent", "—"))}</span></div>
      <div class="confidence-row">
        <div class="confidence-top"><span class="kv-label">میزان اطمینان</span><span class="kv-val">{conf_text}</span></div>
        <div class="bar"><div class="bar-fill" style="width:{conf_pct}%"></div></div>
      </div>
      <div class="kv"><span class="kv-label">اقدام پیشنهادی</span><span class="kv-val">{_esc(pipeline.get("suggested_action", "—"))}</span></div>
      <div class="kv"><span class="kv-label">نیاز به بررسی انسانی</span><span class="kv-val {review_class}">{_bool_fa(pipeline.get("needs_human_review"))}</span></div>
      <div class="kv"><span class="kv-label">ارسال خودکار</span><span class="kv-val {send_class}">{_bool_fa(pipeline.get("should_send"))}</span></div>
      <div class="kv"><span class="kv-label">هشدارها</span><span class="kv-val muted">{warning_text}</span></div>
    </div>
    """


def _tab_ai_html(record: dict[str, Any]) -> str:
    pipeline = record.get("pipeline", {})
    return f"""
    <div class="tab-pane-card">
      <div><b>پاسخ نهایی</b><br>{_esc(pipeline.get("final_reply", "—")).replace(chr(10), "<br>")}</div>
      <div style="margin-top:12px;"><b>منبع پاسخ</b><br>{_esc(pipeline.get("final_reply_source", "—"))}</div>
      <div style="margin-top:12px;"><b>Entities</b></div>
      <pre class="tab-pre">{_esc(json.dumps(pipeline.get("entities", {}), ensure_ascii=False, indent=2))}</pre>
      <div style="margin-top:12px;"><b>Safe Tool Output</b></div>
      <pre class="tab-pre">{_esc(json.dumps(record.get("tool_output", []), ensure_ascii=False, indent=2))}</pre>
    </div>
    """


def _tab_order_html(record: dict[str, Any]) -> str:
    outputs = record.get("tool_output", []) or []
    if not outputs:
        return '<div class="tab-pane-card">نتیجه‌ای از جستجوی سفارش برای این رکورد موجود نیست.</div>'
    blocks = []
    for index, item in enumerate(outputs, start=1):
        blocks.append(
            f"<div style='margin-bottom:12px;'><b>سفارش {index}</b>"
            f"<pre class='tab-pre'>{_esc(json.dumps(item, ensure_ascii=False, indent=2))}</pre></div>"
        )
    return f'<div class="tab-pane-card">{"".join(blocks)}</div>'


def _tab_tools_html(record: dict[str, Any]) -> str:
    pipeline = record.get("pipeline", {})
    tools = pipeline.get("selected_tools", []) or []
    return f"""
    <div class="tab-pane-card">
      <div><b>ابزارهای انتخاب‌شده</b><br>{_esc(", ".join(tools) if tools else "—")}</div>
      <div style="margin-top:12px;"><b>خروجی امن ابزارها</b></div>
      <pre class="tab-pre">{_esc(json.dumps(record.get("tool_output", []), ensure_ascii=False, indent=2))}</pre>
    </div>
    """


def _tab_log_html(record: dict[str, Any]) -> str:
    pipeline = record.get("pipeline", {})
    log = {
        "warnings": record.get("warnings", []),
        "pipeline_warnings": pipeline.get("warnings", []),
        "evidence": pipeline.get("evidence", []),
        "send_log": record.get("send_log", []),
    }
    return f"""
    <div class="tab-pane-card">
      <div><b>لاگ پردازش</b></div>
      <pre class="tab-pre">{_esc(json.dumps(log, ensure_ascii=False, indent=2))}</pre>
    </div>
    """


def _tab_meta_html(record: dict[str, Any]) -> str:
    meta = {
        "record_id": record.get("record_id"),
        "target_message_id": record.get("target_message_id"),
        "room_id": record.get("room_id"),
        "shop_id": record.get("shop_id"),
        "room_type": record.get("room_type"),
        "status": record.get("status"),
        "created_at": record.get("created_at"),
        "created_at_jalali": record.get("created_at_jalali"),
        "feedback": record.get("feedback"),
    }
    return f"""
    <div class="tab-pane-card">
      <div><b>متادیتای رکورد</b></div>
      <pre class="tab-pre">{_esc(json.dumps(meta, ensure_ascii=False, indent=2))}</pre>
    </div>
    """


def _save_feedback(record_id: str, label: str, comment: str) -> None:
    update_record(
        record_id,
        {
            "feedback": {
                "label": label,
                "comment": comment,
                "created_at_jalali": to_jalali(),
            }
        },
    )


def _handle_send(
    record: dict[str, Any],
    action: str,
    refer_to_raw: str,
    request_fn=None,
) -> None:
    record_id = str(record["record_id"])
    current = get_record(record_id)
    if current is None or not can_send(str(current.get("status", ""))):
        st.error("Send blocked: record is not in a sendable status.")
        return
    try:
        refer_to = parse_refer_to(refer_to_raw)
    except ValueError:
        st.error("Refer To must be empty or a valid integer.")
        return

    update_record(record_id, {"status": "send_attempted"})
    logs = list(current.get("send_log", []))

    if action == "reply":
        result = send_reply(current, refer_to=refer_to, request_fn=request_fn)
        logs.append(result)
        status = "sent" if result.get("success") else "send_failed"
        update_record(record_id, {"status": status, "send_log": logs})
    elif action == "suggestion":
        result = send_suggestion(current, refer_to=refer_to, request_fn=request_fn)
        logs.append(result)
        status = "suggested" if result.get("success") else "send_failed"
        update_record(record_id, {"status": status, "send_log": logs})
    elif action == "both":
        results = send_both(current, refer_to=refer_to, request_fn=request_fn)
        logs.extend(results)
        reply_ok = results[0].get("success")
        suggestion_ok = results[1].get("success")
        if reply_ok and suggestion_ok:
            status = "sent_both"
        elif reply_ok:
            status = "sent"
        elif suggestion_ok:
            status = "suggested"
        else:
            status = "send_failed"
        update_record(record_id, {"status": status, "send_log": logs})
    elif action == "reject":
        update_record(record_id, {"status": "rejected_local"})
    elif action == "retry":
        last_action = st.session_state.get(f"retry_action_{record_id}", "reply")
        _handle_send(record, last_action, refer_to_raw, request_fn=request_fn)
        return


def _render_actions(record: dict[str, Any]) -> None:
    record_id = str(record["record_id"])
    status = str(record.get("status", ""))
    fund_confirmed = True
    if record.get("room_type") == "fund":
        st.markdown(
            f'<div class="fund-warn"><span class="warn-ico">⚠</span>'
            f"<div>این روم از نوع <b>fund</b> است.<br>"
            f"قبل از ارسال، از صحت مبلغ و شماره حساب اطمینان حاصل کنید.</div></div>",
            unsafe_allow_html=True,
        )
        fund_confirmed = st.checkbox(
            "تایید بررسی مالی",
            key=f"fund_confirm_{record_id}",
        )
    refer_to_raw = st.text_input(
        "Refer To (ارجاع)",
        key=f"refer_to_{record_id}",
        label_visibility="collapsed",
        placeholder="Refer To (اختیاری)",
    )
    disabled = not fund_confirmed or not can_send(status)
    if st.button("➤ ارسال پاسخ به فروشنده", disabled=disabled, key=f"send_reply_{record_id}", use_container_width=True):
        _handle_send(record, "reply", refer_to_raw)
        st.rerun()
    if st.button("💬 ارسال پیشنهاد (بدون ارسال)", disabled=disabled, key=f"send_suggestion_{record_id}", use_container_width=True):
        _handle_send(record, "suggestion", refer_to_raw)
        st.rerun()
    if st.button("✅ ارسال هر دو", disabled=disabled, key=f"send_both_{record_id}", use_container_width=True):
        _handle_send(record, "both", refer_to_raw)
        st.rerun()
    col1, col2 = st.columns(2)
    with col1:
        if st.button("⊘ رد در سیستم", disabled=not can_send(status), key=f"reject_{record_id}", use_container_width=True):
            _handle_send(record, "reject", refer_to_raw)
            st.rerun()
    with col2:
        if status in {"send_failed", "error"} and st.button("↻ تلاش مجدد", key=f"retry_{record_id}", use_container_width=True):
            st.session_state[f"retry_action_{record_id}"] = "reply"
            _handle_send(record, "retry", refer_to_raw)
            st.rerun()


def _render_feedback(record: dict[str, Any]) -> None:
    record_id = str(record["record_id"])
    labels = [label for label, _ in _FEEDBACK_OPTIONS if label in FEEDBACK_LABELS]
    display = {label: text for label, text in _FEEDBACK_OPTIONS if label in FEEDBACK_LABELS}
    current = record.get("feedback", {}).get("label", "")
    selected = st.radio(
        "بازخورد اپراتور",
        options=labels,
        index=labels.index(current) if current in labels else 0,
        format_func=lambda value: display.get(value, value),
        key=f"feedback_label_{record_id}",
    )
    comment = st.text_area(
        "توضیحات",
        value=str(record.get("feedback", {}).get("comment", "")),
        key=f"feedback_comment_{record_id}",
        placeholder="توضیحات اختیاری...",
    )
    if st.button("ثبت بازخورد", key=f"save_feedback_{record_id}", use_container_width=True):
        _save_feedback(record_id, selected, comment)
        st.success("بازخورد ثبت شد.")
        st.rerun()


def main() -> None:
    st.set_page_config(
        layout="wide",
        page_title="HITL Review Console",
        initial_sidebar_state="collapsed",
    )
    st.markdown(_HITL_CSS + _STREAMLIT_HIDE, unsafe_allow_html=True)

    if "nav_filter" not in st.session_state:
        st.session_state.nav_filter = "all"
    if "selected_record_id" not in st.session_state:
        st.session_state.selected_record_id = None

    state_path = str(Path("state") / "hitl_state.jsonl")
    records = _cached_records(state_path)
    counts = _compute_sidebar_counts(records)
    filtered = _filter_by_nav(records, st.session_state.nav_filter)
    filtered.sort(
        key=lambda record: (
            0 if record.get("status") == "pending_review" else 1,
            record.get("created_at_jalali", ""),
        ),
        reverse=True,
    )

    now_local = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Tehran"))
    last_refresh = to_jalali(now_local)
    auto_refresh = st.session_state.get("auto_refresh", True)

    st.markdown('<div class="hitl-app"><div class="hitl-shell">', unsafe_allow_html=True)

    side_col, main_col = st.columns([0.22, 0.78], gap="small")

    with side_col:
        st.markdown(
            '<div class="hitl-sidebar"><div class="sidebar-head">'
            '<div class="sidebar-title">HITL Review Console</div>'
            '<div class="live-badge">LIVE</div></div><div class="nav">',
            unsafe_allow_html=True,
        )
        _render_sidebar_nav(counts, st.session_state.nav_filter)
        st.markdown("</div>", unsafe_allow_html=True)
        nav_keys = [key for key, _, _ in _NAV_ITEMS]
        nav_labels = {key: label for key, _, label in _NAV_ITEMS}
        current_idx = (
            nav_keys.index(st.session_state.nav_filter)
            if st.session_state.nav_filter in nav_keys
            else 0
        )
        selected_nav = st.selectbox(
            "فیلتر",
            nav_keys,
            index=current_idx,
            format_func=lambda key: nav_labels[key],
            label_visibility="collapsed",
            key="nav_filter_select",
        )
        if selected_nav != st.session_state.nav_filter:
            st.session_state.nav_filter = selected_nav
            st.rerun()
        if st.button("↻ تازه‌سازی", key="refresh_btn", use_container_width=True):
            _cached_records.clear()
            st.rerun()
        st.markdown(
            f'<div class="sidebar-foot">'
            f'<div class="foot-line"><b>آخرین بروزرسانی:</b> {_esc(last_refresh)}</div>'
            f'<div class="foot-line">Auto refresh: {"ON" if auto_refresh else "OFF"} (10s)</div>'
            f"</div></div>",
            unsafe_allow_html=True,
        )
        st.session_state.auto_refresh = st.checkbox(
            "Auto refresh (10s)",
            value=auto_refresh,
            key="auto_refresh_toggle",
        )

    with main_col:
        st.markdown('<div class="hitl-main"><div class="content">', unsafe_allow_html=True)
        if not filtered:
            st.info("هیچ رکوردی برای این فیلتر موجود نیست.")
        else:
            options = [str(r["record_id"]) for r in filtered]
            if st.session_state.selected_record_id not in options:
                st.session_state.selected_record_id = options[0]
            selected = st.selectbox(
                "رکورد",
                options=options,
                index=options.index(st.session_state.selected_record_id),
                format_func=lambda rid: next(
                    (
                        f"{rid} · room {r.get('room_id')} · {r.get('status')}"
                        for r in filtered
                        if str(r.get("record_id")) == rid
                    ),
                    rid,
                ),
                key="record_select",
            )
            st.session_state.selected_record_id = selected
            record = next(r for r in filtered if str(r["record_id"]) == selected)

            st.markdown(_header_cards_html(record), unsafe_allow_html=True)

            left_col, right_col = st.columns([1.55, 1], gap="medium")
            with left_col:
                order_count = _order_tool_count(record)
                order_label = f"🔍 جستجوی سفارش ({order_count})" if order_count else "🔍 جستجوی سفارش"
                tabs = st.tabs(
                    [
                        "💬 مکالمه",
                        "🤖 پاسخ AI",
                        order_label,
                        "🛠 ابزارها",
                        "📋 لاگ پردازش",
                        "🗂 متادیتا",
                    ]
                )
                with tabs[0]:
                    st.markdown(_conversation_html(record), unsafe_allow_html=True)
                    target_id = _esc(record.get("target_message_id", ""))
                    scroll_key = f"timeline_scrolled_{record['record_id']}"
                    if scroll_key not in st.session_state and target_id:
                        st.session_state[scroll_key] = True
                        st.markdown(
                            f"<script>window.setTimeout(function(){{"
                            f"var el=document.getElementById('target-message-{target_id}');"
                            f"if(el){{el.scrollIntoView({{block:'center'}});"
                            f"var box=document.getElementById('convBody');"
                            f"if(box){{box.scrollTop=Math.max(0, el.offsetTop-box.offsetTop-80);}}}}"
                            f"}},120);</script>",
                            unsafe_allow_html=True,
                        )
                with tabs[1]:
                    st.markdown(_tab_ai_html(record), unsafe_allow_html=True)
                with tabs[2]:
                    st.markdown(_tab_order_html(record), unsafe_allow_html=True)
                with tabs[3]:
                    st.markdown(_tab_tools_html(record), unsafe_allow_html=True)
                with tabs[4]:
                    st.markdown(_tab_log_html(record), unsafe_allow_html=True)
                with tabs[5]:
                    st.markdown(_tab_meta_html(record), unsafe_allow_html=True)

            with right_col:
                st.markdown(_ai_summary_html(record), unsafe_allow_html=True)
                st.markdown('<div class="card"><div class="card-title"><span>⚙</span> عملیات</div>', unsafe_allow_html=True)
                _render_actions(record)
                st.markdown("</div>", unsafe_allow_html=True)
                st.markdown('<div class="card"><div class="card-title"><span>🗳</span> بازخورد اپراتور</div>', unsafe_allow_html=True)
                if str(record.get("status", "")) == "pending_review":
                    _render_feedback(record)
                else:
                    st.caption("بازخورد فقط برای رکوردهای pending_review فعال است.")
                st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("</div></div>", unsafe_allow_html=True)

    st.markdown("</div></div>", unsafe_allow_html=True)

    if st.session_state.get("auto_refresh", True):
        if "last_refresh" not in st.session_state:
            st.session_state.last_refresh = time.time()
        if time.time() - st.session_state.last_refresh >= 10:
            st.session_state.last_refresh = time.time()
            _cached_records.clear()
            st.rerun()


if __name__ == "__main__":
    main()
