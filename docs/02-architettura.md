# 02 — Architettura

## Vista d'insieme

```
┌──────────────────────────────────────────────────────────┐
│ SUPERFICI DI EDITING (due, paritarie)                    │
│  A. CLI / prompt ────────── B. Plugin Figma              │
│     (utente tecnico)           (tela visuale)            │
└──────────────┬───────────────────────┬───────────────────┘
               │  proposte di modifica  │
               ▼                       ▼
┌──────────────────────────────────────────────────────────┐
│ CORE — screen JSON + tokens.json (DTCG) = SOURCE OF TRUTH│
│   ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  │
│   │ VALIDATORE  │  │ RULES ENGINE │  │ GENERATORE LLM │  │
│   │ error/warn  │  │ regole YAML  │  │ compone/rediseg│ │
│   └─────────────┘  └──────────────┘  └───────┬────────┘  │
│   ┌─────────────────────────────────┐        │           │
│   │ IMPORTER: screenshot/codice     │        │           │
│   │ → screen JSON + audit           │        │           │
│   └─────────────────────────────────┘        │           │
│                         ▲                    │           │
│              ┌──────────┴────────────────────┘           │
│              │ PROVIDER LAYER                            │
│              │ adapter: ollama / lmstudio / openai /     │
│              │ anthropic / kimi / openrouter …           │
│              │ + rilevamento automatico                  │
│              │ + capabilities matrix + routing per task  │
│              └───────────────────────────────────────────┘
└──────────────┬───────────────────────┬───────────────────┘
               ▼                       ▼
┌──────────────────────┐   ┌──────────────────────────────┐
│ RENDERER Expo        │   │ RENDERER Figma               │
│ component library RN │   │ plugin: frame nativi,        │
│ → Expo Go/simulatore │   │ variabili, annotation errori │
└──────────────────────┘   └──────────────────────────────┘
```

## I componenti

### CORE (deterministico, nessuna AI)

| Componente | Responsabilità |
|---|---|
| **Screen JSON + tokens.json** | Unica fonte di verità. Token in formato W3C DTCG 2025.10. Schema: `docs/04`. |
| **Rules engine** | Regole ufficiali come dati YAML versionati. Dettagli: `docs/03`. |
| **Validatore** | Controlla ogni versione dello screen JSON contro le regole. Output: lista di `error` (bloccanti) e `warning` (euristici), ognuno con fonte citata. |
| **Importer** | Screenshot e/o codice `.tsx` → screen JSON (via modello vision) → audit delle violazioni. |
| **Generatore/interprete** | Usa l'LLM via provider layer per: proporre schermate dal brief, ridisegnare dall'audit, interpretare prompt utente ("primario verde salvia") in modifiche al JSON. **Compone solo con la component library**, non disegna libero. |

### PROVIDER LAYER

Astrazione dei modelli AI: l'utente sceglie il modello, il core non sa quale è. Dettagli completi: `docs/05`.

### RENDERER (due, dallo stesso JSON)

| Renderer | Meccanismo |
|---|---|
| **Expo** | Component library React Native conforme per costruzione (Pressable, SafeAreaView/useSafeAreaInsets, FlatList, StyleSheet.create, Expo Router, TypeScript). Hot reload su Expo Go / simulatore. |
| **Figma** | Plugin che (1) renderizza il JSON come frame nativi, (2) intercetta le modifiche utente → proposte → validatore, (3) annota il canvas con errori/warning. Token sincronizzati via Figma Variables (DTCG round-trip). Figma MCP server come acceleratore opzionale (richiede piano a pagamento con Dev Mode; pricing a consumo in arrivo). |

## Il flusso di modifica (identico da entrambe le superfici)

```
MODIFICA (da Figma o da prompt)
        │
        ▼
PROPOSTA di modifica al JSON
        │
        ▼
VALIDATORE ──► errore? → avviso immediato + correzione proposta
        │ ok             (warning: applicata ma segnalata)
        ▼
JSON aggiornato (source of truth)
        │
        ├──► RE-RENDER Figma (plugin riscrive il canvas)
        └──► RE-RENDER Expo Go (hot reload)
```

**Conseguenze:** zero conflitti di sync, un solo validatore, feedback in tempo reale su entrambe le superfici.

## Il flusso di import per redesign (MVP)

1. **Input:** screenshot schermate attuali (+ codice `.tsx` se disponibile — doppia fonte, molto più precisa).
2. **Estrazione:** modello vision → screen JSON. Il codice, se presente, è la fonte strutturale; lo screenshot la verifica visiva.
3. **Audit:** il validatore gira sul JSON estratto → report violazioni (touch target, contrasto, azioni primarie multiple, navigazione non convenzionale, valori hard-coded da tokenizzare).
4. **Redesign proposto:** il generatore produce la versione conforme — stessa funzionalità, regole rispettate, token applicati → subito su Expo Go e Figma.
5. **Iterazione:** loop normale di modifica (prompt e/o Figma).

⚠️ Il JSON estratto da screenshot è una **bozza da confermare**, mai verità automatica.

## Contratto ferreo

> **Qualsiasi output LLM passa dal validatore prima di toccare lo screen JSON.**

È ciò che rende sicuro usare modelli locali piccoli e imperfetti (decisione D9).
