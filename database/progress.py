"""Student progress analytics repository (subject/chapter performance & weak topics)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from database.mongo import MongoManager


class ProgressRepository:
    """Tracks student doubts, quizzes, subject/chapter accuracy, and weak topics."""

    def __init__(self, mongo: MongoManager) -> None:
        self._mongo = mongo
        self._memory: dict[int, dict[str, Any]] = {}

    def _empty_doc(self, user_id: int) -> dict[str, Any]:
        return {
            "user_id": user_id,
            "questions_attempted": 0,
            "questions_solved": 0,
            "quizzes_completed": 0,
            "quiz_scores": [],
            "subjects": {},
            "chapters": {},
            "active_days": [],
            "updated_at": datetime.now(timezone.utc),
        }

    def _load(self, user_id: int) -> dict[str, Any]:
        if self._mongo.is_connected:
            doc = self._mongo.db["progress"].find_one({"user_id": user_id}, {"_id": 0})
            if doc:
                return doc
        if user_id not in self._memory:
            self._memory[user_id] = self._empty_doc(user_id)
        return self._memory[user_id]

    def _save(self, user_id: int, doc: dict[str, Any]) -> None:
        doc["updated_at"] = datetime.now(timezone.utc)
        # Keep stored arrays compact for 500 MB MongoDB limit
        doc["quiz_scores"] = doc.get("quiz_scores", [])[-20:]
        doc["active_days"] = doc.get("active_days", [])[-30:]
        self._memory[user_id] = doc
        if self._mongo.is_connected:
            self._mongo.db["progress"].replace_one({"user_id": user_id}, doc, upsert=True)

    @staticmethod
    def _record_day(doc: dict[str, Any]) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        days = doc.setdefault("active_days", [])
        if today not in days:
            days.append(today)

    @staticmethod
    def _safe_key(name: str) -> str:
        # MongoDB field names cannot contain dots or leading '$'
        return name.strip().replace(".", "_").replace("$", "")[:64] or "General"

    def record_doubt(self, user_id: int, subject: str, chapter: str = "") -> dict[str, Any]:
        """Record an AI doubt solved by the student."""
        doc = self._load(user_id)
        doc["questions_attempted"] = doc.get("questions_attempted", 0) + 1
        doc["questions_solved"] = doc.get("questions_solved", 0) + 1

        subj_key = self._safe_key(subject.title())
        subj = doc.setdefault("subjects", {}).setdefault(subj_key, {"attempted": 0, "correct": 0, "doubts": 0})
        subj["doubts"] = subj.get("doubts", 0) + 1

        if chapter:
            chap_key = self._safe_key(f"{subj_key}: {chapter}")
            chap = doc.setdefault("chapters", {}).setdefault(chap_key, {"attempted": 0, "correct": 0, "doubts": 0})
            chap["doubts"] = chap.get("doubts", 0) + 1

        self._record_day(doc)
        self._save(user_id, doc)
        return doc

    def record_quiz_result(
        self,
        user_id: int,
        *,
        mode: str,
        subject: str,
        score: int,
        total: int,
        item_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Record completed quiz scores and update subject/chapter accuracy."""
        doc = self._load(user_id)
        accuracy = round((score / total) * 100.0, 1) if total > 0 else 0.0

        doc["questions_attempted"] = doc.get("questions_attempted", 0) + total
        doc["questions_solved"] = doc.get("questions_solved", 0) + score
        doc["quizzes_completed"] = doc.get("quizzes_completed", 0) + 1
        doc.setdefault("quiz_scores", []).append(
            {
                "mode": mode,
                "subject": subject,
                "score": score,
                "total": total,
                "accuracy": accuracy,
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            }
        )

        subjects_map = doc.setdefault("subjects", {})
        chapters_map = doc.setdefault("chapters", {})
        for item in item_results:
            s_key = self._safe_key(str(item.get("subject", subject)).title())
            s_entry = subjects_map.setdefault(s_key, {"attempted": 0, "correct": 0, "doubts": 0})
            s_entry["attempted"] += 1
            if item.get("is_correct"):
                s_entry["correct"] += 1

            chapter_name = str(item.get("chapter", "")).strip()
            if chapter_name:
                c_key = self._safe_key(f"{s_key}: {chapter_name}")
                c_entry = chapters_map.setdefault(c_key, {"attempted": 0, "correct": 0, "doubts": 0})
                c_entry["attempted"] += 1
                if item.get("is_correct"):
                    c_entry["correct"] += 1

        self._record_day(doc)
        self._save(user_id, doc)
        return doc

    def get_summary(self, user_id: int) -> dict[str, Any]:
        """Compute analytics including overall accuracy and weak topics (<60% accuracy)."""
        doc = self._load(user_id)
        subjects_summary: list[dict[str, Any]] = []
        for name, stats in sorted(doc.get("subjects", {}).items()):
            att = stats.get("attempted", 0)
            cor = stats.get("correct", 0)
            acc = round((cor / att) * 100.0, 1) if att > 0 else None
            subjects_summary.append(
                {
                    "subject": name,
                    "attempted": att,
                    "correct": cor,
                    "doubts": stats.get("doubts", 0),
                    "accuracy": acc,
                }
            )

        weak_topics: list[dict[str, Any]] = []
        for chap_name, stats in doc.get("chapters", {}).items():
            att = stats.get("attempted", 0)
            cor = stats.get("correct", 0)
            if att >= 1:
                acc = round((cor / att) * 100.0, 1)
                if acc < 60.0:
                    weak_topics.append({"topic": chap_name, "attempted": att, "correct": cor, "accuracy": acc})
        weak_topics.sort(key=lambda item: (item["accuracy"], -item["attempted"]))

        total_quiz_att = sum(s["attempted"] for s in subjects_summary)
        total_quiz_cor = sum(s["correct"] for s in subjects_summary)
        quiz_accuracy = round((total_quiz_cor / total_quiz_att) * 100.0, 1) if total_quiz_att > 0 else 0.0

        return {
            "user_id": user_id,
            "questions_attempted": doc.get("questions_attempted", 0),
            "questions_solved": doc.get("questions_solved", 0),
            "quizzes_completed": doc.get("quizzes_completed", 0),
            "quiz_accuracy": quiz_accuracy,
            "recent_quizzes": doc.get("quiz_scores", [])[-5:],
            "subjects": subjects_summary,
            "weak_topics": weak_topics[:5],
            "active_days_count": len(doc.get("active_days", [])),
        }
