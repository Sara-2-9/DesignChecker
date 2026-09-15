"""Test flusso padre+figli (branch propose): classify, research, merge, gate."""
import unittest

from designchecker import patcher
from designchecker.evaluator import classify as C
from designchecker.evaluator import research_agentic as R
from designchecker.evaluator import subagents as S
from designchecker.evaluator.orchestrator import run_propose
from designchecker.evaluator.vision import has_vision, user_content_with_image


def _screen():
    return {
        "schema_version": "0.1.0",
        "meta": {"id": "home", "name": "Home"},
        "root": {
            "id": "home", "type": "Screen",
            "layout": {"safe_area": True}, "style": {"background": "{color.surface}"},
            "children": [
                {"id": "balance-value", "type": "Text",
                 "props": {"content": "$25.00", "variant": "title"},
                 "style": {"color": "{color.text-primary}"}},
                {"id": "add-btn", "type": "Button",
                 "props": {"label": "Add funds", "min_height": 48},
                 "a11y": {"role": "button", "label": "Add funds"}},
            ],
        },
    }


class FakeProvider:
    def __init__(self, pid):
        self.pid = pid


class TestVision(unittest.TestCase):
    def test_cloud_has_vision(self):
        self.assertTrue(has_vision(FakeProvider("openai"), "gpt-4o"))

    def test_plain_text_without_preview(self):
        self.assertEqual(user_content_with_image("ciao", None), "ciao")

    def test_multimodal_with_preview(self):
        out = user_content_with_image("ciao", "QUJD")
        self.assertIsInstance(out, list)
        self.assertTrue(any(p.get("type") == "image_url" for p in out))


class TestClassify(unittest.TestCase):
    def test_parse_valid(self):
        raw = '{"role": "wallet-home", "user_goal": "Mostrare saldo", "confidence": 0.9}'
        out = C.parse_classify(raw)
        self.assertEqual(out["role"], "wallet-home")

    def test_parse_fallback(self):
        out = C.parse_classify("non json")
        self.assertEqual(out["role"], "generic-screen")

    def test_heuristic_wallet(self):
        out = C.heuristic_role(_screen())
        self.assertIn(out["role"], ("wallet-home", "generic-screen", "expense-list"))

    def test_classify_with_stub(self):
        scr = _screen()
        out = C.classify(scr, lambda m: '{"role":"profile-screen","user_goal":"Mostrare profilo"}')
        self.assertEqual(out["role"], "profile-screen")


class TestResearch(unittest.TestCase):
    def test_verify_drops_fake_urls(self):
        valid, dropped = R.verify_sources([
            {"title": "A", "url": "https://example.com/a", "snippet": "x"},
            {"title": "B", "url": "non-un-url", "snippet": "y"},
            {"title": "A2", "url": "https://example.com/a", "snippet": "dup"},
        ])
        self.assertEqual(len(valid), 1)
        self.assertEqual(len(dropped), 2)

    def test_queries_for_role(self):
        qs = R.queries_for_role("profile-screen", "ios")
        self.assertTrue(any("profile" in q for q in qs))

    def test_agentic_uses_search_fn(self):
        def chat_fn(msgs):
            return '{"queries": ["wallet home UX 2026"]}'
        calls = []

        def search_fn(q):
            calls.append(q)
            return [{"title": "T", "url": "https://example.com/t", "snippet": "s"}]
        res = R.agentic_research("wallet-home", chat_fn, search_fn, log=[])
        self.assertEqual(len(res["sources"]), 1)
        self.assertTrue(calls)


class TestSubagents(unittest.TestCase):
    def test_parse_fixes(self):
        raw = ('[{"node": "add-btn", "key": "props/label", "op": "replace", '
               '"value": "Add $10"}]')
        self.assertEqual(len(S.parse_sub_fixes(raw)), 1)

    def test_parse_rejects_without_node(self):
        self.assertEqual(S.parse_sub_fixes('[{"op": "replace"}]'), [])
        self.assertEqual(S.parse_sub_fixes('niente json'), [])

    def test_six_agents_defined(self):
        self.assertEqual(len(S.SUBAGENTS), 6)


class TestOrchestrator(unittest.TestCase):
    def _chat(self, messages):
        txt = str(messages)
        if "classificatore di ruolo" in txt:
            return '{"role": "wallet-home", "user_goal": "Mostrare saldo e aggiungere fondi"}'
        if "diagnosi cieca" in txt or "padre valutatore" in txt:
            return '[{"node": "add-btn", "issue": "CTA poco evidente"}]'
        if "Ricercatore UX" in txt or "queries" in txt:
            return '{"queries": ["wallet home UX best practices 2026"]}'
        return ('[{"node": "add-btn", "key": "props/label", "op": "replace", '
                '"value": "Add funds", "why": "information scent"}]')

    def test_full_run_offline(self):
        scr = _screen()
        res = run_propose(scr, findings=[], chat_fn=self._chat, search_fn=None,
                          token_paths=["color.text-primary"], baseline=True)
        self.assertEqual(res["role"]["role"], "wallet-home")
        self.assertTrue(len(res["ops"]) >= 1)
        self.assertTrue(any("call sub-agent" in l for l in res["log"]))
        self.assertTrue(any("padre merge" in l for l in res["log"]))

    def test_baseline_off(self):
        scr = _screen()
        res = run_propose(scr, findings=[], chat_fn=self._chat, search_fn=None,
                          baseline=False)
        self.assertTrue(any("baseline disattivata" in l for l in res["log"]))


class TestProposeGate(unittest.TestCase):
    def test_rejects_worse_patch(self):
        from designchecker.validator import Finding
        scr = _screen()
        ops = [{"op": "replace", "path": "/root/id", "value": "x"}]

        def validate_fn(s):
            return [Finding("r", "error", "n", "m")], []
        gate = patcher.gate_propose(scr, ops, validate_fn)
        self.assertFalse(gate["applied"])

    def test_rejects_too_many_ops(self):
        scr = _screen()
        ops = [{"op": "replace", "path": "/root/id", "value": i} for i in range(85)]

        def validate_fn(s):
            return [], []
        gate = patcher.gate_propose(scr, ops, validate_fn)
        self.assertFalse(gate["applied"])
        self.assertIn("troppe operazioni", gate["detail"])


if __name__ == "__main__":
    unittest.main()
