"""Post-processor that converts LLM & dataset LaTeX/Markdown into clean Telegram Unicode/HTML."""

from __future__ import annotations

import html as html_lib
import re

_LATEX_SYMBOLS: list[tuple[str, str]] = [
    (r"\\Delta(?![A-Za-z])", "Δ"),
    (r"\\delta(?![A-Za-z])", "δ"),
    (r"\\alpha(?![A-Za-z])", "α"),
    (r"\\beta(?![A-Za-z])", "β"),
    (r"\\gamma(?![A-Za-z])", "γ"),
    (r"\\theta(?![A-Za-z])", "θ"),
    (r"\\lambda(?![A-Za-z])", "λ"),
    (r"\\mu(?![A-Za-z])", "μ"),
    (r"\\nu(?![A-Za-z])", "ν"),
    (r"\\pi(?![A-Za-z])", "π"),
    (r"\\rho(?![A-Za-z])", "ρ"),
    (r"\\sigma(?![A-Za-z])", "σ"),
    (r"\\omega(?![A-Za-z])", "ω"),
    (r"\\Omega(?![A-Za-z])", "Ω"),
    (r"\\phi(?![A-Za-z])", "φ"),
    (r"\\epsilon_0(?![A-Za-z0-9])", "ε₀"),
    (r"\\varepsilon_0(?![A-Za-z0-9])", "ε₀"),
    (r"\\epsilon(?![A-Za-z])", "ε"),
    (r"\\times(?![A-Za-z])", "×"),
    (r"\\cdot(?![A-Za-z])", "·"),
    (r"\\div(?![A-Za-z])", "÷"),
    (r"\\pm(?![A-Za-z])", "±"),
    (r"\\leq(?![A-Za-z])|\\le(?![A-Za-z])", "≤"),
    (r"\\geq(?![A-Za-z])|\\ge(?![A-Za-z])", "≥"),
    (r"\\neq(?![A-Za-z])|\\ne(?![A-Za-z])", "≠"),
    (r"\\approx(?![A-Za-z])", "≈"),
    (r"\\propto(?![A-Za-z])", "∝"),
    (r"\\infty(?![A-Za-z])", "∞"),
    (r"\\rightarrow(?![A-Za-z])|\\to(?![A-Za-z])", "→"),
    (r"\\leftarrow(?![A-Za-z])", "←"),
    (r"\\rightleftharpoons(?![A-Za-z])", "⇌"),
    (r"\\degree(?![A-Za-z])|\\circ(?![A-Za-z])", "°"),
    (r"\\left(?![A-Za-z])|\\right(?![A-Za-z])", ""),
]

_SUPERSCRIPTS = str.maketrans("0123456789+-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻")
_SUBSCRIPTS = str.maketrans("0123456789+-", "₀₁₂₃₄₅₆₇₈₉₊₋")


def clean_latex_to_unicode(text: str) -> str:
    """Replace LaTeX blocks, commands, and broken OCR/dataset braces with clean Unicode."""
    out = text or ""

    # Strip display/inline math delimiters: \[ ... \], \( ... \), $$ ... $$, $ ... $
    out = re.sub(r"\\\[(.*?)\\\]", lambda m: m.group(1).strip(), out, flags=re.DOTALL)
    out = re.sub(r"\\\((.*?)\\\)", lambda m: m.group(1).strip(), out, flags=re.DOTALL)
    out = re.sub(r"\$\$(.*?)\$\$", lambda m: m.group(1).strip(), out, flags=re.DOTALL)
    out = re.sub(r"(?<!\$)\$([^$\n]{1,200})\$(?!\$)", lambda m: m.group(1).strip(), out)

    # Unwrap \boxed{...}, \text{...}, \mathrm{...}, \mathbf{...}, \mathit{...}, \operatorname{...}
    for _ in range(3):
        out = re.sub(r"\\(?:boxed|text|mathrm|mathbf|mathit|mathcal|operatorname)\s*\{([^{}]+)\}", r"\1", out)
        out = re.sub(r"\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}", r"(\1/\2)", out)
        out = re.sub(r"\\sqrt\s*\{([^{}]+)\}", r"√(\1)", out)

    for pattern, repl in _LATEX_SYMBOLS:
        out = re.sub(pattern, repl, out)

    # Handle malformed exponents like 10^(-5} or 10^{-10} or 10^2
    out = re.sub(r"\^[\{\(]([0-9+\-]{1,5})[\}\)]", lambda m: m.group(1).translate(_SUPERSCRIPTS), out)
    out = re.sub(r"\^([0-9])(?![0-9])", lambda m: m.group(1).translate(_SUPERSCRIPTS), out)
    out = re.sub(r"_[\{\(]([0-9+\-]{1,5})[\}\)]", lambda m: m.group(1).translate(_SUBSCRIPTS), out)
    out = re.sub(r"_([0-9])(?![0-9])", lambda m: m.group(1).translate(_SUBSCRIPTS), out)
    out = re.sub(r"([A-Za-zΔ])_\{?([A-Za-z0-9]{1,3})\}?", r"\1\2", out)

    # Remove stray LaTeX spacing commands and leftover single $ or ~
    out = re.sub(r"\\[,;!]", " ", out)
    out = re.sub(r"\\(?:quad|qquad)(?![A-Za-z])", " ", out)
    out = out.replace("~", " ").replace("$", "")
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out.strip()


def format_ai_response_for_telegram(raw_text: str, max_len: int = 3900) -> str:
    """Convert raw LLM output (possibly with LaTeX & Markdown) into clean Telegram HTML."""
    text = clean_latex_to_unicode(raw_text or "").strip()
    escaped = html_lib.escape(text)

    escaped = re.sub(r"(?m)^#{1,4}\s+(.+)$", r"<b>\1</b>", escaped)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", escaped)

    if len(escaped) > max_len:
        escaped = escaped[: max_len - 40].rstrip() + "\n\n…(truncated for Telegram)"
    return escaped


def detect_subject_from_text(text: str, fallback: str = "general") -> str:
    """Infer Biology, Chemistry, or Physics from question text so the right prompt is used."""
    lower = (text or "").lower()
    scores = {"biology": 0, "chemistry": 0, "physics": 0}

    bio_kw = (
        "biology", "botany", "zoology", "mitochondria", "ribosome", "dna", "rna", "cell",
        "chromosome", "meiosis", "mitosis", "photosynthesis", "chloroplast", "enzyme",
        "hormone", "ovulation", "neuron", "nephron", "xylem", "phloem", "ecosystem",
        "genetics", "mendel", "transcription", "translation", "c4 plant", "blood", "heart",
    )
    chem_kw = (
        "chemistry", "crystal field", "tetrahedral", "octahedral", "ligand", "coordination",
        "orbital", "hybridisation", "hybridization", "vsepr", "molarity", "molality",
        "raoult", "buffer", "ph ", "acid", "base", "alkene", "alkane", "aldehyde", "ketone",
        "carbocation", "sn1", "sn2", "enthalpy", "gibbs", "electrochemistry", "nernst",
        "iupac", "bond order", "periodic", "oxidation", "reduction", "reagent", "mole",
    )
    phy_kw = (
        "physics", "velocity", "acceleration", "momentum", "newton", "force", "torque",
        "moment of inertia", "capacitor", "resistor", "ohm", "current", "voltage", "magnetic",
        "lenz", "faraday", "coulomb", "electric field", "focal length", "lens", "mirror",
        "diffraction", "photoelectric", "de broglie", "carnot", "pendulum", "gravitation",
        "escape velocity", "semiconductor", "logic gate", "diode", "wavelength", "frequency",
    )

    for kw in bio_kw:
        if kw in lower:
            scores["biology"] += 2 if kw == "biology" else 1
    for kw in chem_kw:
        if kw in lower:
            scores["chemistry"] += 2 if kw == "chemistry" else 1
    for kw in phy_kw:
        if kw in lower:
            scores["physics"] += 2 if kw == "physics" else 1

    best_subj, best_score = max(scores.items(), key=lambda kv: kv[1])
    if best_score > 0:
        return best_subj
    return fallback
