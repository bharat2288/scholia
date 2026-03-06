"""
Scholia RLM Evaluation System
==============================
Empirical testing harness for RLM cost optimization dimensions.

Evaluates model selection, budget caps, reasoning effort, prompt templates,
and architectural changes against a test corpus with three-layer scoring:
  1. Programmatic fidelity checks (automated, exact)
  2. LLM-as-judge quality scores (automated, qualitative)
  3. Human review (gold standard, targeted)
"""
