"""Typed, JSON-friendly domain records for the session-only demo."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


PROJECT_STATUSES = frozenset({"draft", "reviewed", "confirmed", "on_hold"})
USER_STATUSES = frozenset({"pending", "approved", "rejected"})
REVIEW_STATUSES = frozenset({"pending", "approved", "rejected"})


@dataclass
class Project:
    id: str
    investment_code: str
    project_name: str
    status: str = "draft"
    description: str = ""
    created_at: str = ""
    updated_at: str = ""
    owner: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Equipment:
    id: str
    project_id: str
    name: str
    equipment_type: str = ""
    manufacturer: str = ""
    model_name: str = ""
    status: str = "pending"
    report: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class User:
    id: str
    name: str
    email: str
    status: str = "pending"
    role: str = "general"
    decided_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LifecycleReview:
    id: str
    supplier: str
    model_name: str
    target: str
    status: str = "pending"
    decision: str | None = None
    decided_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ActivityLog:
    id: str
    action: str
    timestamp: str
    details: dict[str, Any] = field(default_factory=dict)
    actor: str = "system"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LoginLog:
    id: str
    user_id: str
    timestamp: str
    outcome: str = "success"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

