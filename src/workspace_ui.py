"""Shared workspace components for the running app and its local UI preview."""
from html import escape


def metric_grid(metrics):
    cards = ''.join(
        '<article class="mumo-metric"><span class="mumo-metric-label">'
        + escape(str(label)) + '</span><strong class="mumo-metric-value">'
        + escape(str(value)) + '</strong></article>' for label, value in metrics)
    return '<div class="mumo-metrics">' + cards + '</div>'


def render_sidebar_top(ui, state):
    from agent_catalog import AGENTS
    ui.markdown('<div class="workspace-brand"><span class="workspace-logo">✦</span>'
                '<span>mumo</span><small>WORKSPACE</small></div>', unsafe_allow_html=True)
    new_session = ui.button('＋ New session', key='workspace_new_session', use_container_width=True)
    with ui.popover('Agents', use_container_width=True):
        for agent in AGENTS:
            ui.markdown(f"**{agent['name']}** · {agent['role']}")
    with ui.popover('Appearance', use_container_width=True):
        ui.radio('Theme', ['dark', 'light'], key='theme', format_func=str.title)
    return new_session


def render_toolbar(ui, state, messages):
    # Settings belong outside the conversation; only job progress is inline.
    with ui.sidebar, ui.expander('Chat settings & tools', expanded=False), ui.container(key='workspace_toolbar'):
        cells = [ui] * 5
        cells[0].markdown('<div class="workspace-engine">✦ <strong>MUMO</strong>'
                          '<span>Research workspace</span></div>', unsafe_allow_html=True)
        cells[1].selectbox('Docking mode', ['Medium', 'Standard', 'High'], index=1,
                          key='docking_mode', label_visibility='collapsed',
                          format_func=lambda mode: f'{mode} · ' + {'Medium': '8', 'Standard': '16', 'High': '32'}[mode],
                          help='Vina exhaustiveness. Each mode retains three independently seeded searches.',
                          disabled=bool(state.get('job_id')))
        with cells[2].popover('Sources', use_container_width=True):
            ui.markdown('**Public data sources**\n\nPubChem · PDB · UniProt · AlphaFold · STRING · ChEMBL')
            ui.caption('Availability and structure identity are checked when requested; this is not a live connection indicator.')
        export = '\n\n'.join(f"## {m.get('role', 'message').title()}\n\n{m.get('content', '')}" for m in messages)
        cells[3].download_button('Export', export, 'mumo_chat.md', mime='text/markdown',
                                 key='export_visible_chat', disabled=not messages,
                                 help='Download the visible conversation. Scientific reports remain in Quill.')
        return cells[4].button('Clear', key='clear_visible_chat', disabled=not messages or bool(state.get('job_id')),
                               help='Clear only the visible chat. Saved history and calculation results remain available.')


def render_messages(ui, messages, render_id='static'):
    for index, message in enumerate(messages):
        role = 'user' if message.get('role') == 'user' else 'assistant'
        with ui.container(key=f'workspace_message_{render_id}_{index}_{role}'):
            if role == 'user':
                ui.markdown('<div class="workspace-user-bubble">'
                            + escape(str(message.get('content', '')))
                            + '</div>', unsafe_allow_html=True)
            else:
                ui.markdown('<div class="workspace-assistant-label">✦ MUMO</div>', unsafe_allow_html=True)
                # Native Markdown renders bold/list/table syntax, with raw HTML disabled.
                ui.markdown(str(message.get('content', '')))


def render_welcome(ui):
    ui.markdown('### What would you like to investigate?')
    ui.caption('Describe a target or attach a molecular structure.')
    choices = [('Docking setup', 'Help me set up a docking run', 'quick_dock'),
               ('Fate - ADME', 'Run ADME for aspirin', 'quick_fate'),
               ('Orbit - HOMO/LUMO', 'Run HOMO LUMO for aspirin', 'quick_orbit')]
    for col, (label, prompt, key) in zip(ui.columns(3), choices):
        if col.button(label, key=key, use_container_width=True):
            return prompt
    return None


def workspace_css(panel_width=384, panel_showing=False):
    reserved = int(panel_width) + 32 if panel_showing else 0
    return '''<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Outfit:wght@500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root { --workspace-sidebar:256px; --workspace-header:0px; }
.stApp { background:radial-gradient(ellipse 65vw 55vh at 58% 26%,rgba(40,110,255,.19),transparent 75%),radial-gradient(ellipse 45vw 35vh at 58% 96%,rgba(40,125,255,.13),transparent 78%),var(--bg)!important; background-attachment:fixed!important; }
[data-testid="stChatInput"] { border:1px solid rgba(85,151,255,.55)!important; box-shadow:0 0 22px rgba(55,125,255,.20),0 8px 48px rgba(35,100,240,.15)!important; }
[data-testid="stChatInput"]:focus-within { border-color:#75adff!important; box-shadow:0 0 26px rgba(55,135,255,.32),0 8px 52px rgba(35,100,240,.22)!important; }
[data-testid="stSidebar"] { width:var(--workspace-sidebar)!important; min-width:var(--workspace-sidebar)!important; max-width:var(--workspace-sidebar)!important; }
[data-testid="stSidebarContent"] { padding-top:12px!important; }
[data-testid="stSidebarUserContent"] { padding:12px 16px!important; }
[data-testid="stSidebar"] .block-container { padding-top:16px!important; }
[data-testid="stSidebar"] button { min-height:34px!important; font-size:12px!important; border-radius:10px!important; }
.workspace-brand { display:flex; align-items:center; gap:8px; padding:8px 0 20px; font:700 20px Outfit,Inter,sans-serif; color:var(--ink-strong); }
.workspace-brand small { font:500 8px Inter,sans-serif; color:var(--muted); letter-spacing:1px; }
.workspace-logo { width:30px; height:30px; border-radius:8px; background:#326ad6; color:white; display:grid; place-items:center; }
.st-key-workspace_toolbar { position:static; height:auto; padding:0; }
.st-key-workspace_toolbar button { min-height:34px!important; padding:4px 8px!important; font:500 11px Inter,sans-serif!important; }
.st-key-workspace_toolbar [data-testid="stSelectbox"] { font-size:11px; }
.workspace-engine { display:flex; align-items:center; gap:8px; white-space:nowrap; color:var(--ink); font:500 13px Inter,sans-serif; }
.workspace-engine strong { font:600 17px Outfit,Inter,sans-serif; }
.workspace-engine span { color:var(--muted); font-size:11px; }
[data-testid="stMainBlockContainer"] { padding-top:32px!important; padding-bottom:150px!important; }
[class*="st-key-workspace_message_"] { margin:8px 0 16px; }
[class*="st-key-workspace_message_"] [data-testid="stMarkdownContainer"] { font:400 14px/1.8 Inter,sans-serif!important; }
.workspace-assistant-label { font:600 12px Inter,sans-serif; color:var(--accent); margin-bottom:4px; }
.workspace-user-bubble { width:fit-content; max-width:85%; margin-left:auto; padding:14px 18px; border:1px solid #2b4162; border-radius:24px 24px 6px 24px; color:var(--ink); background:var(--input-bg); font:400 14px/1.7 Inter,sans-serif; white-space:pre-wrap; overflow-wrap:anywhere; }
.mumo-panel-header { font:600 17px Outfit,Inter,sans-serif!important; font-style:normal!important; }
.mumo-metrics { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; margin:16px 0; }
.mumo-metric { padding:12px; border:1px solid var(--border-2); border-radius:12px; background:var(--input-bg); min-width:0; }
.mumo-metric-label { display:block; color:var(--muted); font:400 10px/1.5 Inter,sans-serif; margin-bottom:6px; }
.mumo-metric-value { display:block; color:var(--ink-strong); font:600 17px/1.45 Outfit,Inter,sans-serif; overflow-wrap:anywhere; }
.st-key-mumo_panel { top:var(--workspace-header)!important; height:calc(100dvh - var(--workspace-header))!important; padding:18px!important; box-shadow:none!important; }
[data-testid="stChatInput"] { border-radius:28px!important; padding:10px 14px!important; }
[data-testid="stChatInput"] textarea { font:400 14px/1.6 Inter,sans-serif!important; }
.stApp:has([data-testid="stSidebar"][aria-expanded="false"]) .st-key-workspace_toolbar { left:0; }
@media (max-width:1100px) { .workspace-engine span { display:none; } }
@media (max-width:900px) { .st-key-workspace_toolbar { left:0; padding-left:48px; } .workspace-engine strong { font-size:13px; } }
@media (max-width:600px) { .st-key-workspace_toolbar { position:relative; height:auto; left:auto; padding:8px 0; } .st-key-workspace_toolbar [data-testid="stHorizontalBlock"] { flex-wrap:wrap; } [data-testid="stMainBlockContainer"] { padding-top:24px!important; } }
@media (prefers-reduced-motion:reduce) { *,*::before,*::after { transition:none!important; animation:none!important; } }
''' + f'''.st-key-mumo_panel {{ position:fixed; right:0; width:{int(panel_width)}px; overflow-y:auto; z-index:999; background:var(--sidebar); border-left:1px solid var(--border-2); }}
@media (max-width:900px) {{ .st-key-mumo_panel {{ width:100vw; }} }}
''' + f'''@media (min-width:1201px) {{ [data-testid="stMainBlockContainer"] {{ max-width:none!important; width:calc(100% - {reserved}px)!important; padding-left:32px!important; padding-right:32px!important; }} }}
''' + (f'''@media (min-width:1201px) {{ [data-testid="stBottomBlockContainer"] {{ margin-right:{reserved}px!important; width:calc(100% - {reserved}px)!important; }} }}''' if reserved else '') + '</style>'
