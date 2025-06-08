# sql_guardrail/__init__.py
"""
SQL Guardrail Module: Analyze and suggest corrections for SQL query parameters.
"""
__version__ = "0.0.8"

from .core.sql_rail import SQLRail
from .core.distance_metrics import (
    Distance,
    LevenshteinDistance,
    # SemanticDistance,
    JaroWinklerSimilarity,
    TokenSetRatio,
)
from .models.results import (
    MatchSuggestion,
    DistanceMetricAnalysis,
    WhereClauseConditionAnalysis,
    GuardRailAnalysisResult,
)

__all__ = [
    "SQLRail",
    "Distance",
    "LevenshteinDistance",
    # "SemanticDistance",
    "JaroWinklerSimilarity",
    "TokenSetRatio",
    "MatchSuggestion",
    "DistanceMetricAnalysis",
    "WhereClauseConditionAnalysis",
    "GuardRailAnalysisResult",
]

# Optional: Configure logging
import logging
logging.getLogger(__name__).addHandler(logging.NullHandler())