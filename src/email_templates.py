from __future__ import annotations

from datetime import date
from typing import Any


TEMPLATE_TYPES = [
    "Follow-up Email",
    "Interview Thank-you Email",
    "Recruiter Outreach Email",
    "Rejection Acknowledgement Email",
]


def suggest_template_type(application: dict[str, Any]) -> str:
    status = str(application.get("status", ""))
    if status == "Interview Scheduled":
        return "Interview Thank-you Email"
    if status == "Rejected":
        return "Rejection Acknowledgement Email"
    if status in {"Saved", "No Response"}:
        return "Recruiter Outreach Email"
    return "Follow-up Email"


def generate_email_template(
    application: dict[str, Any],
    template_type: str,
    recipient_name: str = "",
    sender_name: str = "Yibo Zhang",
    today: date | None = None,
) -> dict[str, str]:
    current_date = today or date.today()
    context = {
        "company": _value(application, "company", "your company"),
        "role": _value(application, "role", "the role"),
        "recipient": recipient_name.strip() or _recipient_from_contact(application.get("contact", "")),
        "sender": sender_name.strip() or "Yibo Zhang",
        "date": current_date.isoformat(),
        "application_date": str(application.get("application_date", "") or "").strip(),
    }

    if template_type == "Interview Thank-you Email":
        return _interview_thank_you(context)
    if template_type == "Recruiter Outreach Email":
        return _recruiter_outreach(context)
    if template_type == "Rejection Acknowledgement Email":
        return _rejection_acknowledgement(context)
    return _follow_up(context)


def _follow_up(context: dict[str, str]) -> dict[str, str]:
    submitted_phrase = (
        f" submitted on {context['application_date']}"
        if context["application_date"]
        else ""
    )
    return {
        "subject": f"Follow-up on {context['role']} application",
        "body": (
            f"Dear {context['recipient']},\n\n"
            f"I hope you are doing well. I wanted to follow up on my application for the "
            f"{context['role']} position at {context['company']}{submitted_phrase}.\n\n"
            "I remain very interested in the opportunity and would be grateful for any update "
            "you could share regarding the next steps.\n\n"
            "Thank you for your time and consideration.\n\n"
            f"Best regards,\n{context['sender']}"
        ),
    }


def _interview_thank_you(context: dict[str, str]) -> dict[str, str]:
    return {
        "subject": f"Thank you for the interview - {context['role']}",
        "body": (
            f"Dear {context['recipient']},\n\n"
            f"Thank you for taking the time to speak with me about the {context['role']} "
            f"position at {context['company']}.\n\n"
            "I appreciated learning more about the team, the role, and the next steps. "
            "The conversation further strengthened my interest in the opportunity.\n\n"
            "Please let me know if I can provide any additional information.\n\n"
            f"Best regards,\n{context['sender']}"
        ),
    }


def _recruiter_outreach(context: dict[str, str]) -> dict[str, str]:
    return {
        "subject": f"Interest in {context['role']} opportunities at {context['company']}",
        "body": (
            f"Dear {context['recipient']},\n\n"
            f"I am reaching out because I am interested in the {context['role']} opportunity "
            f"at {context['company']}.\n\n"
            "My background combines quality assurance, automation, and technical operations, "
            "and I would be happy to share more context about my experience if it is relevant "
            "for the team.\n\n"
            "Thank you for your time. I would appreciate the chance to discuss whether my "
            "profile could be a good fit.\n\n"
            f"Best regards,\n{context['sender']}"
        ),
    }


def _rejection_acknowledgement(context: dict[str, str]) -> dict[str, str]:
    return {
        "subject": f"Thank you for the update - {context['role']}",
        "body": (
            f"Dear {context['recipient']},\n\n"
            f"Thank you for letting me know about the outcome of my application for the "
            f"{context['role']} position at {context['company']}.\n\n"
            "Although I am disappointed, I appreciate the time taken to review my application. "
            "I would be grateful if you could keep my profile in mind for future opportunities "
            "that may be a closer match.\n\n"
            f"Best regards,\n{context['sender']}"
        ),
    }


def _recipient_from_contact(contact: object) -> str:
    text = str(contact or "").strip()
    if not text:
        return "Hiring Team"
    if "<" in text:
        text = text.split("<", 1)[0].strip()
    if "@" in text:
        return "Hiring Team"
    return text or "Hiring Team"


def _value(application: dict[str, Any], key: str, fallback: str) -> str:
    value = str(application.get(key, "") or "").strip()
    return value or fallback
