"""Layer provider AI (D31): rilevamento, probe e chiamate chat.

DesignChecker non ha un provider preferito: l'utente sceglie il modello.
Gruppo A — locale: Ollama, LM Studio (rilevati via HTTP su localhost).
Gruppo B — cloud: Kimi, Claude, OpenAI (API key da variabile d'ambiente
o da ~/.designchecker/config.json, mai richiesta a riga di comando in chiaro).

I CLI agent installati (claude, gemini, ...) vengono solo SEGNALATI come
presenti: DesignChecker non li esegue come subprocess — sono fonti di
credenziali dell'utente, non backend del tool.

Solo stdlib: nessuna dipendenza aggiuntiva.
"""
from __future__ import annotations

import json
import os
import shutil
import urllib.error
import urllib.request
from dataclasses import dataclass, field

OLLAMA_URL = "http://localhost:11434"
LMSTUDIO_URL = "http://localhost:1234"
DETECT_TIMEOUT = 1.5
CHAT_TIMEOUT = 120

# Modelli consigliati per attivita' che richiedono JSON affidabile (patch)
# o ragionamento qualitativo (review). Match per sottostringa sul nome
# rilevato (es. "qwen3:8b-instruct" matcha "qwen3"). Fallback: primo disponibile.
MODEL_HINTS = {
    "patch_fix": ["qwen3", "qwen2.5-coder", "deepseek-coder", "gpt-4o",
                  "claude-sonnet", "claude-opus", "kimi"],
    "review": ["qwen3", "deepseek-r1", "gpt-4o", "claude-sonnet",
               "claude-opus", "kimi"],
}


@dataclass
class Provider:
    pid: str
    label: str
    group: str            # "A" locale, "B" cloud
    style: str            # "openai" | "anthropic"
    base_url: str = ""
    env_key: str = ""
    models: list = field(default_factory=list)
    detected: bool = False
    note: str = ""
    alt_env: str = ""     # seconda variabile d'ambiente accettata
    temperature: float | None = 0.2  # None = non inviarla (es. Kimi Code: solo default)


PROVIDERS = [
    Provider("ollama", "Ollama", "A", "openai", OLLAMA_URL + "/v1"),
    Provider("lmstudio", "LM Studio", "A", "openai", LMSTUDIO_URL + "/v1"),
    # Kimi Code (abbonamento): rifiuta temperature != default (HTTP 400).
    # Host internazionale alternativo: https://api.kimi.ai/coding/v1
    Provider("kimicode", "Kimi Code (abbonamento)", "B", "openai",
             "https://api.kimi.com/coding/v1", "KIMI_API_KEY",
             alt_env="KIMI_CODE_API_KEY", temperature=None),
    Provider("kimi", "Kimi API (pay-as-you-go)", "B", "openai",
             "https://api.moonshot.ai/v1", "MOONSHOT_API_KEY"),
    Provider("anthropic", "Claude (Anthropic)", "B", "anthropic",
             "https://api.anthropic.com", "ANTHROPIC_API_KEY"),
    Provider("openai", "OpenAI", "B", "openai",
             "https://api.openai.com/v1", "OPENAI_API_KEY"),
    Provider("huggingface", "HuggingFace Inference", "B", "openai",
             "https://router.huggingface.co/v1", "HF_TOKEN"),
    Provider("custom", "Altro endpoint OpenAI-compatibile", "B", "openai"),
]

DEFAULT_MODELS = {
    # Kimi Code: model ID ufficiali dell'endpoint abbonamento (docs kimi.com/code)
    "kimicode": ["kimi-for-coding", "k3-256k"],
    "kimi": ["kimi-k3", "kimi-k2.6"],
    "anthropic": ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5"],
    "openai": ["gpt-4o", "gpt-4o-mini"],
    "huggingface": ["Qwen/Qwen3-32B", "deepseek-ai/DeepSeek-R1:fastest",
                    "meta-llama/Llama-3.3-70B-Instruct"],
}


def _http_json(url: str, payload: dict | None = None, headers: dict | None = None,
               timeout: float = DETECT_TIMEOUT) -> dict:
    """GET (payload None) o POST JSON. Solleva eccezione su errore."""
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _detect_ollama(p: Provider, http_json) -> None:
    data = http_json(OLLAMA_URL + "/api/tags")
    p.models = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
    p.detected = bool(p.models)
    if p.detected:
        p.note = f"{len(p.models)} modelli locali"


def _detect_lmstudio(p: Provider, http_json) -> None:
    data = http_json(LMSTUDIO_URL + "/v1/models")
    p.models = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
    p.detected = bool(p.models)
    if p.detected:
        p.note = f"{len(p.models)} modelli caricati"


def _detect_cloud(p: Provider, config: dict) -> None:
    """Cloud: 'rilevato' se la API key e' in env o nel config."""
    key = api_key_for(p, config)
    if key:
        p.detected = True
        p.models = list(DEFAULT_MODELS.get(p.pid, []))
        env_hit = next((e for e in (p.env_key, p.alt_env)
                        if e and os.environ.get(e)), None)
        p.note = f"API key ({'env ' + env_hit if env_hit else 'config'})"


def _detect_custom(p: Provider, config: dict) -> None:
    """Endpoint personalizzato: rilevato se base_url + chiave sono nel config."""
    ai_cfg = config.get("ai", {})
    if ai_cfg.get("base_url") and api_key_for(p, config):
        p.detected = True
        p.base_url = ai_cfg["base_url"]
        if ai_cfg.get("model"):
            p.models = [ai_cfg["model"]]
        p.note = f"endpoint personalizzato ({ai_cfg['base_url']})"


def detect_providers(config: dict | None = None, http_json=_http_json) -> list[Provider]:
    """Rileva i provider disponibili. http_json iniettabile per i test."""
    config = config or {}
    out = []
    for tmpl in PROVIDERS:
        p = Provider(tmpl.pid, tmpl.label, tmpl.group, tmpl.style,
                     tmpl.base_url, tmpl.env_key, alt_env=tmpl.alt_env,
                     temperature=tmpl.temperature)
        try:
            if p.pid == "ollama":
                _detect_ollama(p, http_json)
            elif p.pid == "lmstudio":
                _detect_lmstudio(p, http_json)
            elif p.pid == "custom":
                _detect_custom(p, config)
            else:
                _detect_cloud(p, config)
        except Exception:
            p.detected = False
        out.append(p)
    return out


def cli_agents_present() -> list[str]:
    """CLI agent installati: solo informativi, mai eseguiti da DesignChecker."""
    return [name for name in ("claude", "gemini", "codex") if shutil.which(name)]


def api_key_for(p: Provider, config: dict) -> str:
    for env in (p.env_key, p.alt_env):
        if env and os.environ.get(env):
            return os.environ[env]
    return (config.get("ai", {}).get("keys", {}) or {}).get(p.pid, "")


def pick_model(p: Provider, task: str = "patch_fix") -> str:
    """Sceglie il modello piu' adatto fra quelli rilevati (euristica per nome)."""
    if not p.models:
        return ""
    for hint in MODEL_HINTS.get(task, []):
        for m in p.models:
            if hint in m.lower():
                return m
    return p.models[0]


def fetch_models(p: Provider, config: dict | None = None,
                 http_json=_http_json) -> list[str]:
    """Recupera i modelli live da GET {base_url}/models (OpenAI-compatible).
    Fallback: i default noti. Mai eccezioni."""
    config = config or {}
    if p.style == "openai" and p.base_url:
        try:
            headers = {}
            key = api_key_for(p, config)
            if key:
                headers["Authorization"] = f"Bearer {key}"
            data = http_json(p.base_url.rstrip("/") + "/models", None,
                             headers, 5)
            models = [m.get("id") for m in data.get("data", []) if m.get("id")]
            if models:
                return models
        except Exception:
            pass
    return list(DEFAULT_MODELS.get(p.pid, []))


def chat(p: Provider, model: str, messages: list, config: dict | None = None,
         timeout: int = CHAT_TIMEOUT, http_json=_http_json) -> str:
    """Chiamata chat completion. Ritorna il testo della risposta."""
    config = config or {}
    if p.style == "anthropic":
        payload = {
            "model": model,
            "max_tokens": 4096,
            "messages": [{"role": m["role"], "content": m["content"]}
                         for m in messages if m["role"] != "system"],
        }
        sys_msg = next((m["content"] for m in messages if m["role"] == "system"), None)
        if sys_msg:
            payload["system"] = sys_msg
        data = http_json(p.base_url + "/v1/messages", payload, {
            "x-api-key": api_key_for(p, config),
            "anthropic-version": "2023-06-01",
        }, timeout)
        return "".join(b.get("text", "") for b in data.get("content", []))
    # OpenAI-compatible: Ollama /v1, LM Studio, OpenAI, Kimi, HuggingFace
    payload = {"model": model, "messages": messages}
    if p.temperature is not None:
        payload["temperature"] = p.temperature
    headers = {}
    key = api_key_for(p, config)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    data = http_json(p.base_url.rstrip("/") + "/chat/completions", payload,
                     headers, timeout)
    return data["choices"][0]["message"]["content"] or ""


def probe(p: Provider, model: str, config: dict | None = None,
          timeout: int = 20) -> tuple[bool, str]:
    """Test minimo: il provider risponde? Ritorna (ok, dettaglio)."""
    try:
        reply = chat(p, model, [{"role": "user", "content": "Rispondi solo: ok"}],
                     config, timeout)
        return (bool(reply.strip()), reply.strip()[:60] or "risposta vuota")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:120]
        except Exception:
            pass
        return (False, f"HTTP {e.code}: {body}")
    except Exception as e:
        return (False, str(e)[:120])
