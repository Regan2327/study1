"""Spaced-repetition retention model.

Each card has a stability S (days until recall probability falls to ~37%) and a
last-review time. Recall probability follows the forgetting curve:

    R(t) = exp(-t / S)

Review priority is computed as a dot product between a user recall vector and a
decay weight matrix (priority = V . W^T). Rows of V are per-card features; rows of
W are per-card weights over those features. The row-wise dot product gives a score
that is high when a card is both likely forgotten and historically hard.

Features for each card (the columns of V):
    0: predicted forgetting   1 - R(t)
    1: difficulty             normalized 0..1 (higher = harder)
    2: lapse rate            fraction of recent reviews that failed
    3: overdue ratio          max(0, t - S) / S
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

FEATURE_COUNT = 4
DEFAULT_STABILITY_DAYS = 1.0
MIN_STABILITY_DAYS = 0.1
MAX_STABILITY_DAYS = 3650.0
MIN_DIFFICULTY = 0.0
MAX_DIFFICULTY = 1.0


def recall_probability(elapsed_days: float, stability_days: float) -> float:
    """Predicted probability of recall after elapsed_days, given stability."""
    if elapsed_days <= 0:
        return 1.0
    stability = max(stability_days, MIN_STABILITY_DAYS)
    return math.exp(-elapsed_days / stability)


@dataclass
class CardState:
    """Persistent scheduling state for one card."""

    card_id: int
    stability_days: float = DEFAULT_STABILITY_DAYS
    difficulty: float = 0.5
    last_reviewed: datetime | None = None
    recent_results: list[bool] = field(default_factory=list)  # True = recalled

    def __post_init__(self) -> None:
        self.stability_days = _clamp(self.stability_days, MIN_STABILITY_DAYS, MAX_STABILITY_DAYS)
        self.difficulty = _clamp(self.difficulty, MIN_DIFFICULTY, MAX_DIFFICULTY)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def elapsed_days(card: CardState, now: datetime | None = None) -> float:
    """Days since the card was last reviewed. Never-reviewed cards count as 0."""
    if card.last_reviewed is None:
        return 0.0
    now = now or datetime.now(timezone.utc)
    last = card.last_reviewed
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return max((now - last).total_seconds() / 86400.0, 0.0)


def build_feature_matrix(cards: list[CardState], now: datetime | None = None) -> np.ndarray:
    """Build V, an (n_cards x FEATURE_COUNT) matrix of per-card features."""
    rows = np.zeros((len(cards), FEATURE_COUNT), dtype=float)
    for i, card in enumerate(cards):
        t = elapsed_days(card, now)
        retention = recall_probability(t, card.stability_days)
        overdue = max(0.0, t - card.stability_days) / card.stability_days

        lapses = (
            sum(1 for ok in card.recent_results if not ok) / len(card.recent_results)
            if card.recent_results
            else 0.0
        )
        rows[i] = (1.0 - retention, card.difficulty, lapses, min(overdue, 5.0) / 5.0)
    return rows


def build_weight_matrix(n_cards: int, weights: np.ndarray | None = None) -> np.ndarray:
    """Build W, an (n_cards x FEATURE_COUNT) weight matrix.

    If a single weight vector of length FEATURE_COUNT is given, it is broadcast to
    every card. The default favors forgetting risk, then difficulty.
    """
    default = np.array([0.5, 0.2, 0.2, 0.1])
    base = default if weights is None else np.asarray(weights, dtype=float)
    if base.shape != (FEATURE_COUNT,):
        raise ValueError(f"weights must have length {FEATURE_COUNT}, got {base.shape}")
    return np.tile(base, (n_cards, 1))


def review_priorities(
    cards: list[CardState],
    now: datetime | None = None,
    weights: np.ndarray | None = None,
) -> np.ndarray:
    """Return a priority score per card: the diagonal of V . W^T.

    Only the diagonal is needed (card i paired with its own weights), so this
    computes the row-wise dot product directly instead of the full n x n product.
    """
    if not cards:
        return np.zeros(0, dtype=float)
    V = build_feature_matrix(cards, now)
    W = build_weight_matrix(len(cards), weights)
    return np.einsum("ij,ij->i", V, W)


def schedule_order(
    cards: list[CardState],
    now: datetime | None = None,
    weights: np.ndarray | None = None,
) -> list[CardState]:
    """Cards sorted from highest to lowest review priority."""
    scores = review_priorities(cards, now, weights)
    order = np.argsort(-scores, kind="stable")
    return [cards[i] for i in order]


def apply_review(card: CardState, recalled: bool, now: datetime | None = None) -> CardState:
    """Update a card's stability and difficulty after a review.

    Successful recall grows stability, more so when the card was close to being
    forgotten (a "desirable difficulty"). A failed recall shrinks stability and
    raises difficulty. Returns the same card object for convenience.
    """
    now = now or datetime.now(timezone.utc)
    retention_before = recall_probability(elapsed_days(card, now), card.stability_days)

    if recalled:
        growth = 1.0 + (1.0 - retention_before) * 2.0
        card.stability_days *= growth
        card.difficulty -= 0.05
    else:
        card.stability_days = max(card.stability_days * 0.3, MIN_STABILITY_DAYS)
        card.difficulty += 0.1

    card.difficulty = _clamp(card.difficulty, MIN_DIFFICULTY, MAX_DIFFICULTY)
    card.stability_days = _clamp(card.stability_days, MIN_STABILITY_DAYS, MAX_STABILITY_DAYS)
    card.last_reviewed = now
    card.recent_results = (card.recent_results + [recalled])[-10:]
    return card
