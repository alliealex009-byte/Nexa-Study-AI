"""Interactive MCQ quiz and timed mock test engine."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from services.pyq import PYQItem, PYQService


@dataclass
class QuizSession:
    """Active in-memory quiz session for a Telegram user."""

    user_id: int
    mode: str  # "chapter", "subject", "mixed", "timed"
    subject: str
    questions: list[PYQItem]
    current_index: int = 0
    answers: dict[int, str] = field(default_factory=dict)
    started_at: float = field(default_factory=time.monotonic)
    time_limit_seconds: int | None = None

    @property
    def is_expired(self) -> bool:
        if self.time_limit_seconds is None:
            return False
        return (time.monotonic() - self.started_at) > self.time_limit_seconds

    @property
    def remaining_seconds(self) -> int | None:
        if self.time_limit_seconds is None:
            return None
        return max(0, int(self.time_limit_seconds - (time.monotonic() - self.started_at)))

    @property
    def current_question(self) -> PYQItem | None:
        if 0 <= self.current_index < len(self.questions):
            return self.questions[self.current_index]
        return None


class QuizService:
    """Manages chapter-wise, subject-wise, mixed, and timed MCQ quizzes."""

    def __init__(self, pyq_service: PYQService) -> None:
        self._pyq_service = pyq_service
        self._sessions: dict[int, QuizSession] = {}

    def start_quiz(
        self,
        user_id: int,
        *,
        mode: str = "mixed",
        subject: str | None = None,
        chapter: str | None = None,
        num_questions: int = 5,
        time_limit_seconds: int | None = None,
    ) -> QuizSession | None:
        """Create and store a new quiz session from verified questions."""
        pool = self._pyq_service.query(
            subject=None if mode in ("mixed", "timed") and not subject else subject,
            chapter=chapter,
            limit=max(1, num_questions),
            shuffle=True,
        )
        if not pool:
            return None

        session = QuizSession(
            user_id=user_id,
            mode=mode,
            subject=(subject or "mixed").lower(),
            questions=pool,
            time_limit_seconds=time_limit_seconds,
        )
        self._sessions[user_id] = session
        return session

    def get_session(self, user_id: int) -> QuizSession | None:
        return self._sessions.get(user_id)

    def cancel_session(self, user_id: int) -> None:
        self._sessions.pop(user_id, None)

    def submit_answer(self, user_id: int, selected_option: str) -> tuple[bool, QuizSession | None, bool]:
        """Record an answer for the current question.

        Returns: (accepted, session, is_finished)
        """
        session = self._sessions.get(user_id)
        if session is None:
            return False, None, True

        if session.is_expired:
            return False, session, True

        idx = session.current_index
        if idx >= len(session.questions):
            return False, session, True

        session.answers[idx] = selected_option.strip().upper()
        session.current_index += 1
        finished = session.current_index >= len(session.questions)
        return True, session, finished

    def finalize_session(self, user_id: int) -> dict[str, Any] | None:
        """Score a finished or timed-out quiz and return full review details."""
        session = self._sessions.pop(user_id, None)
        if session is None:
            return None

        total = len(session.questions)
        score = 0
        item_results: list[dict[str, Any]] = []

        for idx, q in enumerate(session.questions):
            chosen = session.answers.get(idx, "Not Attempted")
            is_correct = chosen == q.correct_option
            if is_correct:
                score += 1
            item_results.append(
                {
                    "index": idx + 1,
                    "pyq_id": q.pyq_id,
                    "exam": q.exam,
                    "year": q.year,
                    "subject": q.subject,
                    "chapter": q.chapter,
                    "question": q.question,
                    "chosen": chosen,
                    "correct": q.correct_option,
                    "is_correct": is_correct,
                    "explanation": q.explanation,
                    "source": q.source,
                }
            )

        accuracy = round((score / total) * 100.0, 1) if total > 0 else 0.0
        elapsed = round(time.monotonic() - session.started_at, 1)
        return {
            "mode": session.mode,
            "subject": session.subject,
            "score": score,
            "total": total,
            "accuracy": accuracy,
            "elapsed_seconds": elapsed,
            "timed_out": session.is_expired,
            "items": item_results,
        }
