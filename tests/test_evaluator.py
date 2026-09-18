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


class TestTolerantNormalize(unittest.TestCase):
    """Regressione Pay-Frame: 72 fix con 1 allucinato diventavano 0 ops."""

    def test_keeps_good_drops_bad(self):
        scr = _screen()
        fixes = [
            {"op": "replace", "node": "add-btn", "key": "props/label",
             "value": "Add funds"},
            {"op": "replace", "node": "nodo-che-non-esiste", "key": "props/label",
             "value": "X"},
        ]
        ops, dropped = patcher.normalize_ops_tolerant(scr, fixes)
        self.assertEqual(len(ops), 1)
        self.assertEqual(len(dropped), 1)
        self.assertIn("nodo-che-non-esiste", dropped[0][0])

    def test_all_bad_gives_empty_ops(self):
        scr = _screen()
        ops, dropped = patcher.normalize_ops_tolerant(
            scr, [{"op": "replace", "node": "fantasma", "key": "x", "value": 1}])
        self.assertEqual(ops, [])
        self.assertEqual(len(dropped), 1)

    def test_orchestrator_survives_bad_fixes(self):
        from designchecker.evaluator.orchestrator import run_propose
        scr = _screen()

        def chat(msgs):
            txt = str(msgs)
            if "classificatore di ruolo" in txt:
                return '{"role": "wallet-home", "user_goal": "g"}'
            if "padre valutatore" in txt:
                return "[]"
            if "Ricercatore UX" in txt:
                return '{"queries": []}'
            return ('[{"node": "add-btn", "key": "props/label", "value": "A"},'
                    ' {"node": "fantasma", "key": "props/label", "value": "B"}]')
        res = run_propose(scr, [], chat_fn=chat, search_fn=None, baseline=False)
        self.assertTrue(len(res["ops"]) >= 1)
        self.assertTrue(any("scartati" in l for l in res["log"]))


class TestFocusedFixes(unittest.TestCase):
    def test_prompt_asks_five(self):
        from designchecker.evaluator.subagents import SUB_SYSTEM
        self.assertIn("max 5", SUB_SYSTEM)

    def test_parse_caps_padding(self):
        many = [{"node": f"n{i}", "key": "props/label", "value": "x"}
                for i in range(20)]
        import json as _json
        out = S.parse_sub_fixes(_json.dumps(many))
        self.assertLessEqual(len(out), 6)


class TestTokenOrdering(unittest.TestCase):
    def test_used_tokens_first(self):
        from designchecker.evaluator.orchestrator import _token_block
        scr = _screen()  # usa {color.surface} e {color.text-primary}
        block = _token_block(["color.brand.primary", "color.surface",
                              "spacing.4", "color.text-primary"],
                             {p: p for p in ["color.brand.primary", "color.surface",
                                             "spacing.4", "color.text-primary"]},
                             scr)
        first = block.splitlines()[1]
        self.assertIn("color.surface", first)


class TestWebsearch(unittest.TestCase):
    FIXTURE = ('<div class="result"><div class="result__body">'
               '<a rel="nofollow" class="result__a" '
               'href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fwallet&amp;rut=x">'
               'Wallet UX guide</a>'
               '<a class="result__snippet" href="x">snippet testo</a>'
               '</div></div>')

    def test_parse_fixture_no_network(self):
        from designchecker.evaluator.websearch import parse_duckduckgo
        out = parse_duckduckgo(self.FIXTURE)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["url"], "https://example.com/wallet")
        self.assertIn("Wallet", out[0]["title"])

    def test_search_never_raises(self):
        from designchecker.evaluator import websearch
        self.assertEqual(websearch.duckduckgo_search("   "), [])
        self.assertEqual(websearch.parse_duckduckgo(""), [])


class TestTolerantApply(unittest.TestCase):
    """Bug Pay-Frame #2: un remove su path inesistente bocciava 25 ops."""

    def test_remove_missing_is_noop_drop(self):
        scr = _screen()
        ops = [
            {"op": "replace", "path": "/root/id", "value": "home2"},
            {"op": "remove", "path": "/root/props/enabled"},
        ]
        patched, applied, dropped = patcher.apply_patch_tolerant(scr, ops)
        self.assertEqual(len(applied), 1)
        self.assertEqual(len(dropped), 1)
        self.assertEqual(patched["root"]["id"], "home2")

    def test_gate_applies_rest_despite_bad_remove(self):
        from designchecker.validator import Finding
        scr = _screen()
        ops = [
            {"op": "replace", "path": "/root/id", "value": "home2"},
            {"op": "remove", "path": "/root/props/enabled"},
        ]

        def validate_fn(s):
            # l'id fixato toglie un errore finto: la patch deve passare
            if s["root"]["id"] == "home2":
                return [], []
            return [Finding("r", "error", "n", "m")], []
        gate = patcher.gate_propose(scr, ops, validate_fn)
        self.assertTrue(gate["applied"])
        self.assertEqual(len(gate["dropped"]), 1)


class TestKeyAllowlist(unittest.TestCase):
    def test_schema_keys_pass(self):
        scr = _screen()
        fixes = [
            {"op": "replace", "node": "add-btn", "key": "props/label", "value": "X"},
            {"op": "replace", "node": "add-btn", "key": "a11y/label", "value": "Y"},
            {"op": "replace", "node": "add-btn", "key": "layout/gap", "value": 8},
        ]
        ops, dropped = patcher.normalize_ops_tolerant(scr, fixes)
        self.assertEqual(len(ops), 3)
        self.assertEqual(dropped, [])

    def test_invented_keys_dropped(self):
        scr = _screen()
        fixes = [
            {"op": "replace", "node": "add-btn", "key": "style/background-pressed",
             "value": "{color.brand.primary}"},
            {"op": "replace", "node": "add-btn", "key": "layout/height", "value": "44"},
            {"op": "replace", "node": "add-btn", "key": "props/enabled", "value": True},
        ]
        ops, dropped = patcher.normalize_ops_tolerant(scr, fixes)
        self.assertEqual(ops, [])
        self.assertEqual(len(dropped), 3)


class TestGateNoRegression(unittest.TestCase):
    """Pay-Frame: 23->20 con 1 nuovo errore contrasto veniva accettata."""

    def test_rejects_patch_with_new_error(self):
        from designchecker.validator import Finding
        before = [Finding("a", "error", "n1", "m"),
                  Finding("b", "error", "n2", "m"),
                  Finding("c", "error", "n3", "m"),
                  Finding("d", "error", "n4", "m"),
                  Finding("e", "error", "n5", "m")]
        after = [Finding("a", "error", "n1", "m"),
                 Finding("b", "error", "n2", "m"),
                 Finding("NEW", "error", "nx", "m")]
        calls = {"n": 0}

        def vf(s):
            calls["n"] += 1
            return (before, []) if calls["n"] == 1 else (after, [])
        gate = patcher.gate_propose({"root": {"id": "r"}},
                                    [{"op": "add", "path": "/root/x", "value": 1}], vf)
        self.assertFalse(gate["applied"])
        self.assertIn("regressione", gate["detail"])

    def test_rejects_trivial_improvement(self):
        from designchecker.validator import Finding
        b10 = [Finding("e", "error", f"n{i}", "m") for i in range(10)]
        a9 = [Finding("e", "error", f"n{i}", "m") for i in range(9)]
        calls = {"n": 0}

        def vf(s):
            calls["n"] += 1
            return (b10, []) if calls["n"] == 1 else (a9, [])
        gate = patcher.gate_propose({"root": {"id": "r"}},
                                    [{"op": "add", "path": "/root/x", "value": 1}], vf)
        self.assertFalse(gate["applied"])

    def test_drops_culprit_keeps_good(self):
        """Pay-Frame 16/09: 2 hex su nodi gia' tokenizzati uccidevano 10 fix
        buoni. Il gate scarta solo le colpevoli e accetta il resto."""
        from designchecker.validator import Finding
        scr = {"root": {"id": "r", "props": {}}}
        ops = [
            {"op": "add", "path": "/root/props/fixed", "value": True},
            {"op": "add", "path": "/root/props/broken", "value": True},
        ]

        def vf(s):
            errs = []
            if not s["root"].get("props", {}).get("fixed"):
                errs.append(Finding("a", "error", "n1", "m"))
            if s["root"].get("props", {}).get("broken"):
                errs.append(Finding("NEW", "error", "nx", "m"))
            return errs, []
        gate = patcher.gate_propose(scr, ops, vf)
        self.assertTrue(gate["applied"])
        self.assertEqual(gate["before"], (1, 0))
        self.assertEqual(gate["after"], (0, 0))
        self.assertTrue(any("gate:" in d.get("reason", "") for d in gate["dropped"]))

    def test_rejects_when_all_ops_are_culprits(self):
        from designchecker.validator import Finding
        scr = {"root": {"id": "r", "props": {}}}

        def vf(s):
            if s["root"].get("props", {}).get("broken"):
                return [Finding("NEW", "error", "nx", "m")], []
            return [Finding("a", "error", "n1", "m")], []
        gate = patcher.gate_propose(
            scr, [{"op": "add", "path": "/root/props/broken", "value": True}], vf)
        self.assertFalse(gate["applied"])
        self.assertIn("regressione", gate["detail"])


class TestBlindQuality(unittest.TestCase):
    """D44: la qualita' puo' venire dal padre (copertura diagnosi cieca),
    non solo dal conteggio. Safety invariata: mai nuovi errori/warning."""

    def _scr(self):
        return {"root": {"id": "r", "children": [
            {"id": "card", "type": "Stack", "children": [
                {"id": "title", "type": "Text",
                 "props": {"content": "Hi", "variant": "body"}},
                {"id": "cta", "type": "Button",
                 "props": {"label": "Go", "min_height": 48}}]}]}}

    def test_blind_coverage_accepts_without_count_move(self):
        from designchecker.validator import Finding
        scr = self._scr()
        blind = [{"node": "card", "issue": "x"}, {"node": "cta", "issue": "y"}]
        ops = [
            {"op": "add", "path": "/root/children/0/children/0/a11y/label",
             "value": "Hi there"},
            {"op": "add", "path": "/root/children/0/children/1/a11y/label",
             "value": "Go now"},
        ]

        def vf(s):
            return [Finding("a", "error", "elsewhere", "m")], []
        gate = patcher.gate_propose(scr, ops, vf, blind=blind)
        self.assertTrue(gate["applied"])
        self.assertTrue(gate["quality"].startswith("padre"))
        self.assertEqual(gate["before"], gate["after"])

    def test_blind_coverage_counts_subtree(self):
        from designchecker.validator import Finding
        scr = self._scr()
        # cieco su card+cta, fix solo sul figlio cta: copre entrambi
        blind = [{"node": "card", "issue": "x"}, {"node": "cta", "issue": "y"}]
        ops = [{"op": "add", "path": "/root/children/0/children/1/a11y/label",
                "value": "Go now"}]

        def vf(s):
            return [Finding("a", "error", "elsewhere", "m")], []
        gate = patcher.gate_propose(scr, ops, vf, blind=blind)
        self.assertTrue(gate["applied"])
        self.assertIn("card", gate["coverage"])

    def test_blind_low_coverage_still_rejects(self):
        from designchecker.validator import Finding
        scr = self._scr()
        # ciechi su nodi mai toccati: copertura 0
        blind = [{"node": "ghost1", "issue": "x"},
                 {"node": "ghost2", "issue": "y"},
                 {"node": "ghost3", "issue": "z"}]
        ops = [{"op": "add", "path": "/root/children/0/children/0/a11y/label",
                "value": "Hi there"}]

        def vf(s):
            return [Finding("a", "error", "elsewhere", "m")], []
        gate = patcher.gate_propose(scr, ops, vf, blind=blind)
        self.assertFalse(gate["applied"])
        self.assertIn("copertura padre 0/3", gate["detail"])

    def test_blind_never_overrides_safety(self):
        from designchecker.validator import Finding
        scr = self._scr()
        # la colpevole viene scartata, ma il resto copre 1/3: comunque rifiuto
        blind = [{"node": "card", "issue": "x"},
                 {"node": "other", "issue": "y"},
                 {"node": "third", "issue": "z"}]
        ops = [{"op": "add", "path": "/root/children/0/children/0/a11y/label",
                "value": "Hi there"},
               {"op": "add", "path": "/root/props/broken", "value": True}]

        def vf(s):
            errs = [Finding("a", "error", "elsewhere", "m")]
            if s["root"].get("props", {}).get("broken"):
                errs.append(Finding("NEW", "error", "nx", "m"))
            return errs, []
        gate = patcher.gate_propose(scr, ops, vf, blind=blind)
        self.assertFalse(gate["applied"])
        self.assertIn("copertura padre 1/3", gate["detail"])


class TestCopyFrameCofix(unittest.TestCase):
    """Pay-Frame: 'Add 15 $' -> 'Add $15 to wallet' con w:70 = troncato."""

    def test_longer_copy_expands_frame(self):
        scr = {"root": {"id": "r", "children": [
            {"id": "cta", "type": "Text",
             "props": {"content": "Add 15 $", "variant": "body"},
             "layout": {"frame": {"x": 36, "y": 8, "w": 70, "h": 22}}}]}}
        fixes = [{"op": "replace", "node": "cta", "key": "props/content",
                  "value": "Add $15 to wallet"}]
        ops, _ = patcher.normalize_ops_tolerant(scr, fixes)
        self.assertTrue(any("layout/frame" in o["path"] for o in ops))

    def test_min_height_string_coerced(self):
        scr = {"root": {"id": "r", "children": [{"id": "b", "type": "Button"}]}}
        ops = patcher.normalize_ops(
            scr, [{"op": "replace", "node": "b", "key": "props/min_height",
                   "value": "50"}])
        self.assertEqual(ops[0]["value"], 50)


class TestCoherencePolish(unittest.TestCase):
    def test_drops_redundant_container_bg(self):
        from designchecker.evaluator.orchestrator import _coherence_polish
        scr = {"root": {"id": "r", "children": [
            {"id": "wrap", "type": "Stack", "children": [
                {"id": "inner", "type": "Stack"}]}]}}
        fixes = [
            {"op": "replace", "node": "wrap", "key": "style/background",
             "value": "{color.brand.primary}"},
            {"op": "replace", "node": "inner", "key": "style/background",
             "value": "{color.brand.primary}"},
        ]
        kept, _ = _coherence_polish(scr, fixes)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["node"], "inner")

    def test_duplicate_ids_expand_to_twins(self):
        scr = {"root": {"id": "r", "children": [
            {"id": "bg", "type": "Stack"},
            {"id": "bg", "type": "Stack"}]}}
        ops = patcher.normalize_ops(
            scr, [{"op": "replace", "node": "bg", "key": "style/background",
                   "value": "{color.surface}"}])
        self.assertEqual(len(ops), 2)


if __name__ == "__main__":
    unittest.main()
