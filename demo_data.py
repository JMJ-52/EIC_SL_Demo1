"""Fresh demo state factories for the Streamlit session store."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from models import (
    ActivityLog,
    Equipment,
    LifecycleReview,
    LoginLog,
    Project,
    User,
)


def utc_timestamp() -> str:
    """Return a JSON-serializable UTC timestamp."""

    return datetime.now(timezone.utc).isoformat()


def make_demo_state() -> dict[str, object]:
    """Build a complete, unshared seed state for a new browser session."""

    timestamp = utc_timestamp()
    project_id = str(uuid4())
    approved_user_id = str(uuid4())
    pending_user_id = str(uuid4())
    rejected_user_id = str(uuid4())
    pending_review_id = str(uuid4())
    approved_review_id = str(uuid4())
    rejected_review_id = str(uuid4())

    project = Project(
        id=project_id,
        investment_code="EIC-DEMO-2026-01",
        project_name="제1변전소 EIC 교체 타당성 검토",
        status="reviewed",
        description="노후 EIC 제어반과 주변 설비의 교체 타당성을 검토하는 데모 프로젝트입니다.",
        created_at=timestamp,
        updated_at=timestamp,
        owner="데모 관리자",
        metadata={"site": "제1변전소", "budget_krw": 850000000, "priority": "high"},
    ).to_dict()

    equipment_rows = [
        Equipment(
            id=str(uuid4()), project_id=project_id, name="EIC 제어반 A", equipment_type="제어반",
            manufacturer="ABB", model_name="AC800M", status="reviewed",
            report={"replacement_score": 86, "technical_opinion": "교체 우선 검토", "risk": "high"},
        ).to_dict(),
        Equipment(
            id=str(uuid4()), project_id=project_id, name="인버터 B", equipment_type="인버터",
            manufacturer="SIEMENS", model_name="SINAMICS G120", status="reviewed",
            report={"replacement_score": 71, "technical_opinion": "예방 교체 검토", "risk": "medium"},
        ).to_dict(),
        Equipment(
            id=str(uuid4()), project_id=project_id, name="보호계전기 C", equipment_type="보호계전기",
            manufacturer="HITACHI", model_name="REL670", status="pending",
            report={"replacement_score": 54, "technical_opinion": "추가 자료 확인", "risk": "low"},
        ).to_dict(),
    ]

    users = [
        User(approved_user_id, "김승인", "approved@example.demo", "approved", "general", timestamp).to_dict(),
        User(pending_user_id, "이대기", "pending@example.demo", "pending", "general").to_dict(),
        User(rejected_user_id, "박반려", "rejected@example.demo", "rejected", "general", timestamp).to_dict(),
    ]
    reviews = [
        LifecycleReview(pending_review_id, "ABB", "ACS880", "Drive", "pending").to_dict(),
        LifecycleReview(approved_review_id, "SIEMENS", "S7-400", "PLC", "approved", "approved", timestamp).to_dict(),
        LifecycleReview(rejected_review_id, "HITACHI", "RX3i", "Controller", "rejected", "rejected", timestamp).to_dict(),
    ]
    # The pending review is reachable from the normal admin flow and names the
    # exact session equipment record that becomes exportable on approval.
    reviews[0]["project_id"] = project_id
    reviews[0]["equipment_id"] = equipment_rows[0]["id"]

    document_id = str(uuid4())

    return {
        "_session_store_initialized": True,
        "projects": {project_id: project},
        "equipment": {project_id: {row["id"]: row for row in equipment_rows}},
        "documents": {
            project_id: {
                document_id: {
                    "id": document_id, "project_id": project_id, "name": "현장조사표.pdf",
                    "content_type": "application/pdf", "size_bytes": 123456, "uploaded_at": timestamp,
                }
            }
        },
        "report_data": {
            project_id: {
                "summary": "주요 설비 2건은 교체 우선순위가 높습니다.",
                "total_equipment": len(equipment_rows),
                "recommended_replacements": 2,
                "estimated_budget_krw": 850000000,
            }
        },
        "report_versions": {},
        "users": {row["id"]: row for row in users},
        "lifecycle_reviews": {row["id"]: row for row in reviews},
        "login_logs": [LoginLog(str(uuid4()), approved_user_id, timestamp).to_dict()],
        "activity_logs": [
            ActivityLog(str(uuid4()), "seed_demo_state", timestamp, {"project_id": project_id}).to_dict()
        ],
        "statistics": {
            "projects_created": 4,
            "equipment_reviewed": 12,
            "approved_users": 1,
            "pending_reviews": 1,
            "estimated_replacement_budget_krw": 1250000000,
        },
        "chat_messages": {},
    }
