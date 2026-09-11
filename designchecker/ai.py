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


PROVIDERS = [
    Provider("ollama", "Ollama", "A", "openai", OLLAMA_URL + "/v1"),
    Provider("lmstudio", "LM Studio", "A", "openai", LMSTUDIO_URL + "/v1"),
    Provider("kimi", "Kimi (Moonshot)", "B", "openai",
             "https://api.moonshot.ai/v1", "MOONSHOT_API_KEY"),
    Provider("anthropic", "Claude (Anthropic)", "B", "anthropic",
             "https://api.anthropic.com", "ANTHROPIC_API_KEY"),
    Provider("openai", "OpenAI", "B", "openai",
             "https://api.openai.com/v1", "OPENAI_API_KEY"),
]

DEFAULT_MODELS = {
    "kimi": ["kimi-k2-0711-preview", "moonshot-v1-128k"],
    "anthropic": ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5"],
    "openai": ["gpt-4o", "gpt-4o-mini"],
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
        src = "env " + p.env_key if os.environ.get(p.env_key) else "config"
        p.note = f"API key ({src})"


def detect_providers(config: dict | None = None, http_json=_http_json) -> list[Provider]:
    """Rileva i provider disponibili. http_json iniettabile per i test."""
    config = config or {}
    out = []
    for tmpl in PROVIDERS:
        p = Provider(tmpl.pid, tmpl.label, tmpl.group, tmpl.style,
                     tmpl.base_url, tmpl.env_key)
        try:
            if p.pid == "ollama":
                _detect_ollama(p, http_json)
            elif p.pid == "lmstudio":
                _detect_lmstudio(p, http_json)
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
    return (os.environ.get(p.env_key)
            or (config.get("ai", {}).get("keys", {}) or {}).get(p.pid, ""))


def pick_model(p: Provider, task: str = "patch_fix") -> str:
    """Sceglie il modello piu' adatto fra quelli rilevati (euristica per nome)."""
    if not p.models:
        return ""
    for hint in MODEL_HINTS.get(task, []):
        for m in p.models:
            if hint in m.lower():
                return m
    return p.models[0]


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
    # OpenAI-compatible: Ollama /v1, LM Studio, OpenAI, Kimi
    payload = {"model": model, "messages": messages, "temperature": 0.2}
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
