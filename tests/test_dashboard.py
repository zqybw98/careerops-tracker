from src.dashboard import filter_dashboard_applications


def test_dashboard_hides_closed_applications_by_default() -> None:
    applications = [
        {"company": "A", "status": "Saved"},
        {"company": "B", "status": "Applied"},
        {"company": "C", "status": "Confirmation Received"},
        {"company": "D", "status": "Interview Scheduled"},
        {"company": "E", "status": "Assessment"},
        {"company": "F", "status": "Offer"},
        {"company": "G", "status": "Follow-up Needed"},
        {"company": "H", "status": "Rejected"},
        {"company": "I", "status": "No Response"},
    ]

    visible = filter_dashboard_applications(applications)

    assert [application["company"] for application in visible] == ["A", "B", "C", "D", "E", "F", "G"]


def test_dashboard_can_include_closed_applications() -> None:
    applications = [
        {"company": "A", "status": "Applied"},
        {"company": "B", "status": "Rejected"},
        {"company": "C", "status": "No Response"},
    ]

    visible = filter_dashboard_applications(applications, include_closed=True)

    assert visible == applications
