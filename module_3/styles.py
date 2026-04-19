"""Custom CSS injected into the Streamlit app.

Kept in a separate file so we can iterate on styles without touching logic,
and so future devs see the aesthetic surface area in one place.
"""

CUSTOM_CSS = """
<style>
    /* ---- Fonts ---- */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }

    /* ---- Base dark theme overrides ---- */
    .stApp {
        background: linear-gradient(135deg, #0a0e27 0%, #1a1f3a 50%, #0a0e27 100%);
        background-attachment: fixed;
    }

    /* Soft animated gradient backdrop */
    .stApp::before {
        content: '';
        position: fixed;
        top: 0; left: 0; right: 0; bottom: 0;
        background: radial-gradient(circle at 20% 30%, rgba(66, 153, 225, 0.15) 0%, transparent 50%),
                    radial-gradient(circle at 80% 70%, rgba(168, 85, 247, 0.1) 0%, transparent 50%);
        pointer-events: none;
        z-index: 0;
    }

    .main .block-container {
        padding-top: 2rem;
        max-width: 900px;
        position: relative;
        z-index: 1;
    }

    /* ---- Header ---- */
    .app-header {
        display: flex;
        align-items: center;
        gap: 1rem;
        margin-bottom: 0.5rem;
    }
    .app-title {
        font-size: 2.5rem;
        font-weight: 800;
        background: linear-gradient(135deg, #60a5fa 0%, #a78bfa 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        margin: 0;
        letter-spacing: -0.02em;
    }
    .app-subtitle {
        color: #94a3b8;
        font-size: 1rem;
        margin-top: 0;
        margin-bottom: 2rem;
        font-weight: 400;
    }
    .app-badge {
        display: inline-block;
        background: rgba(96, 165, 250, 0.15);
        border: 1px solid rgba(96, 165, 250, 0.3);
        color: #93c5fd;
        padding: 0.2rem 0.6rem;
        border-radius: 9999px;
        font-size: 0.7rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-left: 0.5rem;
        vertical-align: middle;
    }

    /* ---- Welcome card ---- */
    .welcome-card {
        background: rgba(30, 41, 59, 0.5);
        backdrop-filter: blur(10px);
        border: 1px solid rgba(148, 163, 184, 0.15);
        border-radius: 16px;
        padding: 1.75rem;
        margin-bottom: 1.5rem;
        animation: fadeInUp 0.6s ease-out;
    }
    .welcome-card h3 {
        color: #e2e8f0;
        margin-top: 0;
        font-weight: 600;
        font-size: 1.15rem;
    }
    .welcome-card p {
        color: #cbd5e1;
        line-height: 1.6;
        margin-bottom: 0.75rem;
    }
    .welcome-card .dataset-stats {
        display: flex;
        gap: 1.5rem;
        margin: 1rem 0;
        flex-wrap: wrap;
    }
    .welcome-card .stat {
        background: rgba(15, 23, 42, 0.6);
        padding: 0.6rem 1rem;
        border-radius: 8px;
        border: 1px solid rgba(148, 163, 184, 0.1);
    }
    .welcome-card .stat-value {
        color: #60a5fa;
        font-weight: 700;
        font-size: 1.1rem;
        display: block;
    }
    .welcome-card .stat-label {
        color: #94a3b8;
        font-size: 0.75rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .welcome-card .examples-heading {
        color: #e2e8f0;
        font-weight: 600;
        margin-top: 1rem;
        margin-bottom: 0.5rem;
        font-size: 0.9rem;
    }

    /* ---- Example question buttons ---- */
    .example-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 0.6rem;
        margin-top: 0.5rem;
    }
    @media (max-width: 600px) {
        .example-grid { grid-template-columns: 1fr; }
    }

    /* Streamlit buttons styled as prompt chips */
    .stButton > button {
        background: rgba(51, 65, 85, 0.4) !important;
        color: #e2e8f0 !important;
        border: 1px solid rgba(148, 163, 184, 0.2) !important;
        border-radius: 10px !important;
        padding: 0.65rem 1rem !important;
        font-size: 0.85rem !important;
        font-weight: 400 !important;
        text-align: left !important;
        transition: all 0.2s ease !important;
        width: 100% !important;
        white-space: normal !important;
        height: auto !important;
        line-height: 1.4 !important;
    }
    .stButton > button:hover {
        background: rgba(59, 130, 246, 0.15) !important;
        border-color: rgba(96, 165, 250, 0.4) !important;
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    }
    .stButton > button:active {
        transform: translateY(0);
    }

    /* ---- Chat message bubbles ---- */
    [data-testid="stChatMessage"] {
        background: rgba(30, 41, 59, 0.4) !important;
        backdrop-filter: blur(8px);
        border: 1px solid rgba(148, 163, 184, 0.1);
        border-radius: 14px !important;
        padding: 1rem 1.25rem !important;
        margin-bottom: 0.75rem;
        animation: fadeIn 0.3s ease-out;
    }
    [data-testid="stChatMessage"] p,
    [data-testid="stChatMessage"] li {
        color: #e2e8f0 !important;
        line-height: 1.6;
    }

    /* Assistant avatar accent */
    [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) {
        border-left: 3px solid #60a5fa;
    }
    [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
        border-left: 3px solid #a78bfa;
    }

    /* ---- Chat input ---- */
    [data-testid="stChatInput"] {
        background: rgba(15, 23, 42, 0.8) !important;
        backdrop-filter: blur(10px);
        border: 1px solid rgba(148, 163, 184, 0.2) !important;
        border-radius: 14px !important;
    }
    [data-testid="stChatInput"] textarea {
        color: #e2e8f0 !important;
        font-family: 'Inter', sans-serif !important;
    }

    /* ---- Scalar metric (for single-value answers) ---- */
    .scalar-metric {
        background: linear-gradient(135deg,
            rgba(96, 165, 250, 0.12) 0%,
            rgba(168, 85, 247, 0.08) 100%);
        border: 1px solid rgba(96, 165, 250, 0.25);
        border-radius: 14px;
        padding: 1.5rem 1.25rem;
        margin: 0.75rem 0;
        text-align: center;
        animation: fadeInUp 0.4s ease-out;
    }
    .scalar-value {
        font-size: 2.5rem;
        font-weight: 700;
        background: linear-gradient(135deg, #60a5fa 0%, #a78bfa 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        letter-spacing: -0.02em;
        line-height: 1.1;
        font-family: 'JetBrains Mono', monospace;
    }
    .scalar-label {
        color: #94a3b8;
        font-size: 0.75rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-top: 0.4rem;
        font-weight: 500;
    }

    /* ---- Visualization labels (above charts / tables) ---- */
    .viz-label {
        color: #94a3b8;
        font-size: 0.75rem;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        font-weight: 600;
        margin-top: 0.9rem;
        margin-bottom: 0.3rem;
        display: flex;
        align-items: center;
        gap: 0.4rem;
    }

    /* Streamlit dataframe tweaks for dark theme */
    [data-testid="stDataFrame"] {
        border: 1px solid rgba(148, 163, 184, 0.15) !important;
        border-radius: 10px !important;
        overflow: hidden;
    }

    /* Plotly chart container padding */
    [data-testid="stPlotlyChart"] {
        background: rgba(15, 23, 42, 0.3);
        border: 1px solid rgba(148, 163, 184, 0.1);
        border-radius: 10px;
        padding: 0.5rem;
        margin-top: 0.25rem;
    }

    /* ---- SQL code block ---- */
    .sql-block {
        background: rgba(15, 23, 42, 0.9) !important;
        border: 1px solid rgba(96, 165, 250, 0.2);
        border-radius: 10px;
        padding: 1rem;
        margin-top: 0.75rem;
        font-family: 'JetBrains Mono', monospace;
    }
    .sql-label {
        color: #60a5fa;
        font-size: 0.7rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        font-weight: 600;
        margin-bottom: 0.5rem;
        display: flex;
        align-items: center;
        gap: 0.4rem;
    }
    .sql-label::before {
        content: '';
        display: inline-block;
        width: 6px; height: 6px;
        background: #60a5fa;
        border-radius: 50%;
        box-shadow: 0 0 8px rgba(96, 165, 250, 0.6);
    }

    /* Streamlit code block tweaks */
    code {
        font-family: 'JetBrains Mono', monospace !important;
        color: #93c5fd !important;
        background: rgba(15, 23, 42, 0.6) !important;
        padding: 0.1rem 0.35rem;
        border-radius: 4px;
        font-size: 0.85em;
    }
    pre code {
        padding: 0 !important;
    }

    /* ---- Status indicator ---- */
    [data-testid="stStatusWidget"] {
        background: rgba(30, 41, 59, 0.6) !important;
        border: 1px solid rgba(148, 163, 184, 0.15) !important;
        border-radius: 10px !important;
    }

    /* ---- Warning banners (for guardrail flags) ---- */
    .warning-banner {
        background: rgba(251, 191, 36, 0.1);
        border: 1px solid rgba(251, 191, 36, 0.3);
        color: #fbbf24;
        padding: 0.6rem 0.9rem;
        border-radius: 8px;
        font-size: 0.85rem;
        margin-top: 0.5rem;
    }

    /* ---- Footer ---- */
    .app-footer {
        text-align: center;
        color: #64748b;
        font-size: 0.75rem;
        margin-top: 3rem;
        padding-bottom: 1rem;
    }
    .app-footer a {
        color: #94a3b8;
        text-decoration: none;
    }
    .app-footer a:hover {
        color: #cbd5e1;
    }

    /* ---- Animations ---- */
    @keyframes fadeIn {
        from { opacity: 0; }
        to { opacity: 1; }
    }
    @keyframes fadeInUp {
        from {
            opacity: 0;
            transform: translateY(10px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }

    /* Hide Streamlit default chrome */
    #MainMenu { visibility: hidden; }
    footer { visibility: hidden; }
    [data-testid="stDecoration"] { display: none; }
    [data-testid="stHeader"] {
        background: transparent;
    }

    /* Scrollbar polish */
    ::-webkit-scrollbar { width: 8px; height: 8px; }
    ::-webkit-scrollbar-track { background: rgba(15, 23, 42, 0.5); }
    ::-webkit-scrollbar-thumb {
        background: rgba(100, 116, 139, 0.4);
        border-radius: 4px;
    }
    ::-webkit-scrollbar-thumb:hover { background: rgba(100, 116, 139, 0.6); }
</style>
"""