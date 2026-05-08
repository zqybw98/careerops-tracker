from src.csv_importer import normalize_import_rows


def test_imports_chinese_header_csv_rows() -> None:
    result = normalize_import_rows(
        [
            {
                "公司名称 (Company)": "Bosch",
                "职位名称 (Position)": "Werkstudent Informatik",
                "申请日期 (Date Applied)": "2023/5/3",
                "最新状态 (Status)": "已收到拒信",
                "拒绝原因": "After HR screen",
                "备注/来源 (Notes)": "",
                "Column 1": "",
                "Unnamed: 6": "",
            },
            {
                "公司名称 (Company)": "DLR",
                "职位名称 (Position)": "Student/in Simulation",
                "申请日期 (Date Applied)": "2026/2/5",
                "最新状态 (Status)": "已确认收到",
                "备注/来源 (Notes)": "Application transferred to department",
                "Column 1": "",
                "Unnamed: 6": "",
            },
        ]
    )

    assert len(result.rows) == 2
    assert result.rows[0]["company"] == "Bosch"
    assert result.rows[0]["application_date"] == "2023-05-03"
    assert result.rows[0]["status"] == "Rejected"
    assert result.rows[0]["rejection_reason"] == "After HR screen"
    assert result.rows[1]["status"] == "Confirmation Received"


def test_skips_repeated_headers_and_imports_numbered_table_rows() -> None:
    result = normalize_import_rows(
        [
            {
                "公司名称 (Company)": "序号",
                "职位名称 (Position)": "公司名称",
                "申请日期 (Date Applied)": "申请职位",
                "最新状态 (Status)": "申请日期",
                "备注/来源 (Notes)": "最新状态",
                "Column 1": "状态更新日期",
                "Unnamed: 6": "备注",
            },
            {
                "公司名称 (Company)": "1",
                "职位名称 (Position)": "pi4_robotics GmbH",
                "申请日期 (Date Applied)": "IT-Mitarbeiter",
                "最新状态 (Status)": "2026/1/31",
                "备注/来源 (Notes)": "已申请",
                "Column 1": "2026/1/31",
                "Unnamed: 6": "收到系统自动回复确认",
            },
        ]
    )

    assert len(result.rows) == 1
    assert result.skipped_count == 1
    assert result.rows[0]["company"] == "pi4_robotics GmbH"
    assert result.rows[0]["role"] == "IT-Mitarbeiter"
    assert result.rows[0]["application_date"] == "2026-01-31"
    assert result.rows[0]["status"] == "Applied"
    assert "收到系统自动回复确认" in result.rows[0]["notes"]


def test_imports_pipe_delimited_rows_from_first_column() -> None:
    result = normalize_import_rows(
        [
            {
                "公司名称 (Company)": (
                    "2026-04-29 | DILAX | Student Assistant Software Testing & Automation | "
                    "Email sent | QA/Test Automation CV (English) | Email application | "
                    "2026-05-07 or 2026-05-08 | Online link broken, applied by email"
                ),
                "职位名称 (Position)": "",
                "申请日期 (Date Applied)": "",
                "最新状态 (Status)": "",
                "备注/来源 (Notes)": "",
                "Column 1": "",
                "Unnamed: 6": "",
            }
        ]
    )

    assert len(result.rows) == 1
    assert result.rows[0]["company"] == "DILAX"
    assert result.rows[0]["role"] == "Student Assistant Software Testing & Automation"
    assert result.rows[0]["application_date"] == "2026-04-29"
    assert result.rows[0]["status"] == "Applied"
    assert "QA/Test Automation CV" in result.rows[0]["notes"]
