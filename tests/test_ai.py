"""Test del layer AI (D31): provider detection, patcher RFC 6902, fix loop."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from designchecker import ai, patcher


def finding(rule_id="ds.no-hardcoded-value", node_id="title", severity="error",
            message="colore hardcoded", suggestion="usa un token"):
    return SimpleNamespace(rule_id=rule_id, node_id=node_id, severity=severity,
                           message=message, suggestion=suggestion)


def screen_with_bad_color():
    return {
        "schema_version": "0.1",
        "meta": {"id": "test", "name": "Test"},
        "tokens": {"color": {"brand": {"primary": {"value": "#6C5CE7"}}}},
        "root": {
            "id": "main", "type": "Screen",
            "children": [{"id": "title", "type": "Text", "text": "Ciao",
                          "style": {"color": "#FF0000"}}],
        },
    }


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


class TestFixLoop(unittest.TestCase):
    def _validate_fn(self):
        """Simula il validatore: errore finche' il colore e' un hex hardcoded."""
        def validate_fn(scr):
            color = scr["root"]["children"][0]["style"]["color"]
            errors = [finding()] if isinstance(color, str) and color.startswith("#") else []
            return errors, []
        return validate_fn

    def test_patch_accettata(self):
        screen = screen_with_bad_color()
        ops = [{"op": "replace",
                "path": "/root/children/0/style/color",
                "value": "token:color.brand.primary"}]
        result = patcher.fix_loop(screen, [finding()], self._validate_fn(),
                                  lambda msgs: __import__("json").dumps(ops))
        self.assertTrue(result["applied"])
        self.assertEqual(result["before"], (1, 0))
        self.assertEqual(result["after"], (0, 0))
        self.assertEqual(result["screen"]["root"]["children"][0]
                         ["style"]["color"], "token:color.brand.primary")

    def test_patch_che_non_migliora_viene_rifiutata(self):
        screen = screen_with_bad_color()
        ops = [{"op": "replace",
                "path": "/root/children/0/style/color",
                "value": "#00FF00"}]  # cambia ma non risolve
        result = patcher.fix_loop(screen, [finding()], self._validate_fn(),
                                  lambda msgs: __import__("json").dumps(ops),
                                  max_attempts=1)
        self.assertFalse(result["applied"])
        self.assertEqual(screen["root"]["children"][0]["style"]["color"],
                         "#FF0000")  # invariato

    def test_risposta_sporca_con_fence(self):
        screen = screen_with_bad_color()
        ops = [{"op": "replace",
                "path": "/root/children/0/style/color",
                "value": "token:color.brand.primary"}]
        import json
        chat = lambda msgs: "Certo! Ecco:\n```json\n" + json.dumps(ops) + "\n```"
        result = patcher.fix_loop(screen, [finding()], self._validate_fn(), chat)
        self.assertTrue(result["applied"])

    def test_niente_da_correggere(self):
        screen = screen_with_bad_color()
        screen["root"]["children"][0]["style"]["color"] = "token:color.brand.primary"
        result = patcher.fix_loop(screen, [], self._validate_fn(),
                                  lambda msgs: "[]")
        self.assertFalse(result["applied"])
        self.assertIn("Niente da correggere", result["log"][-1])

    def test_retry_dopo_patch_invalida(self):
        screen = screen_with_bad_color()
        import json
        good = json.dumps([{"op": "replace",
                            "path": "/root/children/0/style/color",
                            "value": "token:color.brand.primary"}])
        risposte = iter(["non so cosa dire", good])
        result = patcher.fix_loop(screen, [finding()], self._validate_fn(),
                                  lambda msgs: next(risposte))
        self.assertTrue(result["applied"])
        self.assertTrue(any("non valida" in l for l in result["log"]))


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


class TestPrompts(unittest.TestCase):
    def test_fix_prompt_contiene_nodi_e_finding(self):
        msgs = patcher.build_fix_prompt(screen_with_bad_color(), [finding()])
        user = msgs[1]["content"]
        self.assertIn("ds.no-hardcoded-value", user)
        self.assertIn('"title"', user)
        self.assertIn("token", msgs[0]["content"])

    def test_review_prompt_in_italiano_e_consultivo(self):
        msgs = patcher.build_review_prompt(screen_with_bad_color(), [])
        self.assertIn("italiano", msgs[0]["content"])
        self.assertIn("NON proporre JSON", msgs[0]["content"])


if __name__ == "__main__":
    unittest.main()
