"""Switchable cost models. Both implement cost.base.CostModel; pick one with eva.cost.model."""
from marswalk.cost.base import CostModel, get_cost_model

__all__ = ["CostModel", "get_cost_model"]
