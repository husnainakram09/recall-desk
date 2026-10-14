
"""Policy for simulated human review decisions.

This module does not authenticate pharmacists or authorize
physical medicine-handling actions.
"""

from enum import Enum

from contracts import MatchState


class ReviewAction(str, Enum):
    ACKNOWLEDGE_CANDIDATE = "acknowledge_candidate"
    REQUEST_EVIDENCE = "request_evidence"
    ESCALATE_CONFLICT = "escalate_conflict"
    RECORD_NONMATCH = "record_nonmatch_for_this_notice"


_ALLOWED = {
    MatchState.EXACT_CANDIDATE: ReviewAction.ACKNOWLEDGE_CANDIDATE,
    MatchState.NEEDS_EVIDENCE: ReviewAction.REQUEST_EVIDENCE,
    MatchState.CONFLICTING_IDENTIFIERS: ReviewAction.ESCALATE_CONFLICT,
    MatchState.NOT_MATCHED: ReviewAction.RECORD_NONMATCH,
}


def validate_review_action(
    state: MatchState,
    action: ReviewAction,
    role: str,
) -> None:
    """Reject unsupported or unauthorized demo decisions."""
    if role != "Pharmacist":
        raise PermissionError(
            "Only the simulated Pharmacist role can review."
        )

    if not isinstance(state, MatchState):
        raise TypeError("state must be a MatchState.")

    if not isinstance(action, ReviewAction):
        raise TypeError("action must be a ReviewAction.")

    if _ALLOWED.get(state) is not action:
        raise ValueError(
            f"Decision {action.value} is invalid for {state.value}."
        )
