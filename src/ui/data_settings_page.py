from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import streamlit as st

from src.calendar_export import (
    CalendarItem,
    build_calendar_items,
    build_calendar_text_block,
    build_ics_calendar,
    calendar_items_to_rows,
)
from src.csv_importer import normalize_import_rows
from src.database import (
    DEFAULT_DB_PATH,
    ApplicationFieldChange,
    ApplicationSyncPreview,
    deduplicate_applications,
    get_application_events,
    preview_application_sync,
    sync_applications,
)
from src.demo_data import seed_sample_applications
from src.models import APPLICATION_COLUMNS


def render_data_tools(applications: list[dict]) -> None:
    st.subheader("Sample Data")

    if st.button("Load sample applications"):
        created = seed_sample_applications()
        if created:
            st.success(f"Loaded {created} sample applications.")
        else:
            st.info("Sample applications are already loaded.")
        st.rerun()

    st.subheader("CSV Import")
    uploaded_file = st.file_uploader("Import applications from CSV", type=["csv"])
    if uploaded_file is not None:
        uploaded_df = pd.read_csv(uploaded_file, dtype=str).fillna("")
        import_result = normalize_import_rows(uploaded_df.to_dict(orient="records"))
        sync_preview: ApplicationSyncPreview | None = None

        if not import_result.rows:
            st.error("No valid application rows found in this CSV.")
            st.caption("Detected columns: " + ", ".join(import_result.source_columns))
        else:
            st.success(f"Detected {len(import_result.rows)} application rows ready to review.")
            if import_result.skipped_count:
                st.caption(f"Skipped {import_result.skipped_count} blank, duplicate, or header-like rows.")

            sync_preview = preview_application_sync(import_result.rows)
            _render_import_preview(sync_preview)

        has_import_changes = False
        if sync_preview is not None:
            has_import_changes = sync_preview.created > 0 or sync_preview.updated > 0

        if sync_preview is not None and not has_import_changes:
            st.info("No database changes detected. This CSV is already in sync.")

        if sync_preview is not None and st.button("Import CSV changes", disabled=not has_import_changes):
            result = sync_applications(import_result.rows, source="csv_import")
            st.success(
                f"Import complete: {result['created']} created, "
                f"{result['updated']} updated, {result['skipped']} unchanged."
            )
            st.rerun()

    st.subheader("Backup / Export")
    st.caption("Create a local copy before large imports, cleanup, or real job-search updates.")
    backup_col_a, backup_col_b, backup_col_c = st.columns(3)
    backup_col_a.download_button(
        "Download all data as CSV",
        _applications_csv_bytes(applications) if applications else b"",
        file_name=_backup_file_name("careerops_applications", "csv"),
        mime="text/csv",
        disabled=not applications,
    )

    events = get_application_events()
    backup_col_b.download_button(
        "Export activity log",
        _activity_log_csv_bytes(events),
        file_name=_backup_file_name("careerops_activity_log", "csv"),
        mime="text/csv",
        disabled=not events,
    )

    db_bytes = _sqlite_backup_bytes()
    backup_col_c.download_button(
        "Download SQLite backup",
        db_bytes or b"",
        file_name=_backup_file_name("careerops_backup", "db"),
        mime="application/x-sqlite3",
        disabled=db_bytes is None,
    )
    if not applications:
        st.info("Add or import applications before exporting CSV data.")

    st.subheader("Calendar Export")
    calendar_items = build_calendar_items(applications)
    if not calendar_items:
        st.info("Add follow-up dates to interviews, assessments, or applications to export calendar events.")
    else:
        event_type_options = sorted({item.event_type for item in calendar_items})
        cal_col_a, cal_col_b = st.columns([1, 1.4])
        selected_event_types = cal_col_a.multiselect(
            "Event types",
            event_type_options,
            default=event_type_options,
            key="calendar_event_type_filter",
        )
        calendar_date_range = cal_col_b.date_input(
            "Calendar date range",
            value=_calendar_date_range_default(calendar_items),
            key="calendar_export_date_range",
        )
        calendar_start_date, calendar_end_date = _date_range_bounds(calendar_date_range)
        filtered_calendar_items = _filter_calendar_items(
            calendar_items,
            selected_event_types=selected_event_types,
            start_date=calendar_start_date,
            end_date=calendar_end_date,
        )

        if not filtered_calendar_items:
            st.info("No calendar events match the current filters.")
        else:
            st.dataframe(
                pd.DataFrame(calendar_items_to_rows(filtered_calendar_items)),
                use_container_width=True,
                hide_index=True,
            )
            st.download_button(
                "Download calendar .ics",
                build_ics_calendar(filtered_calendar_items).encode("utf-8"),
                file_name="careerops_calendar.ics",
                mime="text/calendar",
            )
            st.text_area(
                "Calendar text block",
                value=build_calendar_text_block(filtered_calendar_items),
                height=220,
                key="calendar_text_block",
            )

    with st.expander("CSV format"):
        st.code(", ".join(APPLICATION_COLUMNS), language="text")
        st.caption(
            "English and common Chinese headers are supported, "
            "for example 公司名称, 职位名称, 申请日期, 最新状态, 备注/来源."
        )

    if applications:
        with st.expander("Maintenance"):
            st.caption("Use this after repeated CSV imports to remove duplicate company/role/date records.")
            if st.button("Clean duplicate applications", key="data_clean_duplicates"):
                removed = deduplicate_applications()
                if removed:
                    st.success(f"Removed {removed} duplicate records.")
                else:
                    st.info("No duplicate records found.")
                st.rerun()


def _render_import_preview(preview: ApplicationSyncPreview) -> None:
    metric_col_a, metric_col_b, metric_col_c, metric_col_d = st.columns(4)
    metric_col_a.metric("Created", preview.created)
    metric_col_b.metric("Updated", preview.updated)
    metric_col_c.metric("Unchanged", preview.unchanged)
    metric_col_d.metric("Skipped", preview.skipped)

    st.caption("Review the planned changes before writing anything to the SQLite database.")
    created_tab, updated_tab, unchanged_tab = st.tabs(["Created", "Updated", "Unchanged"])
    _render_preview_action_tab(created_tab, preview, "Created")
    _render_preview_action_tab(updated_tab, preview, "Updated")
    _render_preview_action_tab(unchanged_tab, preview, "Unchanged")

    if preview.skipped:
        skipped_rows = _import_preview_dataframe(preview, action="Skipped")
        with st.expander("Skipped rows"):
            st.dataframe(skipped_rows, use_container_width=True, hide_index=True)


def _render_preview_action_tab(tab: Any, preview: ApplicationSyncPreview, action: str) -> None:
    rows = _import_preview_dataframe(preview, action=action)
    if rows.empty:
        tab.info(f"No {action.lower()} rows.")
        return

    tab.dataframe(rows, use_container_width=True, hide_index=True)


def _import_preview_dataframe(
    preview: ApplicationSyncPreview,
    action: str | None = None,
) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for row in preview.rows:
        if action and row.action != action:
            continue
        field_changes = _format_field_changes(row.field_changes)
        records.append(
            {
                "Action": row.action,
                "Company": row.company,
                "Role": row.role,
                "Application date": row.application_date,
                "Matched ID": row.matched_id or "",
                "Fields to overwrite": ", ".join(change.field for change in row.field_changes)
                if row.action == "Updated"
                else "-",
                "Change details": field_changes,
                "Reason": row.reason,
            }
        )
    return pd.DataFrame(records)


def _format_field_changes(changes: list[ApplicationFieldChange]) -> str:
    formatted: list[str] = []
    for change in changes:
        field = change.field
        current = _display_value(change.current)
        incoming = _display_value(change.incoming)
        formatted.append(f"{field}: {current} -> {incoming}")
    return "; ".join(formatted) if formatted else "-"


def _display_value(value: str) -> str:
    return value if value else "(empty)"


def _applications_csv_bytes(applications: list[dict]) -> bytes:
    export_df = _with_display_sequence(pd.DataFrame(applications))
    export_columns = ["#"] + APPLICATION_COLUMNS + ["created_at", "updated_at"]
    available_columns = [column for column in export_columns if column in export_df.columns]
    csv_text: str = export_df[available_columns].to_csv(index=False)
    return csv_text.encode("utf-8-sig")


def _activity_log_csv_bytes(events: list[dict]) -> bytes:
    if not events:
        return b""
    csv_text: str = pd.DataFrame(events).to_csv(index=False)
    return csv_text.encode("utf-8-sig")


def _sqlite_backup_bytes() -> bytes | None:
    if not DEFAULT_DB_PATH.exists():
        return None
    return DEFAULT_DB_PATH.read_bytes()


def _backup_file_name(stem: str, extension: str) -> str:
    return f"{stem}_{date.today().isoformat()}.{extension}"


def _with_display_sequence(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    sorted_df = df.sort_values(
        by=["application_date", "id"],
        ascending=[False, False],
        na_position="last",
    ).reset_index(drop=True)
    sorted_df.insert(0, "#", range(1, len(sorted_df) + 1))
    return sorted_df


def _date_range_bounds(value: object) -> tuple[date | None, date | None]:
    if isinstance(value, tuple) and len(value) == 2:
        start, end = value
        return (start if isinstance(start, date) else None, end if isinstance(end, date) else None)
    if isinstance(value, date):
        return value, value
    return None, None


def _calendar_date_range_default(calendar_items: list[CalendarItem]) -> tuple[date, date]:
    event_dates = [item.event_date for item in calendar_items]
    return min(event_dates), max(event_dates)


def _filter_calendar_items(
    calendar_items: list[CalendarItem],
    selected_event_types: list[str],
    start_date: date | None,
    end_date: date | None,
) -> list[CalendarItem]:
    filtered_items: list[CalendarItem] = []
    selected_types = set(selected_event_types)
    for item in calendar_items:
        event_type = str(getattr(item, "event_type", ""))
        if selected_types and event_type not in selected_types:
            continue

        raw_item_date = getattr(item, "event_date", None)
        item_date = raw_item_date if isinstance(raw_item_date, date) else _text_to_date(raw_item_date)
        if start_date and item_date and item_date < start_date:
            continue
        if end_date and item_date and item_date > end_date:
            continue
        filtered_items.append(item)
    return filtered_items


def _text_to_date(value: object) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None
