"""Test del layer AI: provider detection e patcher RFC 6902 / per-id-nodo."""
from __future__ import annotations

import unittest

from designchecker import ai, patcher



class TestApplyPatch(unittest.TestCase):
    def test_replace_scalare(self):
        doc = {"a": {"b": 1}}
        out = patcher.apply_patch(doc, [{"op": "replace", "path": "/a/b", "value": 2}])
        self.assertEqual(out["a"]["b"], 2)
        self.assertEqual(doc["a"]["b"], 1)  # l'originale non viene toccato

    def test_add_e_remove_array(self):
        doc = {"list": [1, 2, 3]}
        out = patcher.apply_patch(doc, [{"op": "add", "path": "/list/-", "value": 4}])
        self.assertEqual(out["list"], [1, 2, 3, 4])
        out = patcher.apply_patch(out, [{"op": "remove", "path": "/list/0"}])
        self.assertEqual(out["list"], [2, 3, 4])

    def test_escape_json_pointer(self):
        doc = {"a/b": {"~key": 1}}
        out = patcher.apply_patch(doc, [{"op": "replace", "path": "/a~1b/~0key", "value": 9}])
        self.assertEqual(out["a/b"]["~key"], 9)

    def test_replace_chiave_inesistente_errore(self):
        with self.assertRaises(patcher.PatchError):
            patcher.apply_patch({}, [{"op": "replace", "path": "/nope", "value": 1}])

    def test_troppe_operazioni_rifiutate(self):
        ops = [{"op": "add", "path": "/k%d" % i, "value": i}
               for i in range(patcher.MAX_OPS + 1)]
        with self.assertRaises(patcher.PatchError):
            patcher.apply_patch({}, ops)

    def test_operazione_non_supportata(self):
        with self.assertRaises(patcher.PatchError):
            patcher.apply_patch({}, [{"op": "move", "from": "/a", "path": "/b"}])


class TestExtractJson(unittest.TestCase):
    def test_json_puro(self):
        self.assertEqual(patcher.extract_json('[{"op":"add","path":"/a","value":1}]'),
                         [{"op": "add", "path": "/a", "value": 1}])

    def test_json_in_fence_con_prosa(self):
        text = 'Ecco la patch:\n```json\n[{"op":"remove","path":"/x"}]\n```\nFatto!'
        self.assertEqual(patcher.extract_json(text), [{"op": "remove", "path": "/x"}])

    def test_nessun_json(self):
        with self.assertRaises(patcher.PatchError):
            patcher.extract_json("mi rifiuto di produrre JSON")


class TestProviders(unittest.TestCase):
    def test_detect_ollama(self):
        def fake_http(url, payload=None, headers=None, timeout=1.5):
            if url.endswith("/api/tags"):
                return {"models": [{"name": "qwen3:8b"}, {"name": "llama3.2:3b"}]}
            raise ConnectionError(url)
        providers = ai.detect_providers({}, http_json=fake_http)
        ollama = next(p for p in providers if p.pid == "ollama")
        self.assertTrue(ollama.detected)
        self.assertIn("qwen3:8b", ollama.models)
        lm = next(p for p in providers if p.pid == "lmstudio")
        self.assertFalse(lm.detected)

    def test_detect_cloud_via_config(self):
        config = {"ai": {"keys": {"anthropic": "sk-test"}}}
        def fail(url, payload=None, headers=None, timeout=1.5):
            raise ConnectionError(url)
        providers = ai.detect_providers(config, http_json=fail)
        claude = next(p for p in providers if p.pid == "anthropic")
        self.assertTrue(claude.detected)
        self.assertTrue(claude.models)

    def test_detect_kimicode_via_config(self):
        config = {"ai": {"keys": {"kimicode": "sk-kimi-code"}}}
        def fail(url, payload=None, headers=None, timeout=1.5):
            raise ConnectionError(url)
        providers = ai.detect_providers(config, http_json=fail)
        kc = next(p for p in providers if p.pid == "kimicode")
        self.assertTrue(kc.detected)
        self.assertIn("coding", kc.base_url)
        self.assertEqual(ai.api_key_for(kc, config), "sk-kimi-code")
        # la temperature=None del template deve sopravvivere al rilevamento
        # (Kimi Code rifiuta temperature esplicita: HTTP 400)
        self.assertIsNone(kc.temperature)

    def test_detect_custom_via_config(self):
        config = {"ai": {"base_url": "https://mio-host/v1", "model": "mio-modello",
                         "keys": {"custom": "k"}}}
        def fail(url, payload=None, headers=None, timeout=1.5):
            raise ConnectionError(url)
        providers = ai.detect_providers(config, http_json=fail)
        custom = next(p for p in providers if p.pid == "custom")
        self.assertTrue(custom.detected)
        self.assertEqual(custom.base_url, "https://mio-host/v1")
        self.assertIn("mio-modello", custom.models)

    def test_custom_senza_config_non_rilevato(self):
        def fail(url, payload=None, headers=None, timeout=1.5):
            raise ConnectionError(url)
        providers = ai.detect_providers({}, http_json=fail)
        custom = next(p for p in providers if p.pid == "custom")
        self.assertFalse(custom.detected)

    def test_pick_model_preferisce_hint(self):
        p = ai.Provider("ollama", "Ollama", "A", "openai",
                        models=["llama3.2:3b", "qwen3:8b"])
        self.assertEqual(ai.pick_model(p, "patch_fix"), "qwen3:8b")

    def test_chat_openai_compatibile(self):
        seen = {}
        def fake_http(url, payload=None, headers=None, timeout=1.5):
            seen["url"] = url
            seen["payload"] = payload
            return {"choices": [{"message": {"content": "ok"}}]}
        p = ai.Provider("ollama", "Ollama", "A", "openai", "http://x/v1")
        reply = ai.chat(p, "qwen3:8b", [{"role": "user", "content": "ciao"}],
                        {}, http_json=fake_http)
        self.assertEqual(reply, "ok")
        self.assertTrue(seen["url"].endswith("/chat/completions"))
        self.assertEqual(seen["payload"]["model"], "qwen3:8b")
        self.assertEqual(seen["payload"]["temperature"], 0.2)

    def test_chat_senza_temperature_quando_none(self):
        """Kimi Code rifiuta temperature esplicita: non deve essere nel payload."""
        seen = {}
        def fake_http(url, payload=None, headers=None, timeout=1.5):
            seen["payload"] = payload
            return {"choices": [{"message": {"content": "ok"}}]}
        p = next(p for p in ai.PROVIDERS if p.pid == "kimicode")
        self.assertIsNone(p.temperature)
        ai.chat(p, "kimi-for-coding", [{"role": "user", "content": "ciao"}],
                {"ai": {"keys": {"kimicode": "k"}}}, http_json=fake_http)
        self.assertNotIn("temperature", seen["payload"])

    def test_fetch_models_fallback(self):
        def fail(url, payload=None, headers=None, timeout=1.5):
            raise ConnectionError(url)
        p = next(p for p in ai.PROVIDERS if p.pid == "kimicode")
        models = ai.fetch_models(p, {"ai": {"keys": {"kimicode": "k"}}},
                                 http_json=fail)
        self.assertIn("kimi-for-coding", models)

    def test_fetch_models_live(self):
        def fake_http(url, payload=None, headers=None, timeout=1.5):
            return {"data": [{"id": "k3"}, {"id": "kimi-for-coding"}]}
        p = next(p for p in ai.PROVIDERS if p.pid == "kimicode")
        models = ai.fetch_models(p, {"ai": {"keys": {"kimicode": "k"}}},
                                 http_json=fake_http)
        self.assertEqual(models, ["k3", "kimi-for-coding"])

    def test_chat_anthropic(self):
        seen = {}
        def fake_http(url, payload=None, headers=None, timeout=1.5):
            seen["headers"] = headers
            return {"content": [{"type": "text", "text": "ciao"}]}
        p = ai.Provider("anthropic", "Claude", "B", "anthropic",
                        "https://api.anthropic.com")
        reply = ai.chat(p, "claude-sonnet-4-6",
                        [{"role": "system", "content": "s"},
                         {"role": "user", "content": "u"}],
                        {"ai": {"keys": {"anthropic": "sk"}}}, http_json=fake_http)
        self.assertEqual(reply, "ciao")
        self.assertEqual(seen["headers"]["x-api-key"], "sk")


class TestPatchPerIdNodo(unittest.TestCase):
    """D41: il modello indirizza le patch per ID di nodo, non per indici."""

    def _screen(self):
        return {"schema_version": "0.1", "meta": {"id": "s"},
                "root": {"id": "root", "type": "Screen", "children": [
                    {"id": "card", "type": "Card", "children": [
                        {"id": "title", "type": "Text",
                         "style": {"color": "#000000"}}]}]}}

    def test_node_key_tradotti_in_path_reale(self):
        from designchecker.patcher import normalize_ops, apply_patch
        screen = self._screen()
        ops = normalize_ops(screen, [{"op": "replace", "node": "title",
                                      "key": "style/color",
                                      "value": "{color.text-primary}"}])
        self.assertEqual(ops[0]["path"],
                         "/root/children/0/children/0/style/color")
        out = apply_patch(screen, ops)
        self.assertEqual(out["root"]["children"][0]["children"][0]
                         ["style"]["color"], "{color.text-primary}")

    def test_replace_su_chiave_mancante_ora_crea(self):
        """Il bug del log di Sara: replace su chiave inesistente -> upsert."""
        from designchecker.patcher import normalize_ops, apply_patch
        screen = self._screen()  # 'card' non ha style
        ops = normalize_ops(screen, [{"op": "replace", "node": "card",
                                      "key": "style/background",
                                      "value": "{color.surface-raised}"}])
        out = apply_patch(screen, ops)
        self.assertEqual(out["root"]["children"][0]["style"]["background"],
                         "{color.surface-raised}")

    def test_nodo_sconosciuto_errore_chiaro(self):
        from designchecker.patcher import normalize_ops, PatchError
        with self.assertRaises(PatchError) as ctx:
            normalize_ops(self._screen(), [{"op": "replace",
                                            "node": "fantasma",
                                            "key": "style/color",
                                            "value": "red"}])
        self.assertIn("fantasma", str(ctx.exception))

    def test_forma_rfc6902_classica_ancora_valida(self):
        from designchecker.patcher import normalize_ops, apply_patch
        screen = self._screen()
        ops = normalize_ops(screen, [{"op": "replace",
                                      "path": "/root/children/0/children/0/style/color",
                                      "value": "red"}])
        out = apply_patch(screen, ops)
        self.assertEqual(out["root"]["children"][0]["children"][0]
                         ["style"]["color"], "red")

