"""K 线 / 财务图与格式化。"""
from __future__ import annotations

import math

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.ui.theme import (
    ACCENT, BG, DOWN, DOWN_FILL, FLAT, GRID, TEXT, UP, UP_FILL,
)


def calc_rsi(df: pd.DataFrame, n: int = 14):
    if len(df) < n + 1:
        return None
    d = df["close"].diff()
    g = d.clip(0)
    l = -d.clip(0)
    return (100 - 100 / (1 + g.rolling(n).mean() / l.rolling(n).mean())).values


def plot_quant_kline(df, name):
    if df.empty or len(df) < 30:
        return None
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.02,
                        row_heights=[0.5, 0.15, 0.35])
    fig.add_trace(go.Candlestick(
        x=df["trade_date"], open=df["open"], high=df["high"],
        low=df["low"], close=df["close"], name="", showlegend=False,
        increasing_line_color=UP, increasing_fillcolor=UP_FILL,
        decreasing_line_color=DOWN, decreasing_fillcolor=DOWN_FILL), row=1, col=1)
    for m, c, n in [(5, "#f97316", "MA5"), (20, "#facc15", "MA20"), (60, "#8b5cf6", "MA60")]:
        if len(df) >= m:
            fig.add_trace(go.Scatter(
                x=df["trade_date"], y=df["close"].rolling(m).mean(),
                line=dict(color=c, width=1), name=n), row=1, col=1)
    bc = [UP if r["close"] >= r["open"] else DOWN for _, r in df.iterrows()]
    fig.add_trace(go.Bar(x=df["trade_date"], y=df["volume"], marker_color=bc, name=""),
                  row=2, col=1)
    rsi = calc_rsi(df)
    if rsi is not None:
        t = df["trade_date"].values[-len(rsi):]
        fig.add_trace(go.Scatter(x=t, y=rsi, line=dict(color="#22d3ee", width=1),
                                 name="RSI(14)"), row=3, col=1)
        fig.add_hline(y=70, line_dash="dash", line_color=UP, row=3, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color=DOWN, row=3, col=1)
    fig.update_layout(height=450, template="plotly_dark",
                      margin=dict(l=10, r=10, t=10, b=10),
                      xaxis_rangeslider_visible=False, hovermode="x unified",
                      paper_bgcolor=BG, plot_bgcolor=BG, font=dict(color=TEXT))
    fig.update_xaxes(gridcolor=GRID)
    fig.update_yaxes(gridcolor=GRID)
    return fig


def plot_fin_trend(df):
    if df.empty:
        return None
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["period"], y=df["revenue"] / 1e8, mode="lines+markers",
        name="营收(亿)", line=dict(color="#3b82f6")))
    fig.add_trace(go.Scatter(
        x=df["period"], y=df["net_profit"] / 1e8, mode="lines+markers",
        name="净利润(亿)", line=dict(color="#f59e0b")))
    fig.update_layout(height=250, template="plotly_dark",
                      margin=dict(l=10, r=10, t=10, b=10),
                      paper_bgcolor=BG, plot_bgcolor=BG,
                      font=dict(color=TEXT, size=10),
                      xaxis=dict(gridcolor="#1e293b"),
                      yaxis=dict(gridcolor="#1e293b"))
    return fig


def fmt(val, d=2):
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "-"
    try:
        return f"{float(val):.{d}f}"
    except (TypeError, ValueError):
        return str(val) if str(val).strip() else "-"


def cor(s):
    if not s or s == "-":
        return FLAT
    s = str(s).replace("%", "")
    try:
        v = float(s)
        return UP if v > 0 else DOWN if v < 0 else FLAT
    except (TypeError, ValueError):
        return FLAT
