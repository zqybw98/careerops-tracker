from __future__ import annotations

from datetime import date
from typing import Any

TEMPLATE_TYPES = [
    "Follow-up Email",
    "Interview Thank-you Email",
    "Recruiter Outreach Email",
    "Rejection Acknowledgement Email",
]

TEMPLATE_LANGUAGES = ["English", "German", "Chinese"]


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
    language: str = "English",
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

    normalized_language = language if language in TEMPLATE_LANGUAGES else "English"
    if normalized_language == "German":
        return _generate_german_template(context, template_type)
    if normalized_language == "Chinese":
        return _generate_chinese_template(context, template_type)
    return _generate_english_template(context, template_type)


def _generate_english_template(context: dict[str, str], template_type: str) -> dict[str, str]:
    if template_type == "Interview Thank-you Email":
        return _interview_thank_you(context)
    if template_type == "Recruiter Outreach Email":
        return _recruiter_outreach(context)
    if template_type == "Rejection Acknowledgement Email":
        return _rejection_acknowledgement(context)
    return _follow_up(context)


def _generate_german_template(context: dict[str, str], template_type: str) -> dict[str, str]:
    if template_type == "Interview Thank-you Email":
        return {
            "subject": f"Vielen Dank fuer das Gespraech - {context['role']}",
            "body": (
                f"Guten Tag {context['recipient']},\n\n"
                f"vielen Dank fuer das freundliche Gespraech zur Position {context['role']} "
                f"bei {context['company']}.\n\n"
                "Ich habe mich sehr ueber die Einblicke in das Team, die Aufgaben und die "
                "naechsten Schritte gefreut. Das Gespraech hat mein Interesse an der Position "
                "weiter bestaerkt.\n\n"
                "Gerne reiche ich bei Bedarf weitere Informationen nach.\n\n"
                f"Mit freundlichen Gruessen\n{context['sender']}"
            ),
        }
    if template_type == "Recruiter Outreach Email":
        return {
            "subject": f"Interesse an {context['role']} bei {context['company']}",
            "body": (
                f"Guten Tag {context['recipient']},\n\n"
                f"ich interessiere mich fuer die Position {context['role']} bei {context['company']} "
                "und wuerde mich gerne kurz vorstellen.\n\n"
                "Mein Profil verbindet Qualitaetssicherung, Automatisierung und technische "
                "Operations-Themen. Gerne teile ich weitere Informationen, falls mein Hintergrund "
                "fuer Ihr Team relevant ist.\n\n"
                "Vielen Dank fuer Ihre Zeit. Ich freue mich ueber eine kurze Rueckmeldung.\n\n"
                f"Mit freundlichen Gruessen\n{context['sender']}"
            ),
        }
    if template_type == "Rejection Acknowledgement Email":
        return {
            "subject": f"Vielen Dank fuer Ihre Rueckmeldung - {context['role']}",
            "body": (
                f"Guten Tag {context['recipient']},\n\n"
                f"vielen Dank fuer Ihre Rueckmeldung zu meiner Bewerbung fuer die Position "
                f"{context['role']} bei {context['company']}.\n\n"
                "Auch wenn ich die Entscheidung bedauere, danke ich Ihnen fuer die Pruefung "
                "meiner Unterlagen. Ich wuerde mich freuen, wenn Sie mein Profil fuer zukuenftige "
                "passende Positionen beruecksichtigen.\n\n"
                f"Mit freundlichen Gruessen\n{context['sender']}"
            ),
        }
    submitted_phrase = f" vom {context['application_date']}" if context["application_date"] else ""
    return {
        "subject": f"Rueckfrage zu meiner Bewerbung als {context['role']}",
        "body": (
            f"Guten Tag {context['recipient']},\n\n"
            f"ich wollte mich kurz nach dem aktuellen Stand meiner Bewerbung als {context['role']} "
            f"bei {context['company']}{submitted_phrase} erkundigen.\n\n"
            "Ich bin weiterhin sehr an der Position interessiert und freue mich ueber eine kurze "
            "Rueckmeldung zu den naechsten Schritten.\n\n"
            f"Mit freundlichen Gruessen\n{context['sender']}"
        ),
    }


def _generate_chinese_template(context: dict[str, str], template_type: str) -> dict[str, str]:
    if template_type == "Interview Thank-you Email":
        return {
            "subject": f"感谢面试机会 - {context['role']}",
            "body": (
                f"{context['recipient']}您好，\n\n"
                f"非常感谢您抽出时间与我沟通 {context['company']} 的 {context['role']} 职位。\n\n"
                "这次交流让我更清楚地了解了团队、岗位内容和后续流程，也进一步增强了我对这个机会的兴趣。\n\n"
                "如果后续需要我补充任何材料，请随时告诉我。\n\n"
                f"祝好，\n{context['sender']}"
            ),
        }
    if template_type == "Recruiter Outreach Email":
        return {
            "subject": f"咨询 {context['company']} 的 {context['role']} 机会",
            "body": (
                f"{context['recipient']}您好，\n\n"
                f"我对 {context['company']} 的 {context['role']} 机会很感兴趣，因此想主动联系您。\n\n"
                "我的背景结合了质量保证、自动化和技术运营方向。如果我的经历与团队需求匹配，"
                "我很乐意进一步分享简历和项目经历。\n\n"
                "感谢您的时间，期待您的回复。\n\n"
                f"祝好，\n{context['sender']}"
            ),
        }
    if template_type == "Rejection Acknowledgement Email":
        return {
            "subject": f"感谢您的反馈 - {context['role']}",
            "body": (
                f"{context['recipient']}您好，\n\n"
                f"感谢您告知我关于 {context['company']} 的 {context['role']} 职位申请结果。\n\n"
                "虽然结果有些遗憾，但我仍然感谢您和团队花时间审核我的申请材料。"
                "如果未来有更匹配的机会，也希望您可以继续考虑我的资料。\n\n"
                f"祝好，\n{context['sender']}"
            ),
        }
    submitted_phrase = f"（提交日期：{context['application_date']}）" if context["application_date"] else ""
    return {
        "subject": f"跟进 {context['role']} 职位申请",
        "body": (
            f"{context['recipient']}您好，\n\n"
            f"我想跟进一下我申请 {context['company']} 的 {context['role']} 职位{submitted_phrase}的进展。\n\n"
            "我仍然非常关注这个机会，也很期待了解后续流程或任何更新。\n\n"
            "感谢您的时间。\n\n"
            f"祝好，\n{context['sender']}"
        ),
    }


def _follow_up(context: dict[str, str]) -> dict[str, str]:
    submitted_phrase = f" submitted on {context['application_date']}" if context["application_date"] else ""
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
