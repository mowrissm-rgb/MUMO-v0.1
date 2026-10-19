import importlib.util
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


class WorkspaceUITests(unittest.TestCase):
    def test_models_menu_and_send_share_bottom_composer(self):
        import workspace_ui
        self.assertTrue(hasattr(workspace_ui, 'render_composer'))
        from streamlit.testing.v1 import AppTest
        src = str(Path(__file__).resolve().parents[1] / 'src')
        script = f'''import sys
sys.path.insert(0, {src!r})
import streamlit as st
from workspace_ui import render_composer
value = render_composer(st, placeholder='Message MUMO...', file_types=['pdb', 'sdf'])
if value is not None:
    st.session_state.submitted = value.text
'''
        app = AppTest.from_string(script, default_timeout=30).run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.sidebar.get('popover')), 0)
        self.assertTrue(any(p.proto.popover.label == 'Models' for p in app.get('popover')))
        self.assertEqual(len(app.chat_input), 1)
        app.chat_input[0].set_value('Run HOMO LUMO for aspirin').run()
        self.assertEqual(app.session_state.submitted, 'Run HOMO LUMO for aspirin')

    def test_repeated_chat_updates_keep_one_reply_before_job_status(self):
        import ast
        from streamlit.testing.v1 import AppTest
        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / 'src/mumo_chat.py').read_text(encoding='utf-8'))
        helpers = '\n'.join(ast.unparse(node) for node in tree.body
                            if isinstance(node, ast.FunctionDef)
                            and node.name in {'_refresh_chat_messages', 'say'})
        script = f'''import sys
sys.path.insert(0, {str(root / 'src')!r})
import streamlit as st
from workspace_ui import render_messages
ss = st.session_state
ss.messages = []
_persist = lambda *args: None
{helpers}
_chat_area = st.empty()
_refresh_chat_messages()
say('Preparing aspirin for HOMO/LUMO.')
with st.status('Calculating orbitals', expanded=True):
    st.write('Preparing structure')
_refresh_chat_messages()
'''
        app = AppTest.from_string(script, default_timeout=30).run()
        self.assertFalse(app.exception)
        self.assertEqual(sum(m.value == 'Preparing aspirin for HOMO/LUMO.' for m in app.markdown), 1)
        nodes = list(app.main)
        reply = next(i for i, n in enumerate(nodes) if n.type == 'markdown'
                     and n.value == 'Preparing aspirin for HOMO/LUMO.')
        progress = next(i for i, n in enumerate(nodes) if n.type == 'status')
        self.assertLess(reply, progress)

    def test_metrics_keep_values_and_escape_untrusted_content(self):
        self.assertIsNotNone(importlib.util.find_spec('workspace_ui'))
        from workspace_ui import metric_grid
        html = metric_grid([('Vina score', '-4.398 kcal/mol'), ('Target', '<script>alert(1)</script>')])
        from html.parser import HTMLParser
        class Cards(HTMLParser):
            def __init__(self):
                super().__init__()
                self.cards, self.scripts, self.text = 0, 0, []
            def handle_starttag(self, tag, attrs):
                self.cards += tag == 'article'
                self.scripts += tag == 'script'
            def handle_data(self, data):
                self.text.append(data)
        parsed = Cards()
        parsed.feed(html)
        self.assertEqual(parsed.cards, 2)
        self.assertEqual(parsed.scripts, 0)
        self.assertIn('-4.398 kcal/mol', parsed.text)

    def test_toolbar_and_message_widgets_use_real_streamlit_controls(self):
        self.assertIsNotNone(importlib.util.find_spec('workspace_ui'))
        from streamlit.testing.v1 import AppTest
        src = str(Path(__file__).resolve().parents[1] / 'src')
        script = f'''import sys
sys.path.insert(0, {src!r})
import streamlit as st
from workspace_ui import render_toolbar, render_messages
st.session_state.setdefault('messages', [{{'role': 'assistant', 'content': '**aspirin** result'}}])
cleared = render_toolbar(st, st.session_state, st.session_state.messages)
if cleared:
    st.session_state.messages = []
render_messages(st, st.session_state.messages)
'''
        app = AppTest.from_string(script, default_timeout=30).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.selectbox(key='docking_mode').value, 'Standard')
        self.assertEqual(app.selectbox(key='docking_mode').options, ['Low', 'Medium', 'High'])
        self.assertEqual(len(app.main.selectbox), 0, 'Settings must not occupy the conversation')
        self.assertEqual(len(app.sidebar.selectbox), 1)
        self.assertTrue(any(m.value == '**aspirin** result' for m in app.markdown))
        app.button(key='clear_visible_chat').click().run()
        self.assertEqual(app.session_state.messages, [])
