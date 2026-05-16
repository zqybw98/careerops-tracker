from datetime import date

from src.calendar_export import CalendarItem
from src.ui.data_settings_page import _calendar_date_range_default, _date_range_bounds


def test_date_range_bounds_accepts_empty_streamlit_range() -> None:
    assert _date_range_bounds(()) == (None, None)


def test_date_range_bounds_accepts_selected_range() -> None:
    start = date(2026, 5, 1)
    end = date(2026, 5, 31)

    assert _date_range_bounds((start, end)) == (start, end)


def test_date_range_bounds_accepts_single_selected_date() -> None:
    selected = date(2026, 5, 16)

    assert _date_range_bounds(selected) == (selected, selected)


def test_calendar_date_range_default_covers_all_calendar_items() -> None:
    items = [
        _calendar_item(date(2026, 5, 20)),
        _calendar_item(date(2026, 5, 10)),
        _calendar_item(date(2026, 5, 30)),
    ]

    assert _calendar_date_range_default(items) == (date(2026, 5, 10), date(2026, 5, 30))


def _calendar_item(event_date: date) -> CalendarItem:
    return CalendarItem(
        application_id=1,
        event_type="Follow-up",
        event_date=event_date,
        company="Example",
        role="QA Engineer",
        location="Berlin",
        summary="Follow up",
        description="Reminder",
    )
