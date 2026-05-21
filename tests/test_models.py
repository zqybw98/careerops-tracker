import pytest
from src.models import normalize_status


@pytest.mark.parametrize(
    ("raw_status", "expected"),
    [
        ("", "Applied"),
        (None, "Applied"),
        ("Submitted", "Applied"),
        ("Bewerbung abgeschickt", "Applied"),
        ("gespeichert", "Applied"),
        ("Confirmation Received", "Waiting"),
        ("Eingangsbestätigung", "Waiting"),
        ("We received your application", "Waiting"),
        ("Process is delayed", "Waiting"),
        ("Keine Rückmeldung", "Waiting"),
        ("Interview invitation", "Interview / Assessment"),
        ("Vorstellungsgespräch Termin", "Interview / Assessment"),
        ("Coding test challenge", "Interview / Assessment"),
        ("Aufgabe", "Interview / Assessment"),
        ("Follow-up reminder", "Action Needed"),
        ("Nachfassen", "Action Needed"),
        ("Offer", "Action Needed"),
        ("Angebot", "Action Needed"),
        ("Absage", "Rejected"),
        ("Leider nicht berücksichtigt", "Rejected"),
        ("Unfortunately not selected", "Rejected"),
        ("We have decided to progress with other candidates", "Rejected"),
        ("unknown custom status", "Applied"),
    ],
)
def test_normalize_status_handles_common_status_variants(raw_status: object, expected: str) -> None:
    assert normalize_status(raw_status) == expected
