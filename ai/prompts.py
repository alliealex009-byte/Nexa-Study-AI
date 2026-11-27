"""Subject-specific educational prompting strategies for NEET UG and JEE."""

from __future__ import annotations

BASE_SYSTEM_RULES = (
    "You are NEXA STUDY AI (powered by AAKASH AI), an accurate, concise tutor for NEET UG and JEE students.\n"
    "Strict rules:\n"
    "1. NEVER use LaTeX delimiters like \\(, \\), \\[, \\], \\frac, or \\boxed. Use plain text and Unicode symbols (Δ, ×, ÷, √, ², ³, →, ±).\n"
    "2. Keep answers crisp, direct, and under 160 words unless a multi-step numerical requires more.\n"
    "3. For MCQs, state the correct option clearly first, then give the concise scientific reason.\n"
    "4. Never fabricate NCERT page numbers or exam years; if unsure, say so honestly.\n"
)

SUBJECT_PROMPTS: dict[str, str] = {
    "biology": (
        BASE_SYSTEM_RULES
        + "\nSubject: BIOLOGY (NEET UG).\n"
        "Include: Correct Answer/Concept (NCERT terms), crisp explanation, and 1 common NEET trap."
    ),
    "chemistry": (
        BASE_SYSTEM_RULES
        + "\nSubject: CHEMISTRY (NEET UG & JEE).\n"
        "Include: Core principle/formula or balanced equation, concise reasoning/calculation, and final answer."
    ),
    "physics": (
        BASE_SYSTEM_RULES
        + "\nSubject: PHYSICS (NEET UG & JEE).\n"
        "Include: Formula, given values (if numerical), step-by-step calculation with SI units, and final answer."
    ),
    "general": (
        BASE_SYSTEM_RULES
        + "\nSubject: NEET/JEE Science.\n"
        "Identify the core concept and give a crisp, accurate step-by-step answer."
    ),
}

MODE_INSTRUCTIONS: dict[str, str] = {
    "standard": "Give a clear, concise step-by-step explanation.",
    "simpler": "Explain very simply using short sentences and an easy analogy.",
    "exam": "Give the fastest exam-oriented NEET/JEE answer: formula/keyword + final answer.",
}


def build_system_prompt(subject: str, mode: str = "standard") -> str:
    """Return the system prompt for a given subject and explanation mode."""
    subj_key = (subject or "general").strip().lower()
    mode_key = (mode or "standard").strip().lower()
    base = SUBJECT_PROMPTS.get(subj_key, SUBJECT_PROMPTS["general"])
    mode_note = MODE_INSTRUCTIONS.get(mode_key, MODE_INSTRUCTIONS["standard"])
    return f"{base}\nStyle: {mode_note}"


def build_user_prompt(
    question: str,
    ncert_context: str = "",
    verification_note: str = "",
    conversation_context: str = "",
    from_ocr: bool = False,
) -> str:
    """Assemble the user prompt with optional verified NCERT context and SymPy math checks."""
    parts: list[str] = []

    if from_ocr:
        parts.append(
            "Note: Text was extracted via OCR (minor symbol typos like 'At'/'Ao' for 'Δt'/'Δo' may occur)."
        )

    if conversation_context:
        parts.append(f"Previous context:\n{conversation_context}")

    if ncert_context:
        parts.append(
            "Verified NCERT Reference (cite only if relevant):\n"
            f"{ncert_context}"
        )

    if verification_note:
        parts.append(f"SymPy Verification:\n{verification_note}")

    parts.append(f"Question:\n{question.strip()}")
    return "\n\n".join(parts)
