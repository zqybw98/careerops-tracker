from pathlib import Path

from src.database import get_applications, init_db
from src.demo_data import read_sample_applications, seed_sample_applications


def test_reads_sample_applications() -> None:
    rows = read_sample_applications(Path("samples/sample_applications.csv"))

    assert len(rows) == 4
    assert rows[0]["company"] == "Siemens"
    assert rows[2]["status"] == "Assessment"


def test_seed_sample_applications_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"
    init_db(db_path)

    first_import_count = seed_sample_applications(db_path=db_path)
    second_import_count = seed_sample_applications(db_path=db_path)

    applications = get_applications(db_path)
    assert first_import_count == 4
    assert second_import_count == 0
    assert len(applications) == 4
