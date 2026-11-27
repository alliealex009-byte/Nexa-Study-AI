"""Colored inline sub-menus with Telegram Premium Emoji (Bot API 9.4+)."""

from __future__ import annotations

from config import Settings
from keyboards.styles import styled_button

try:
    from aiogram.types import InlineKeyboardMarkup
except ImportError:  # pragma: no cover
    class InlineKeyboardMarkup:  # type: ignore[no-redef]
        def __init__(self, inline_keyboard: list) -> None:
            self.inline_keyboard = inline_keyboard


def subject_submenu_keyboard(subject: str, settings: Settings | None = None) -> InlineKeyboardMarkup:
    """Inline sub-menu for Biology, Chemistry, or Physics with colored buttons & premium emoji."""
    subj_title = subject.title()
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                styled_button(f"Ask {subj_title} Doubt", callback_data=f"subject:{subject}", style="success", emoji_key=subject, settings=settings),
                styled_button(f"Random {subj_title} PYQ", callback_data=f"pyq:random:{subject}", style="primary", emoji_key="random", settings=settings),
            ],
            [
                styled_button("NCERT 11th & 12th", callback_data=f"ncert:subj:{subject}", style="primary", emoji_key="ncert", settings=settings),
                styled_button(f"{subj_title} Quiz", callback_data=f"quiz:start:subject:{subject}", style="success", emoji_key="quiz", settings=settings),
            ],
            [
                styled_button("Send Group Quiz Poll", callback_data=f"pyq:poll:{subject}", style="primary", emoji_key="spark", settings=settings),
                styled_button("Formula Card", callback_data="widget:formula", style="primary", emoji_key="widget", settings=settings),
            ],
            [
                styled_button("Main Menu", callback_data="menu:home", emoji_key="home", settings=settings),
            ],
        ]
    )


def doubt_followup_keyboard(subject: str, settings: Settings | None = None) -> InlineKeyboardMarkup:
    """Action buttons shown below every AI doubt answer."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                styled_button("Simpler Explanation", callback_data=f"mode:simpler:{subject}", style="primary", emoji_key="spark", settings=settings),
                styled_button("Exam-Oriented", callback_data=f"mode:exam:{subject}", style="success", emoji_key="quiz", settings=settings),
            ],
            [
                styled_button("Ask Follow-up", callback_data=f"doubt:followup:{subject}", style="primary", emoji_key="help", settings=settings),
                styled_button("Main Menu", callback_data="menu:home", emoji_key="home", settings=settings),
            ],
        ]
    )


def ncert_subject_keyboard(settings: Settings | None = None) -> InlineKeyboardMarkup:
    """Pick a subject to browse all Class 11 & 12 NCERT chapters."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                styled_button("Biology NCERT", callback_data="ncert:subj:biology", style="success", emoji_key="biology", settings=settings),
                styled_button("Chemistry NCERT", callback_data="ncert:subj:chemistry", style="primary", emoji_key="chemistry", settings=settings),
            ],
            [
                styled_button("Physics NCERT", callback_data="ncert:subj:physics", style="primary", emoji_key="physics", settings=settings),
                styled_button("Main Menu", callback_data="menu:home", emoji_key="home", settings=settings),
            ],
        ]
    )


def ncert_class_keyboard(subject: str, settings: Settings | None = None) -> InlineKeyboardMarkup:
    """Sub-menu to browse Class 11 or Class 12 chapters of a subject."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                styled_button(f"Class 11 {subject.title()}", callback_data=f"ncert:class:{subject}:11", style="success", emoji_key="ncert", settings=settings),
                styled_button(f"Class 12 {subject.title()}", callback_data=f"ncert:class:{subject}:12", style="primary", emoji_key="ncert", settings=settings),
            ],
            [
                styled_button("All Subjects", callback_data="menu:ncert", emoji_key="ncert", settings=settings),
                styled_button("Main Menu", callback_data="menu:home", emoji_key="home", settings=settings),
            ],
        ]
    )


def pyq_exam_keyboard(settings: Settings | None = None) -> InlineKeyboardMarkup:
    """10-Year PYQ sub-menu for NEET UG, JEE Main, JEE Advanced, Random Prep & Polls."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                styled_button("NEET UG (2016–2025)", callback_data="pyq:exam:NEET UG", style="success", emoji_key="biology", settings=settings),
                styled_button("JEE Main (2016–2025)", callback_data="pyq:exam:JEE Main", style="primary", emoji_key="physics", settings=settings),
            ],
            [
                styled_button("JEE Advanced (10-Yr)", callback_data="pyq:exam:JEE Advanced", style="primary", emoji_key="chemistry", settings=settings),
                styled_button("Random Prep (Any)", callback_data="pyq:random:all", style="success", emoji_key="random", settings=settings),
            ],
            [
                styled_button("Group Quiz Poll", callback_data="pyq:poll:all", style="primary", emoji_key="spark", settings=settings),
                styled_button("PYQ Flashcard", callback_data="widget:pyq", style="primary", emoji_key="widget", settings=settings),
            ],
            [
                styled_button("Main Menu", callback_data="menu:home", emoji_key="home", settings=settings),
            ],
        ]
    )


def pyq_subject_keyboard(exam: str, settings: Settings | None = None) -> InlineKeyboardMarkup:
    """Sub-menu inside an exam: pick subject, random 10-yr prep, or filter by year."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                styled_button("Random 10-Yr Prep", callback_data=f"pyq:list:{exam}:mixed", style="success", emoji_key="random", settings=settings),
                styled_button("Filter by Year", callback_data=f"pyq:years:{exam}", style="primary", emoji_key="pyq", settings=settings),
            ],
            [
                styled_button("Biology", callback_data=f"pyq:list:{exam}:biology", style="success", emoji_key="biology", settings=settings),
                styled_button("Chemistry", callback_data=f"pyq:list:{exam}:chemistry", style="primary", emoji_key="chemistry", settings=settings),
            ],
            [
                styled_button("Physics", callback_data=f"pyq:list:{exam}:physics", style="primary", emoji_key="physics", settings=settings),
                styled_button("Back to PYQs", callback_data="menu:pyq", emoji_key="home", settings=settings),
            ],
        ]
    )


def pyq_year_keyboard(exam: str, years: list[int], settings: Settings | None = None) -> InlineKeyboardMarkup:
    """Sub-menu of available 10-year exam years (e.g., 2016–2025)."""
    rows: list[list] = []
    row: list = []
    for yr in sorted(years, reverse=True):
        row.append(styled_button(str(yr), callback_data=f"pyq:year:{exam}:{yr}", style="primary", settings=settings))
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([styled_button("Back", callback_data=f"pyq:exam:{exam}", emoji_key="home", settings=settings)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def pyq_answer_keyboard(
    pyq_id: str,
    exam: str,
    subject: str,
    settings: Settings | None = None,
) -> InlineKeyboardMarkup:
    """Interactive colored option buttons for answering a PYQ in DM or Group Chat."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                styled_button("A", callback_data=f"pyq:ans:{pyq_id}:A", style="primary", settings=settings),
                styled_button("B", callback_data=f"pyq:ans:{pyq_id}:B", style="primary", settings=settings),
                styled_button("C", callback_data=f"pyq:ans:{pyq_id}:C", style="primary", settings=settings),
                styled_button("D", callback_data=f"pyq:ans:{pyq_id}:D", style="primary", settings=settings),
            ],
            [
                styled_button("Next Random PYQ", callback_data=f"pyq:list:{exam}:{subject}", style="success", emoji_key="random", settings=settings),
                styled_button("Send as Poll", callback_data=f"pyq:poll:{subject}", style="primary", emoji_key="spark", settings=settings),
            ],
            [
                styled_button("Main Menu", callback_data="menu:home", emoji_key="home", settings=settings),
            ],
        ]
    )


def widget_menu_keyboard(settings: Settings | None = None) -> InlineKeyboardMarkup:
    """Sub-menu for interactive study cards."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                styled_button("Progress Dashboard", callback_data="widget:progress", style="primary", emoji_key="progress", settings=settings),
            ],
            [
                styled_button("10-Yr PYQ Flashcard", callback_data="widget:pyq", style="success", emoji_key="pyq", settings=settings),
            ],
            [
                styled_button("Pomodoro & Formula Card", callback_data="widget:formula", style="primary", emoji_key="widget", settings=settings),
            ],
            [
                styled_button("Main Menu", callback_data="menu:home", emoji_key="home", settings=settings),
            ],
        ]
    )


def quiz_mode_keyboard(settings: Settings | None = None) -> InlineKeyboardMarkup:
    """Choose quiz mode: Subject-wise, Chapter-wise, Mixed, or Timed."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                styled_button("Biology Quiz", callback_data="quiz:start:subject:biology", style="success", emoji_key="biology", settings=settings),
                styled_button("Chemistry Quiz", callback_data="quiz:start:subject:chemistry", style="primary", emoji_key="chemistry", settings=settings),
            ],
            [
                styled_button("Physics Quiz", callback_data="quiz:start:subject:physics", style="primary", emoji_key="physics", settings=settings),
                styled_button("Mixed 10-Yr Mock", callback_data="quiz:start:mixed:mixed", style="success", emoji_key="random", settings=settings),
            ],
            [
                styled_button("Timed Test (5 min)", callback_data="quiz:start:timed:mixed", style="danger", emoji_key="quiz", settings=settings),
                styled_button("Chapter-wise Quiz", callback_data="quiz:chapters", style="primary", emoji_key="ncert", settings=settings),
            ],
            [styled_button("Main Menu", callback_data="menu:home", emoji_key="home", settings=settings)],
        ]
    )


def quiz_chapter_keyboard(chapters: list[str], settings: Settings | None = None) -> InlineKeyboardMarkup:
    """List verified chapters available for chapter-wise quizzes."""
    rows: list[list] = []
    for chap in chapters[:12]:
        rows.append([styled_button(chap, callback_data=f"quiz:chap:{chap[:40]}", style="primary", emoji_key="ncert", settings=settings)])
    rows.append([styled_button("Back to Quiz Menu", callback_data="menu:quiz", emoji_key="home", settings=settings)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def quiz_options_keyboard(settings: Settings | None = None) -> InlineKeyboardMarkup:
    """Colored MCQ answer buttons during an active quiz."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                styled_button("A", callback_data="quiz:ans:A", style="primary", settings=settings),
                styled_button("B", callback_data="quiz:ans:B", style="primary", settings=settings),
                styled_button("C", callback_data="quiz:ans:C", style="primary", settings=settings),
                styled_button("D", callback_data="quiz:ans:D", style="primary", settings=settings),
            ],
            [styled_button("End Quiz", callback_data="quiz:cancel", style="danger", emoji_key="cancel", settings=settings)],
        ]
    )


def settings_keyboard(current_exam: str, current_mode: str, settings: Settings | None = None) -> InlineKeyboardMarkup:
    """Settings sub-menu with green active-selection styling."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                styled_button("NEET UG", callback_data="set:exam:NEET UG", style="success" if current_exam == "NEET UG" else None, emoji_key="check" if current_exam == "NEET UG" else None, settings=settings),
                styled_button("JEE Main", callback_data="set:exam:JEE Main", style="success" if current_exam == "JEE Main" else None, emoji_key="check" if current_exam == "JEE Main" else None, settings=settings),
                styled_button("JEE Adv", callback_data="set:exam:JEE Advanced", style="success" if current_exam == "JEE Advanced" else None, emoji_key="check" if current_exam == "JEE Advanced" else None, settings=settings),
            ],
            [
                styled_button("Detailed", callback_data="set:mode:standard", style="primary" if current_mode == "standard" else None, settings=settings),
                styled_button("Simpler", callback_data="set:mode:simpler", style="primary" if current_mode == "simpler" else None, settings=settings),
                styled_button("Exam-Mode", callback_data="set:mode:exam", style="primary" if current_mode == "exam" else None, settings=settings),
            ],
            [styled_button("Main Menu", callback_data="menu:home", emoji_key="home", settings=settings)],
        ]
    )
