"""Tests for SymPy deterministic mathematical verifier."""

from __future__ import annotations

import unittest

from ai.verifier import extract_and_verify, verify_arithmetic, verify_equation


class TestMathVerifier(unittest.TestCase):
    def test_linear_equation(self) -> None:
        res = verify_equation("2x + 6 = 14")
        self.assertTrue(res.verified)
        self.assertEqual(res.result, "x = 4")

    def test_quadratic_equation(self) -> None:
        res = verify_equation("x^2 - 5x + 6 = 0")
        self.assertTrue(res.verified)
        self.assertIn("2", res.result)
        self.assertIn("3", res.result)

    def test_arithmetic_expression(self) -> None:
        res = verify_arithmetic("(20 * 5) / 4")
        self.assertTrue(res.verified)
        self.assertEqual(res.result, "25")

    def test_extract_and_verify_from_word_problem(self) -> None:
        res = extract_and_verify("Solve the equation 3x - 9 = 0 for x.")
        self.assertTrue(res.verified)
        self.assertIn("x = 3", res.summary)

    def test_non_math_text_returns_unverified(self) -> None:
        res = extract_and_verify("Explain the role of cristae in mitochondria.")
        self.assertFalse(res.verified)


if __name__ == "__main__":
    unittest.main()
