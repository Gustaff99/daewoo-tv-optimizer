"""Execution engine (FASE 4): dry-run planning over verified profiles.

The planner turns a conclusive device identity + a profile that allows
actions + a real package inventory into an explicit, reversible,
dry-run-by-default plan. It never executes anything and never produces
a plan for non-conclusive identities or default-deny profiles.
"""
from .planner import (
    ExecutionPlan,
    PlanAction,
    PlanError,
    build_plan,
    render_plan,
)

__all__ = ["ExecutionPlan", "PlanAction", "PlanError", "build_plan", "render_plan"]
