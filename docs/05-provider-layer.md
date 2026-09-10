# 05 — Provider Layer: scelta del modello AI

## Principio

DesignChecker ha bisogno dell'LLM solo per tre task:

| Task | Vision? | Structured output? | Modello piccolo locale basta? |
|---|---|---|---|
| **Generazione/redesign** schermata | no | sì, + ragionamento spaziale | no, serve modello capace |
| **Interpretazione prompt** ("primario verde salvia") | no | sì, JSON rigoroso | spesso sì, specie se fine-tunato |
| **Import da screenshot** | **sì, obbligatoria** | sì | solo modelli vision |

Tutto il resto (validatore, rules engine, renderer) è deterministico e non tocca nessuna AI. Quindi l'LLM è un componente intercambiabile dietro adapter (OpenAI-compatible copre quasi tutti: Ollama, LM Studio, OpenRouter, Moonshot/Kimi; Anthropic via adapter proprio). Opzione: appoggiarsi a LiteLLM o Vercel AI SDK invece di riscrivere gli adapter.

## Rilevamento all'avvio di `dc`

### Categoria A — Server locali con API (caso pulito)
Ollama (`localhost:11434`) e LM Studio espongono API REST con lista dei modelli installati e loro capacità. `dc` li interroga: se rispondono, modelli e capabilities sono subito disponibili. Zero configurazione.

### Categoria B — CLI agent (Kimi Code, Codex, Claude Code, OpenCode)
**Non** vengono chiamati come subprocess (fragile: output non strutturato, errori non intercettabili). `dc` rileva la presenza del tool e delle sue credenziali → propone di **riusare le credenziali per parlare direttamente con l'API del provider**. Stesso abbonamento, comunicazione controllata.

### Categoria C — Cloud da configurare
Provider disponibili via API key inserita dall'utente.

## Il menu (decisione D7)

```
$ dc

🔍 Rilevamento modelli disponibili...

 ✅ MODELLO UNICO — copre tutte le funzioni di DesignChecker
 ▸ Kimi K2            (cloud · credenziali da Kimi Code)
 ▸ Claude Sonnet      (cloud · credenziali da Claude Code)
 ▸ qwen2.5vl:32b      (locale · Ollama · 100% privato · generazione: buona)

 ⚙️  COMBINAZIONE — scegli un modello per ogni funzione
 ▸ Configura: generazione + interpretazione prompt + vision separatamente
```

Due modalità: **modello unico** (solo modelli `full_coverage: true`) o **combinazione** (routing per task: es. cloud per generare, LoRA locale per i prompt — uso quotidiano gratis e privato).

## Capabilities matrix (decisione D8)

Tre fonti, in ordine:

1. **Modelli locali** → rilevamento runtime via API Ollama (vision, tools, context length).
2. **Modelli cloud** → registry `models.yaml` versionato, stessa filosofia del rules engine:

```yaml
- id: kimi-k2
  provider: moonshot
  capabilities: [generation, structured_output, vision]
  context: 256k
  full_coverage: true
  generation_quality: excellent   # basic | good | excellent
```

3. **Modelli sconosciuti** (fine-tune, novità) → **probe test** ~30s: micro-prompt con output JSON obbligatorio + micro-immagine di prova. Classifica il modello automaticamente.

## Regole di comportamento

- Il registry distingue "può fare tutto" da "può fare tutto *bene*" (`generation_quality`), mostrato nel menu.
- Se il modello scelto non copre un task (es. no vision + import da screenshot): messaggio-guida esplicito, mai errore generico.
- Config salvata in `~/.designchecker/config.json`; flag `--model` per override al volo.
- **Qualsiasi output LLM passa dal validatore** prima di toccare lo screen JSON (decisione D9) — rete di sicurezza che rende sicuri i modelli piccoli.
- Il validatore è anche **metrica di test per il fine-tuning**: qualità dei LoRA verificabile automaticamente.
