from __future__ import annotations

from datetime import date
from typing import Any

from src.job_post_parser import analyze_job_post, build_job_post_notes


def build_job_post_application_draft(
    job_text: str,
    source_url: str = "",
    *,
    today: date | None = None,
) -> dict[str, Any]:
    saved_date = today or date.today()
    analysis = analyze_job_post(job_text=job_text, source_url=source_url)
    details = analysis["details"]
    payload = {
        "company": details.get("company", ""),
        "role": details.get("role", ""),
        "location": details.get("location", ""),
        "application_date": saved_date.isoformat(),
        "status": analysis["status"],
        "source_link": details.get("source_link", ""),
        "contact": details.get("contact", ""),
        "notes": build_job_post_notes(analysis),
        "rejection_reason": "",
        "next_action": analysis["next_action"],
        "follow_up_date": analysis["follow_up_date"],
    }
    return {
        "analysis": analysis,
        "payload": payload,
        "can_create": bool(payload["company"] and payload["role"]),
    }
