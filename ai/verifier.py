"""Deterministic mathematical verification using SymPy."""

from __future__ import annotations

import re
from dataclasses import dataclass

import sympy as sp
from sympy.parsing.sympy_parser import (
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

_TRANSFORMATIONS = standard_transformations + (implicit_multiplication_application,)
_SAFE_LOCALS = {
    "x": sp.Symbol("x"),
    "y": sp.Symbol("y"),
    "z": sp.Symbol("z"),
    "t": sp.Symbol("t"),
    "v": sp.Symbol("v"),
    "u": sp.Symbol("u"),
    "a": sp.Symbol("a"),
    "m": sp.Symbol("m"),
    "g": sp.Symbol("g"),
    "pi": sp.pi,
    "e": sp.E,
    "sqrt": sp.sqrt,
    "sin": sp.sin,
    "cos": sp.cos,
    "tan": sp.tan,
    "log": sp.log,
    "ln": sp.log,
    "exp": sp.exp,
    "abs": sp.Abs,
}

# Match algebraic equations composed strictly of math tokens (not surrounding English prose)
_MATH_TOKEN = r"(?:sqrt|sin|cos|tan|log|ln|exp|abs|pi|\d+(?:\.\d+)?|[xyzvtamgue])"
_MATH_EXPR = rf"\(?\s*[\+\-]?\s*{_MATH_TOKEN}(?:\s*[\+\-\*/\^]?\s*\(?\s*{_MATH_TOKEN}\s*\)?){{0,8}}\s*\)?"
_EQUATION_RE = re.compile(rf"(?<![A-Za-z0-9_])({_MATH_EXPR}\s*=\s*{_MATH_EXPR})(?![A-Za-z0-9_])")

# Match pure arithmetic expressions like "(12 * 9.8) / 4" or "2^5 + 18"
_ARITHMETIC_RE = re.compile(
    r"(?<![A-Za-z0-9_])(\(?-?\d+(?:\.\d+)?(?:\s*[\+\-\*/\^]\s*\(?-?\d+(?:\.\d+)?\)?){1,6}\)?)(?![A-Za-z0-9_])"
)


@dataclass(frozen=True)
class VerificationResult:
    """Result of deterministic SymPy verification."""

    verified: bool
    summary: str
    expression: str = ""
    result: str = ""


def _normalize_math(raw: str) -> str:
    cleaned = raw.strip()
    cleaned = cleaned.replace("×", "*").replace("÷", "/").replace("−", "-")
    cleaned = cleaned.replace("^", "**")
    return cleaned


def verify_equation(equation_text: str) -> VerificationResult:
    """Solve a single-variable algebraic equation deterministically using SymPy."""
    normalized = _normalize_math(equation_text)
    if normalized.count("=") != 1:
        return VerificationResult(verified=False, summary="")

    lhs_str, rhs_str = (part.strip() for part in normalized.split("=", 1))
    if not lhs_str or not rhs_str:
        return VerificationResult(verified=False, summary="")

    try:
        lhs = parse_expr(lhs_str, local_dict=_SAFE_LOCALS, transformations=_TRANSFORMATIONS)
        rhs = parse_expr(rhs_str, local_dict=_SAFE_LOCALS, transformations=_TRANSFORMATIONS)
        eq = sp.Eq(lhs, rhs)
        symbols = sorted(eq.free_symbols, key=lambda s: s.name)
        if len(symbols) == 1:
            sym = symbols[0]
            solutions = sp.solve(eq, sym)
            if solutions:
                formatted = ", ".join(str(sp.simplify(sol)) for sol in solutions[:4])
                return VerificationResult(
                    verified=True,
                    expression=equation_text.strip(),
                    result=f"{sym} = {formatted}",
                    summary=f"Verified equation `{equation_text.strip()}` -> {sym} = {formatted}",
                )
        elif len(symbols) == 0:
            is_equal = bool(sp.simplify(lhs - rhs) == 0)
            return VerificationResult(
                verified=True,
                expression=equation_text.strip(),
                result=str(is_equal),
                summary=f"Verified identity `{equation_text.strip()}` -> {is_equal}",
            )
    except Exception:
        return VerificationResult(verified=False, summary="")

    return VerificationResult(verified=False, summary="")


def verify_arithmetic(expr_text: str) -> VerificationResult:
    """Evaluate a pure numerical arithmetic expression deterministically."""
    normalized = _normalize_math(expr_text)
    if re.search(r"[A-Za-z_]", normalized):
        return VerificationResult(verified=False, summary="")
    try:
        expr = parse_expr(normalized, local_dict={}, transformations=_TRANSFORMATIONS)
        simplified = sp.simplify(expr)
        numeric = sp.N(simplified, 6)
        if simplified.is_Integer:
            val_str = str(simplified)
        else:
            val_str = f"{simplified} (≈ {float(numeric):.4g})"
        return VerificationResult(
            verified=True,
            expression=expr_text.strip(),
            result=val_str,
            summary=f"Verified calculation `{expr_text.strip()}` = {val_str}",
        )
    except Exception:
        return VerificationResult(verified=False, summary="")


def extract_and_verify(question_text: str) -> VerificationResult:
    """Scan a student's question for equations or arithmetic and verify with SymPy."""
    if not question_text or len(question_text) > 2000:
        return VerificationResult(verified=False, summary="")

    notes: list[str] = []
    seen: set[str] = set()

    for match in _EQUATION_RE.finditer(question_text):
        candidate = match.group(1).strip()
        if candidate in seen or len(candidate) < 3:
            continue
        res = verify_equation(candidate)
        if res.verified:
            seen.add(candidate)
            notes.append(res.summary)
            if len(notes) >= 2:
                break

    if not notes:
        for match in _ARITHMETIC_RE.finditer(question_text):
            candidate = match.group(1).strip()
            if candidate in seen:
                continue
            res = verify_arithmetic(candidate)
            if res.verified:
                seen.add(candidate)
                notes.append(res.summary)
                if len(notes) >= 2:
                    break

    if not notes:
        return VerificationResult(verified=False, summary="")

    return VerificationResult(
        verified=True,
        summary="\n".join(notes),
        result=notes[0],
    )
