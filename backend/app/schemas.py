"""Pydantic request schemas (responses are documented dicts built by the services)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.simulator.whatif import SCENARIO_TYPES


class LoginIn(BaseModel):
    username: str = Field(..., min_length=2, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class DemoLoginIn(BaseModel):
    username: str


class ScenarioIn(BaseModel):
    type: str
    params: dict = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def known(cls, v):
        if v not in SCENARIO_TYPES:
            raise ValueError(f"unknown scenario type; expected one of {SCENARIO_TYPES}")
        return v


class SimulateIn(BaseModel):
    scenarios: list[ScenarioIn] = Field(..., min_length=1, max_length=6)
    horizon_months: int | None = Field(default=None, ge=1, le=12)
    preset: str | None = None


class CounterfactualIn(BaseModel):
    product_id: str


class OfferIn(BaseModel):
    user_id: str
    product_id: str
    interest_rate: float | None = Field(default=None, gt=0, lt=60)
    amount: float | None = Field(default=None, gt=0)
    expiry_days: int | None = Field(default=None, ge=1, le=90)
    message: str | None = Field(default=None, max_length=500)


class BulkOfferIn(BaseModel):
    user_ids: list[str] = Field(..., min_length=1, max_length=500)
    product_id: str
    interest_rate: float | None = Field(default=None, gt=0, lt=60)
    amount: float | None = Field(default=None, gt=0)
    expiry_days: int | None = Field(default=None, ge=1, le=90)
    message: str | None = Field(default=None, max_length=500)
    campaign_name: str | None = Field(default=None, max_length=120)


class OfferResponseIn(BaseModel):
    action: Literal["accept", "reject", "view"]


class ApplicationIn(BaseModel):
    product_id: str
    offer_id: str | None = None
    requested_amount: float | None = Field(default=None, gt=0)
