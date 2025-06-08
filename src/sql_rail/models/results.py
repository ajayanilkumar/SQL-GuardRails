# sql_guardrail/models/results.py
from typing import List, Optional, Any
from pydantic import BaseModel, Field

class MatchSuggestion(BaseModel):
    suggested_value: str
    similarity_score: float = Field(..., ge=0.0, le=1.0)

class DistanceMetricAnalysis(BaseModel):
    metric_name: str
    query_parameter_value: str # The specific value analyzed (e.g., one item from an IN clause)
    suggestions: List[MatchSuggestion]

class WhereClauseConditionAnalysis(BaseModel):
    column_name: str
    operator: str
    raw_value_in_query: str # Original string representation of the value(s)
    analyses_by_metric: List[DistanceMetricAnalysis]

class GuardRailAnalysisResult(BaseModel):
    original_query: str
    analyzed_conditions: List[WhereClauseConditionAnalysis]
    warnings: Optional[List[str]] = None