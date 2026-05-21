from src.dashboard import filter_dashboard_applications


def test_dashboard_hides_closed_applications_by_default() -> None:
    applications = [
        {"company": "A", "status": "Applied"},
        {"company": "B", "status": "Applied"},
        {"company": "C", "status": "Waiting"},
        {"company": "D", "status": "Interview / Assessment"},
        {"company": "E", "status": "Action Needed"},
        {"company": "H", "status": "Rejected"},
    ]

    visible = filter_dashboard_applications(applications)

    assert [application["company"] for application in visible] == ["A", "B", "C", "D", "E"]


def test_dashboard_can_include_closed_applications() -> None:
    applications = [
        {"company": "A", "status": "Applied"},
        {"company": "B", "status": "Rejected"},
        {"company": "C", "status": "Waiting"},
    ]

    visible = filter_dashboard_applications(applications, include_closed=True)

    assert visible == applications
