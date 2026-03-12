from __future__ import annotations

from app.domain.roles import ROLE_ORDER

TIER_SCORES: dict[str, float] = {
    "S+": 1.0,
    "S": 0.92,
    "A+": 0.84,
    "A": 0.76,
    "A-": 0.72,
    "B+": 0.68,
    "B": 0.58,
    "B-": 0.52,
    "C": 0.4,
    "D": 0.2,
}

SUPPORTED_ROLES: list[str] = ROLE_ORDER

ROLE_SCENARIO_LIMIT: int = 6
ROLE_SCENARIO_TEMPERATURE: float = 2.5

# Confidence thresholds for sample sizes
SAMPLE_THRESHOLD_IGNORE: int = 25
# Coverage shrinkage prior - reduced from 300 because delta is already shrunk via MATCHUP_SHRINKAGE_PRIOR
RELATION_SHRINKAGE_PRIOR_GAMES: float = 100.0

# Bayesian shrinkage priors for delta normalization (applied before tanh to prevent noisy signals)
MATCHUP_SHRINKAGE_PRIOR: float = 200.0
SYNERGY_SHRINKAGE_PRIOR: float = 150.0

COUNTER_BUDGET_BASE: float = 0.07
COUNTER_BUDGET_PER_ENEMY: float = 0.07
COUNTER_BUDGET_CAP: float = 0.42

SYNERGY_BUDGET_BASE: float = 0.03
SYNERGY_BUDGET_PER_ALLY: float = 0.03
SYNERGY_BUDGET_CAP: float = 0.15

# Late-draft counter boost: as more champions are visible, counter budget scales up by this factor
LATE_DRAFT_COUNTER_BOOST_MAX: float = 0.25

COUNTER_EDGE_SCALE: float = 7.0
SYNERGY_EDGE_SCALE: float = 10.0

# Evidence multiplier parameters
EVIDENCE_BASE_MULTIPLIER: float = 0.7
EVIDENCE_COVERAGE_WEIGHT: float = 0.3

# Low-sample tier penalty thresholds
TIER_GAMES_HIGH: int = 5000
TIER_GAMES_MEDIUM: int = 2000
TIER_PENALTY_MEDIUM: float = 0.05
TIER_PENALTY_LOW: float = 0.10

# PBI normalization scale - PBI values rarely exceed 30 in practice
PBI_NORMALIZATION_SCALE: float = 30.0

# Role fit thresholds (kept for backward compatibility, no longer used in scoring)
ROLE_FIT_HIGH_PICK_RATE: float = 5.0
ROLE_FIT_MEDIUM_PICK_RATE: float = 1.0

# Lane proximity weights: how much a matchup/synergy matters based on role pair
# Same-lane = 1.0, adjacent = ~0.85, distant = ~0.55
LANE_PROXIMITY: dict[tuple[str, str], float] = {
    ("top", "top"): 1.0,
    ("top", "jungle"): 0.85,
    ("top", "middle"): 0.65,
    ("top", "bottom"): 0.50,
    ("top", "support"): 0.55,
    ("jungle", "jungle"): 1.0,
    ("jungle", "top"): 0.85,
    ("jungle", "middle"): 0.85,
    ("jungle", "bottom"): 0.80,
    ("jungle", "support"): 0.80,
    ("middle", "middle"): 1.0,
    ("middle", "jungle"): 0.85,
    ("middle", "top"): 0.65,
    ("middle", "bottom"): 0.60,
    ("middle", "support"): 0.65,
    ("bottom", "bottom"): 1.0,
    ("bottom", "support"): 0.90,
    ("bottom", "jungle"): 0.80,
    ("bottom", "middle"): 0.60,
    ("bottom", "top"): 0.50,
    ("support", "support"): 1.0,
    ("support", "bottom"): 0.90,
    ("support", "jungle"): 0.80,
    ("support", "middle"): 0.65,
    ("support", "top"): 0.55,
}

# Confidence calculation weights (picks)
PICK_CONFIDENCE_BASE: float = 0.18
PICK_CONFIDENCE_GAMES_MAX: float = 0.35
PICK_CONFIDENCE_GAMES_DIVISOR: float = 25000.0
PICK_CONFIDENCE_EVIDENCE_WEIGHT: float = 0.18
PICK_CONFIDENCE_CERTAINTY_WEIGHT: float = 0.14
PICK_CONFIDENCE_SAMPLE_WEIGHT: float = 0.15

# Confidence calculation weights (bans)
BAN_CONFIDENCE_BASE: float = 0.24
BAN_CONFIDENCE_GAMES_MAX: float = 0.30
BAN_CONFIDENCE_GAMES_DIVISOR: float = 25000.0
BAN_CONFIDENCE_EVIDENCE_WEIGHT: float = 0.14
BAN_CONFIDENCE_CERTAINTY_WEIGHT: float = 0.12
BAN_CONFIDENCE_SAMPLE_WEIGHT: float = 0.14

# Confidence caps
CONFIDENCE_CAP_PATCH_MISMATCH: float = 0.55
CONFIDENCE_CAP_INCOMPLETE_SCOPE: float = 0.72

# Thin evidence penalty multiplier
THIN_EVIDENCE_MULTIPLIER: float = 0.9
THIN_EVIDENCE_GAME_THRESHOLD: int = 100

# Ban score static weights
PREDRAFT_WEIGHT_TIER_RANK: float = 0.45
PREDRAFT_WEIGHT_TIER: float = 0.25
PREDRAFT_WEIGHT_PBI: float = 0.15
PREDRAFT_WEIGHT_ROLE_FIT: float = 0.15

BAN_WEIGHT_TIER: float = 0.34
BAN_WEIGHT_ROLE_LIKELIHOOD: float = 0.24
BAN_WEIGHT_PICK_RATE: float = 0.24
BAN_WEIGHT_BAN_RATE: float = 0.18
BAN_WEIGHT_COUNTER: float = 0.16
BAN_WEIGHT_SYNERGY: float = 0.08

DISPLAY_BAND_ELITE: float = 75.0
DISPLAY_BAND_STRONG: float = 60.0
DISPLAY_BAND_SITUATIONAL: float = 45.0

# Role inference ambiguity thresholds
ROLE_AMBIGUITY_TOP_THRESHOLD: float = 0.55
ROLE_AMBIGUITY_GAP_THRESHOLD: float = 0.10
ROLE_AMBIGUITY_PENALTY: float = 0.85
