
"""Tests for the simulated review-decision policy."""

import pytest

from contracts import MatchState
from storage.review_policy import (
    ReviewAction,
    validate_review_action,
)


@pytest.mark.parametrize(
    ("state", "action"),
    [
        (
            MatchState.EXACT_CANDIDATE,
            ReviewAction.ACKNOWLEDGE_CANDIDATE,
        ),
        (
            MatchState.NEEDS_EVIDENCE,
            ReviewAction.REQUEST_EVIDENCE,
        ),
        (
            MatchState.CONFLICTING_IDENTIFIERS,
            ReviewAction.ESCALATE_CONFLICT,
        ),
        (
            MatchState.NOT_MATCHED,
            ReviewAction.RECORD_NONMATCH,
        ),
    ],
)
def test_valid_review_decisions(state, action):
    validate_review_action(state, action, "Pharmacist")


@pytest.mark.parametrize(
    ("state", "action"),
    [
        (
            MatchState.EXACT_CANDIDATE,
            ReviewAction.RECORD_NONMATCH,
        ),
        (
            MatchState.NEEDS_EVIDENCE,
            ReviewAction.ACKNOWLEDGE_CANDIDATE,
        ),
        (
            MatchState.CONFLICTING_IDENTIFIERS,
            ReviewAction.ACKNOWLEDGE_CANDIDATE,
        ),
    ],
)
def test_invalid_decisions_rejected(state, action):
    with pytest.raises(ValueError):
        validate_review_action(state, action, "Pharmacist")


def test_incomplete_evidence_blocks_review():
    with pytest.raises(ValueError):
        validate_review_action(
            MatchState.CHECK_INCOMPLETE,
            ReviewAction.ACKNOWLEDGE_CANDIDATE,
            "Pharmacist",
        )


def test_technician_cannot_record_review():
    with pytest.raises(PermissionError):
        validate_review_action(
            MatchState.EXACT_CANDIDATE,
            ReviewAction.ACKNOWLEDGE_CANDIDATE,
            "Technician",
        )
