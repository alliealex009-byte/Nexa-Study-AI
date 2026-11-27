"""Lightweight ARM64 progress chart generator (Pillow PNG) & NEET/JEE motivational quotes."""

from __future__ import annotations

import io
import random
from typing import Any

from PIL import Image, ImageDraw, ImageFont

MOTIVATIONAL_QUOTES: list[str] = [
    "Every NCERT line you master today is 4 marks locked in on exam day. Keep going!",
    "Consistency beats last-minute cramming—10 focused questions a day build an unstoppable rank.",
    "Mistakes during practice are your best teachers; each wrong MCQ now is one you won't miss in the exam hall.",
    "Small daily improvements lead to massive NEET & JEE breakthroughs. Stay disciplined!",
    "Speed follows accuracy—understand the concept cleanly first, then beat the 45-second timer.",
    "Your future stethoscope or IIT campus is built one solved doubt at a time.",
    "Don't fear weak chapters—attack them first, and they become your biggest rank boosters.",
    "Champions aren't born in one night; they show up every single day even when it's tough.",
]


def pick_motivational_quote(accuracy: float = 0.0, today_count: int = 0) -> str:
    """Return an encouraging, context-aware NEET/JEE motivational quote."""
    if today_count >= 15 and accuracy >= 75.0:
        return "🔥 Incredible momentum today! High accuracy + daily volume is the exact formula for a top rank."
    if 0 < accuracy < 50.0:
        return "💪 Tough chapters build strong ranks—review your weak topics below and watch your accuracy climb!"
    return random.choice(MOTIVATIONAL_QUOTES)


def _load_font(size: int) -> ImageFont.ImageFont:
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_progress_graphic(summary: dict[str, Any], student_name: str = "Student") -> bytes:
    """Render a crisp dark-mode PNG analytics card showing Today/Weekly/Monthly stats & weak areas."""
    width, height = 840, 560
    img = Image.new("RGB", (width, height), color=(15, 23, 42))
    draw = ImageDraw.Draw(img)

    f_title = _load_font(26)
    f_sub = _load_font(16)
    f_num = _load_font(28)
    f_label = _load_font(15)
    f_small = _load_font(13)

    # Header bar
    draw.rectangle([(0, 0), (width, 72)], fill=(30, 41, 59))
    draw.text((28, 16), f"NEXA STUDY AI  •  {student_name[:22]}", fill=(248, 250, 252), font=f_title)
    draw.text((28, 48), "Powered by AAKASH AI  |  Performance & Focus Map", fill=(148, 163, 184), font=f_small)

    # Top KPI cards: Today, Weekly, Monthly, Accuracy
    kpis = [
        ("TODAY", str(summary.get("today_questions", 0)), (56, 189, 248)),
        ("WEEKLY (7d)", str(summary.get("weekly_questions", 0)), (34, 197, 94)),
        ("MONTHLY (30d)", str(summary.get("monthly_questions", 0)), (168, 85, 247)),
        ("ACCURACY", f"{summary.get('quiz_accuracy', 0.0):.0f}%", (250, 204, 21)),
    ]
    card_w = 182
    gap = 18
    start_x = 28
    for idx, (label, value, accent) in enumerate(kpis):
        x0 = start_x + idx * (card_w + gap)
        y0, x1, y1 = 92, x0 + card_w, 178
        draw.rounded_rectangle([(x0, y0), (x1, y1)], radius=12, fill=(30, 41, 59), outline=(51, 65, 85), width=2)
        draw.text((x0 + 16, y0 + 14), label, fill=(148, 163, 184), font=f_small)
        draw.text((x0 + 16, y0 + 38), value, fill=accent, font=f_num)

    # Left column: Subject Performance Bars
    draw.text((28, 202), "SUBJECT ACCURACY", fill=(226, 232, 240), font=f_sub)
    subjects = summary.get("subjects", [])
    y = 234
    if not subjects:
        draw.text((28, y), "Attempt a quiz or PYQ to populate subject bars.", fill=(148, 163, 184), font=f_label)
    else:
        for s in subjects[:4]:
            acc = s["accuracy"] if s["accuracy"] is not None else 0.0
            label_txt = f"{s['subject']} ({acc:.0f}%)" if s["accuracy"] is not None else f"{s['subject']} ({s['doubts']} doubts)"
            draw.text((28, y), label_txt, fill=(241, 245, 249), font=f_label)
            bar_x0, bar_y0, bar_w, bar_h = 28, y + 24, 360, 16
            draw.rounded_rectangle([(bar_x0, bar_y0), (bar_x0 + bar_w, bar_y0 + bar_h)], radius=8, fill=(51, 65, 85))
            fill_w = max(14, int(bar_w * min(100.0, acc) / 100.0))
            bar_color = (34, 197, 94) if acc >= 70 else ((250, 204, 21) if acc >= 50 else (239, 68, 68))
            draw.rounded_rectangle([(bar_x0, bar_y0), (bar_x0 + fill_w, bar_y0 + bar_h)], radius=8, fill=bar_color)
            y += 58

    # Right column: Weak Topics (Where to Work Next)
    draw.text((430, 202), "FOCUS AREAS (WORK HERE NEXT)", fill=(252, 165, 165), font=f_sub)
    weak_topics = summary.get("weak_topics", [])
    wy = 234
    if not weak_topics:
        draw.rounded_rectangle([(430, wy), (812, wy + 72)], radius=12, fill=(20, 83, 45), outline=(34, 197, 94))
        draw.text((448, wy + 24), "No weak chapters yet — great consistency!", fill=(187, 247, 208), font=f_label)
    else:
        for topic in weak_topics[:4]:
            t_name = str(topic["topic"])[:30]
            t_acc = float(topic["accuracy"])
            draw.text((430, wy), f"{t_name}  ({t_acc:.0f}%)", fill=(254, 226, 226), font=f_label)
            bx0, by0, bw, bh = 430, wy + 24, 380, 14
            draw.rounded_rectangle([(bx0, by0), (bx0 + bw, by0 + bh)], radius=7, fill=(51, 65, 85))
            fw = max(14, int(bw * max(5.0, min(100.0, t_acc)) / 100.0))
            draw.rounded_rectangle([(bx0, by0), (bx0 + fw, by0 + bh)], radius=7, fill=(239, 68, 68))
            wy += 56

    # Footer motivational banner
    quote = pick_motivational_quote(
        accuracy=float(summary.get("quiz_accuracy", 0.0)),
        today_count=int(summary.get("today_questions", 0)),
    )
    draw.rounded_rectangle([(28, 486), (812, 540)], radius=10, fill=(30, 58, 138))
    draw.text((44, 504), quote[:88], fill=(219, 234, 254), font=f_small)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
