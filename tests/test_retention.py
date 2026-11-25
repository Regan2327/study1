from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from synaptiq.model.retention import (
    CardState,
    apply_review,
    recall_probability,
    review_priorities,
    schedule_order,
)


def test_recall_probability_decays_with_elapsed_time() -> None:
    assert recall_probability(0, 1) == 1
    assert recall_probability(1, 1) == pytest.approx(np.exp(-1))


def test_failed_review_reduces_stability_and_increases_difficulty() -> None:
    card = CardState(card_id=1)
    reviewed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    result = apply_review(card, recalled=False, now=reviewed_at)

    assert result is card
    assert card.stability_days == 0.3
    assert card.difficulty == 0.6
    assert card.last_reviewed == reviewed_at
    assert card.recent_results == [False]


def test_schedule_prioritizes_more_overdue_card() -> None:
    now = datetime(2026, 1, 10, tzinfo=timezone.utc)
    recent = CardState(card_id=1, last_reviewed=now - timedelta(hours=1))
    overdue = CardState(card_id=2, last_reviewed=now - timedelta(days=5))

    assert review_priorities([recent, overdue], now)[1] > review_priorities(
        [recent, overdue], now
    )[0]
    assert [card.card_id for card in schedule_order([recent, overdue], now)] == [2, 1]
