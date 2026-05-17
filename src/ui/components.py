from __future__ import annotations

import pandas as pd
import streamlit as st


def render_app_header(workspace: str) -> None:
    st.title(workspace)
    st.caption("Job application tracking, email classification, and follow-up reminders.")


def with_display_sequence(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    sorted_df = df.sort_values(
        by=["application_date", "company", "role", "id"],
        ascending=[False, True, True, False],
        na_position="last",
    ).reset_index(drop=True)
    sorted_df.insert(0, "#", range(1, len(sorted_df) + 1))
    return sorted_df
