"""Auto-visualization for SQL result sets.

Given a list of row-dicts, decide what's the best way to display it:
  - 1 row, 1 column (scalar) → render as a big number
  - 2 columns, label + number, 2-30 rows → horizontal bar chart + table
  - 1 column many rows → table only
  - wide / complex → table only

The decision is purely structural — no LLM involvement. The agent already
produces a prose answer; this module is about supplementing that answer with
visual evidence.
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st


_MIN_CHART_ROWS = 2
_MAX_CHART_ROWS = 30


@dataclass
class RenderedResult:
    df: pd.DataFrame
    chart_type: str  # "scalar", "bar", "table_only", "none"
    label_col: Optional[str] = None
    value_col: Optional[str] = None


def classify(rows: List[Dict[str, Any]], columns: List[str]) -> RenderedResult:
    """Pick the right visualization for this result shape."""
    if not rows or not columns:
        return RenderedResult(df=pd.DataFrame(), chart_type="none")

    df = pd.DataFrame(rows, columns=columns)

    # Case 1: single scalar
    if len(df) == 1 and len(columns) == 1:
        return RenderedResult(df=df, chart_type="scalar", value_col=columns[0])

    # Case 2: exactly two columns with a plausible (label, number) shape
    if len(columns) == 2 and _MIN_CHART_ROWS <= len(df) <= _MAX_CHART_ROWS:
        c1, c2 = columns
        c1_numeric = pd.api.types.is_numeric_dtype(df[c1])
        c2_numeric = pd.api.types.is_numeric_dtype(df[c2])
        if c1_numeric and not c2_numeric:
            return RenderedResult(df=df, chart_type="bar",
                                  label_col=c2, value_col=c1)
        if c2_numeric and not c1_numeric:
            return RenderedResult(df=df, chart_type="bar",
                                  label_col=c1, value_col=c2)

    # Case 3: one numeric column, many rows — could be a distribution
    if len(columns) == 1 and len(df) >= _MIN_CHART_ROWS:
        return RenderedResult(df=df, chart_type="table_only", value_col=columns[0])

    # Default: just show the table
    return RenderedResult(df=df, chart_type="table_only")


def _format_big_number(n: float) -> str:
    """Render a number with commas and scale suffix for display."""
    if n is None:
        return "—"
    try:
        n = float(n)
    except (TypeError, ValueError):
        return str(n)

    abs_n = abs(n)
    if abs_n >= 1_000_000_000:
        return f"{n/1_000_000_000:,.2f}B"
    if abs_n >= 1_000_000:
        return f"{n/1_000_000:,.2f}M"
    if abs_n >= 1_000:
        return f"{n:,.0f}"
    if abs_n >= 1:
        return f"{n:,.2f}"
    return f"{n:.4f}"


def render(result: RenderedResult, container=None) -> None:
    """Render the classified result into a Streamlit container."""
    if container is None:
        container = st

    if result.chart_type == "none":
        return

    if result.chart_type == "scalar":
        val = result.df.iloc[0, 0]
        container.markdown(
            f"""
            <div class="scalar-metric">
                <div class="scalar-value">{_format_big_number(val)}</div>
                <div class="scalar-label">{result.value_col}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    if result.chart_type == "bar":
        # Sort descending by value for visual clarity
        df_sorted = result.df.sort_values(result.value_col, ascending=True)
        container.markdown(
            f'<div class="viz-label">📊 {result.value_col} by {result.label_col}</div>',
            unsafe_allow_html=True,
        )
        # Streamlit's bar_chart is the simplest; use a plotly chart for
        # better styling
        import plotly.express as px
        fig = px.bar(
            df_sorted,
            x=result.value_col,
            y=result.label_col,
            orientation="h",
            text=result.value_col,
        )
        fig.update_traces(
            texttemplate="%{x:,.0f}",
            textposition="outside",
            marker_color="#60a5fa",
        )
        fig.update_layout(
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#e2e8f0", family="Inter"),
            xaxis=dict(
                showgrid=True, gridcolor="rgba(148, 163, 184, 0.1)",
                tickformat=",",
            ),
            yaxis=dict(showgrid=False),
            margin=dict(l=0, r=20, t=10, b=20),
            height=max(200, 40 * len(df_sorted) + 50),
            showlegend=False,
        )
        container.plotly_chart(fig, use_container_width=True,
                               config={"displayModeBar": False})

    # Table always follows (or is the only view for table_only)
    container.markdown(
        '<div class="viz-label">📋 Full result</div>',
        unsafe_allow_html=True,
    )
    # Format numeric columns with thousand separators
    df_display = result.df.copy()
    for col in df_display.columns:
        if pd.api.types.is_numeric_dtype(df_display[col]):
            df_display[col] = df_display[col].apply(
                lambda x: f"{x:,.0f}" if pd.notna(x) and x == int(x)
                else f"{x:,.4f}" if pd.notna(x) else "—"
            )
    container.dataframe(df_display, use_container_width=True, hide_index=True)