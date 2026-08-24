"""衡流 · HengLiu 深色主题。优先靠 Streamlit 主题变量，少量 data-testid 兜底。"""
from __future__ import annotations

UP, DOWN, FLAT = "#ef4444", "#22c55e", "#94a3b8"
BG, CARD = "#0f172a", "#3a4c68"
TEXT, MUTED, ACCENT = "#e2e8f0", "#8fa3bf", "#60a5fa"
GRID = "#2e3f5c"
UP_FILL, DOWN_FILL = "rgba(239,68,68,0.45)", "rgba(34,197,94,0.45)"

CSS = f"""<style>
:root {{
  --text-color: {TEXT};
  --background-color: {BG};
  --secondary-background-color: {CARD};
  --primary-color: {ACCENT};
}}
.stApp {{ background:{BG}; color:{TEXT}; }}
.stButton>button {{ background:{ACCENT}; color:#0f172a; font-weight:600; border:none; border-radius:4px; }}
h1,h2,h3, .stMarkdown {{ color:{TEXT} !important; }}
.stMetric label {{ color:{MUTED} !important; }}
div[data-testid="stMetricValue"] {{ color:{TEXT} !important; font-size:1.2rem !important; }}
div[data-testid="stCaptionContainer"] p {{ color:{MUTED} !important; }}
[data-testid="stTabs"] [data-testid="stTab"] {{ color:{MUTED} !important; }}
[data-testid="stTabs"] [data-testid="stTab"][aria-selected="true"] {{ color:{TEXT} !important; }}
[data-testid="stExpander"] summary, [data-testid="stExpander"] summary p {{ color:{TEXT} !important; }}
.stSelectbox div[data-baseweb="select"] {{ background:{CARD}; border-color:#40536e; }}
.stSelectbox div[data-baseweb="select"] span, .stSelectbox div[data-baseweb="select"] div {{ color:{TEXT} !important; }}
[data-testid="stSelectbox"] input, [data-testid="stSelectbox"] [role="combobox"] {{ color:{TEXT} !important; }}
.stTextInput input, .stTextArea textarea {{ background:{CARD}; color:{TEXT} !important; border-color:#40536e; }}
.stRadio label, .stCheckbox label {{ color:{TEXT} !important; }}
[data-testid="stWidgetLabel"] {{ color:{TEXT} !important; }}
[data-testid="stWidgetLabel"] p {{ color:{TEXT} !important; }}
[data-testid="stSelectbox"] [role="combobox"],
[data-testid="stSelectbox"] input,
[data-testid="stMultiselect"] input,
[data-testid="stNumberInput"] input,
.stTextInput input,
.stTextArea textarea {{
  background:#263449 !important;
  border:1px solid #40536e !important;
  border-radius:6px !important;
  color:{TEXT} !important;
}}
input::placeholder, textarea::placeholder {{ color:{MUTED} !important; }}
#stFloatingOverlayPortal [role="listbox"],
#portal [role="listbox"] {{
  background:#263449 !important;
  color:{TEXT} !important;
  border:1px solid #40536e !important;
  border-radius:6px !important;
}}
#stFloatingOverlayPortal [role="option"],
#portal [role="option"] {{ color:{TEXT} !important; }}
#stFloatingOverlayPortal [role="option"][aria-selected="true"],
#portal [role="option"][aria-selected="true"] {{
  background:rgba(96,165,250,0.25) !important;
  color:{TEXT} !important;
}}
[data-testid="stRadio"] [role="radio"] {{
  color:{TEXT} !important;
  background:transparent !important;
}}
[data-testid="stRadio"] [role="radio"][aria-checked="true"] {{
  color:{ACCENT} !important;
  background:rgba(96,165,250,0.12) !important;
}}
[data-testid="stCheckbox"] label {{ color:{TEXT} !important; }}
div[data-testid="stDataFrame"] {{ background:{CARD}; color:{TEXT}; }}
div[data-testid="stDataFrame"] td, div[data-testid="stDataFrame"] th {{ color:{TEXT} !important; }}
section[data-testid="stSidebar"] {{ background:{CARD}; border-right:1px solid #40536e; }}
</style>"""


def apply_theme(st) -> None:
    st.markdown(CSS, unsafe_allow_html=True)
