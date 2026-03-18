"""Shared constants and utilities for rune and build recommenders."""

LANE_OPPONENT_WEIGHT = 4.0
JUNGLE_WEIGHT = 2.0
DEFAULT_WEIGHT = 1.0

MIN_GAMES_PER_MATCHUP = 20


def position_weight(player_role: str, opponent_role: str) -> float:
    """Determine how much an opponent's matchup should weigh in decisions."""
    if not player_role or not opponent_role:
        return DEFAULT_WEIGHT
    if player_role == opponent_role:
        return LANE_OPPONENT_WEIGHT
    if opponent_role == "jungle":
        return JUNGLE_WEIGHT
    if player_role == "jungle":
        return JUNGLE_WEIGHT
    return DEFAULT_WEIGHT
