"""Content-bearing reported facts from a live Honcho derivation, with polarity controls."""
import importlib
from pathlib import Path

import pytest


@pytest.fixture
def checks(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "integrations/memory-stack"))
    return importlib.import_module("stack_checks")


@pytest.mark.parametrize("text", [
    "synthetic-user states that the project probe-canary permanently prefers cobalt blue.",
    "On November 9, 2026, synthetic-user stated that project probe-canary permanently prefers cobalt blue.",
    "Project probe-canary permanently prefers cobalt blue, as stated by synthetic-user.",
])
def test_reported_derived_fact_preserves_subject_and_positive_preference(checks, text):
    assert checks.semantic_match([{"content": text}], "probe-canary")


@pytest.mark.parametrize("text", [
    "synthetic-user asks whether the project probe-canary permanently prefers cobalt blue.",
    "synthetic-user falsely states that project probe-canary permanently prefers cobalt blue.",
    "synthetic-user states that project probe-canary does not prefer cobalt blue.",
    "synthetic-user states that project another-canary permanently prefers cobalt blue.",
    "synthetic-user states that project probe-canary permanently prefers cobalt blue. This preference was revoked.",
    "synthetic-user states that project probe-canary permanently prefers cobalt blue?",
    "synthetic-user states that project probe-canary permanently prefers cobalt blue, or maybe crimson red.",
])
def test_reported_fact_does_not_admit_questions_retractions_wrong_subject_or_ambiguity(checks, text):
    assert not checks.semantic_match([{"content": text}], "probe-canary")


def test_reported_positive_does_not_override_conflicting_preference(checks):
    documents = [
        "synthetic-user states that project probe-canary permanently prefers cobalt blue.",
        "synthetic-user states that project probe-canary permanently prefers crimson red.",
    ]
    assert not checks.semantic_match(documents, "probe-canary")
