"""Telegram Bot API 10.4+ HTML Widgets (sendWidget) with automatic fallback.

Telegram Bot API 10.4 constraints enforced here:
- HTML payload must be 1–32768 UTF-8 bytes.
- Compressed HTML (zlib level 9) must be <= 4096 bytes.
- In production, widgets are currently supported in private chats only; group chats
  automatically receive native Telegram Quiz Polls or formatted HTML cards.
"""

from __future__ import annotations

import html as html_lib
import logging
import zlib
from typing import Any

from services.pyq import PYQItem

logger = logging.getLogger(__name__)

MAX_WIDGET_RAW_BYTES = 32768
MAX_WIDGET_ZLIB_BYTES = 4096


def validate_widget_html(widget_html: str) -> tuple[bool, int, int]:
    """Check Bot API 10.4 size limits (raw <= 32768 B, zlib level-9 <= 4096 B)."""
    raw = widget_html.encode("utf-8")
    compressed = zlib.compress(raw, level=9)
    ok = (1 <= len(raw) <= MAX_WIDGET_RAW_BYTES) and (len(compressed) <= MAX_WIDGET_ZLIB_BYTES)
    return ok, len(raw), len(compressed)


def build_progress_widget_html(summary: dict[str, Any], student_name: str = "Student") -> str:
    """Build a sleek, interactive Telegram HTML Widget showing student progress & weak topics."""
    name = html_lib.escape(student_name[:32] or "Student")
    attempted = int(summary.get("questions_attempted", 0))
    solved = int(summary.get("questions_solved", 0))
    quizzes = int(summary.get("quizzes_completed", 0))
    acc = float(summary.get("quiz_accuracy", 0.0))
    days = int(summary.get("active_days_count", 0))

    subj_bars = []
    for s in summary.get("subjects", [])[:4]:
        s_name = html_lib.escape(str(s["subject"]))
        s_acc = s["accuracy"] if s["accuracy"] is not None else 0.0
        s_label = f"{s_acc:.0f}%" if s["accuracy"] is not None else f"{s['doubts']} doubts"
        subj_bars.append(
            f"<div class='bar-row'><div class='bar-top'><span>{s_name}</span><span>{s_label}</span></div>"
            f"<div class='track'><div class='fill' style='width:{min(100, max(6, int(s_acc)))}%'></div></div></div>"
        )
    if not subj_bars:
        subj_bars.append("<p class='muted'>Solve a question or quiz to unlock subject bars.</p>")

    weak_chips = "".join(
        f"<span class='chip'>{html_lib.escape(str(w['topic']))} ({w['accuracy']:.0f}%)</span>"
        for w in summary.get("weak_topics", [])[:3]
    ) or "<span class='chip ok'>No weak topics yet</span>"

    return (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        "body{margin:0;padding:14px;font-family:system-ui,-apple-system,sans-serif;"
        "background:linear-gradient(135deg,#0f172a,#1e293b);color:#f8fafc;}"
        ".hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}"
        ".badge{background:#2563eb;padding:3px 8px;border-radius:999px;font-size:11px;font-weight:600}"
        ".grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px}"
        ".kpi{background:rgba(255,255,255,.07);border-radius:10px;padding:8px;text-align:center}"
        ".kpi b{display:block;font-size:18px;color:#38bdf8}.kpi small{font-size:11px;color:#cbd5e1}"
        ".bar-row{margin-bottom:8px}.bar-top{display:flex;justify-content:space-between;font-size:12px;margin-bottom:3px}"
        ".track{height:7px;background:rgba(255,255,255,.12);border-radius:99px;overflow:hidden}"
        ".fill{height:100%;background:linear-gradient(90deg,#22c55e,#38bdf8);border-radius:99px}"
        ".chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}"
        ".chip{font-size:11px;padding:4px 8px;border-radius:8px;background:rgba(239,68,68,.22);color:#fecaca}"
        ".chip.ok{background:rgba(34,197,94,.22);color:#bbf7d0}.muted{font-size:12px;color:#94a3b8}"
        "</style></head><body>"
        f"<div class='hdr'><b>NEXA STUDY AI • {name}</b><span class='badge'>{days}d Active</span></div>"
        "<div class='grid'>"
        f"<div class='kpi'><b>{attempted}</b><small>Attempted</small></div>"
        f"<div class='kpi'><b>{acc:.0f}%</b><small>Accuracy</small></div>"
        f"<div class='kpi'><b>{quizzes}</b><small>Quizzes</small></div>"
        "</div>"
        f"{''.join(subj_bars)}"
        f"<div class='chips'>{weak_chips}</div>"
        "</body></html>"
    )


def build_pyq_flashcard_widget_html(item: PYQItem) -> str:
    """Build an interactive 10-year PYQ flashcard HTML widget (tap options directly inside widget)."""
    exam_tag = html_lib.escape(f"{item.exam} {item.year} • {item.subject.title()}")
    chapter = html_lib.escape(item.chapter)
    question = html_lib.escape(item.question)
    explanation = html_lib.escape(item.explanation)
    source = html_lib.escape(item.source)
    correct = html_lib.escape(item.correct_option)

    opts_html = "".join(
        f"<button class='opt' onclick=\"pick(this,'{html_lib.escape(k)}')\">"
        f"<b>{html_lib.escape(k)}.</b> {html_lib.escape(v)}</button>"
        for k, v in sorted(item.options.items())
    )

    return (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        "body{margin:0;padding:14px;font-family:system-ui,-apple-system,sans-serif;"
        "background:#0b1120;color:#f1f5f9}"
        ".top{display:flex;justify-content:space-between;font-size:11px;color:#38bdf8;margin-bottom:6px}"
        ".q{font-size:14px;line-height:1.4;margin-bottom:10px;font-weight:500}"
        ".opt{display:block;width:100%;text-align:left;margin:6px 0;padding:9px 10px;border:1px solid #334155;"
        "border-radius:10px;background:#1e293b;color:#f8fafc;font-size:13px;cursor:pointer}"
        ".opt.ok{background:#14532d;border-color:#22c55e}.opt.bad{background:#7f1d1d;border-color:#ef4444}"
        "#exp{display:none;margin-top:10px;padding:9px;border-radius:10px;background:rgba(56,189,248,.12);"
        "font-size:12px;line-height:1.4;color:#e2e8f0}"
        "</style></head><body>"
        f"<div class='top'><span>{exam_tag}</span><span>{chapter}</span></div>"
        f"<div class='q'>{question}</div>"
        f"{opts_html}"
        f"<div id='exp'><b>Answer: {correct}</b><br>{explanation}<br><small>{source}</small></div>"
        f"<script>var C='{correct}';function pick(b,k){{document.querySelectorAll('.opt').forEach(function(e){{"
        "e.disabled=true;if(e.innerText.startsWith(C+'.'))e.classList.add('ok');});"
        "if(k!==C)b.classList.add('bad');document.getElementById('exp').style.display='block';}}</script>"
        "</body></html>"
    )


def build_formula_timer_widget_html() -> str:
    """Build an interactive Pomodoro + High-Yield NEET/JEE Formula Quick-Flip Widget."""
    return (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        "body{margin:0;padding:14px;font-family:system-ui,-apple-system,sans-serif;"
        "background:linear-gradient(135deg,#1e1b4b,#0f172a);color:#f8fafc}"
        ".row{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}"
        ".tm{font-size:24px;font-weight:700;color:#a5b4fc;font-variant-numeric:tabular-nums}"
        ".btn{padding:6px 12px;border:none;border-radius:8px;background:#2563eb;color:#fff;font-size:12px;cursor:pointer}"
        ".btn.g{background:#16a34a}.card{background:rgba(255,255,255,.08);padding:10px;border-radius:10px;font-size:13px}"
        "</style></head><body>"
        "<div class='row'><b>⏱️ NEET/JEE Focus Widget</b><span class='tm' id='t'>25:00</span></div>"
        "<div class='row'><button class='btn g' onclick='go()'>Start / Pause</button>"
        "<button class='btn' onclick='nextF()'>Next Formula ➡️</button></div>"
        "<div class='card' id='f'>📐 Physics: F = dp/dt = m·a | v² = u² + 2as</div>"
        "<script>var s=1500,r=null,i=0,fs=["
        "'📐 Physics: F = dp/dt = m·a | v² = u² + 2as',"
        "'📐 Electrostatics: F = k·|q₁q₂|/r², k = 9×10⁹ N·m²/C²',"
        "'⚗️ Physical Chem: ΔG° = -RT ln K = -nFE°',"
        "'⚗️ Solutions: p₁ = p₁°·x₁ (Raoult’s Law, ΔHmix=0)',"
        "'🧬 Biology: Mitochondria = 70S ribosomes + circular DNA, cristae for ATP',"
        "'🧬 Genetics: RNA polymerase reads 3′→5′ template, builds 5′→3′ RNA'];"
        "function upd(){var m=Math.floor(s/60),x=s%60;document.getElementById('t').textContent="
        "(m<10?'0':'')+m+':'+(x<10?'0':'')+x;}"
        "function go(){if(r){clearInterval(r);r=null;return;}r=setInterval(function(){if(s>0){s--;upd();}},1000);}"
        "function nextF(){i=(i+1)%fs.length;document.getElementById('f').textContent=fs[i];}</script>"
        "</body></html>"
    )


async def send_widget_or_fallback(
    *,
    bot: Any,
    chat_id: int,
    chat_type: str,
    widget_html: str,
    caption: str,
    fallback_text: str,
    reply_markup: Any = None,
    enabled: bool = True,
    height: int = 340,
) -> bool:
    """Send a Bot API 10.4 HTML Widget in private chats, falling back cleanly if unavailable.

    Returns True if native sendWidget succeeded, False if fallback message was sent.
    """
    ok, raw_len, comp_len = validate_widget_html(widget_html)
    if enabled and chat_type == "private" and ok and hasattr(bot, "send_widget"):
        try:
            await bot.send_widget(
                chat_id=chat_id,
                html=widget_html,
                height=height,
                caption=caption,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
            return True
        except Exception as exc:
            logger.info(
                "sendWidget unavailable for chat %s (raw=%dB, zlib=%dB): %s — using styled HTML fallback.",
                chat_id,
                raw_len,
                comp_len,
                exc,
            )

    await bot.send_message(
        chat_id=chat_id,
        text=fallback_text,
        parse_mode="HTML",
        reply_markup=reply_markup,
    )
    return False
