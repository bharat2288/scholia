"""
Council Service
===============
Multi-model LLM council for AI-powered document analysis.

Based on Karpathy's llm-council concept:
- Multiple LLMs deliberate independently
- Chairman synthesizes perspectives
"""

from .service import CouncilService
from .config import COUNCIL_CONFIG, PRICING, get_available_models

__all__ = ["CouncilService", "COUNCIL_CONFIG", "PRICING", "get_available_models"]
