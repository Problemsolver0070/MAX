# src/max/comm/injection_scanner.py
"""Prompt injection scanner — pattern-based trust scoring for inbound messages."""

from __future__ import annotations

import re

from max.comm.models import InjectionScanResult

# Each pattern: (compiled regex, category name, score penalty)
_PATTERNS: list[tuple[re.Pattern[str], str, float]] = [
    # Role override attempts
    (
        re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
        "role_override",
        0.6,
    ),
    (
        re.compile(r"you\s+are\s+now\b", re.IGNORECASE),
        "role_override",
        0.6,
    ),
    (
        re.compile(r"system\s+prompt\s*:", re.IGNORECASE),
        "role_override",
        0.5,
    ),
    (
        re.compile(r"\bact\s+as\b", re.IGNORECASE),
        "role_override",
        0.5,
    ),
    (
        re.compile(r"forget\s+(all\s+)?your\s+instructions", re.IGNORECASE),
        "role_override",
        0.6,
    ),
    # Delimiter injection
    (
        re.compile(r"</?(system|user_message|assistant|tool)\s*>", re.IGNORECASE),
        "delimiter_injection",
        0.3,
    ),
    (
        re.compile(r"```\s*\n\s*</?system", re.IGNORECASE),
        "delimiter_injection",
        0.3,
    ),
    # Instruction smuggling
    (
        re.compile(r"\bIMPORTANT\s*:", re.IGNORECASE),
        "instruction_smuggling",
        0.35,
    ),
    (
        re.compile(r"\bCRITICAL\s*:", re.IGNORECASE),
        "instruction_smuggling",
        0.35,
    ),
    (
        re.compile(r"\bOVERRIDE\s*:", re.IGNORECASE),
        "instruction_smuggling",
        0.35,
    ),
    (
        re.compile(r"\bADMIN\s*:", re.IGNORECASE),
        "instruction_smuggling",
        0.35,
    ),
]


class PromptInjectionScanner:
    """Scans inbound text for prompt injection patterns.

    Does NOT block messages — flags them with a trust_score and found patterns.
    """

    def scan(self, text: str) -> InjectionScanResult:
        if not text:
            return InjectionScanResult()

        total_penalty = 0.0
        found_categories: set[str] = set()

        for pattern, category, penalty in _PATTERNS:
            if pattern.search(text):
                total_penalty += penalty
                found_categories.add(category)

        trust_score = max(0.0, 1.0 - total_penalty)
        return InjectionScanResult(
            trust_score=round(trust_score, 2),
            patterns_found=sorted(found_categories),
            is_suspicious=trust_score < 0.5,
        )
