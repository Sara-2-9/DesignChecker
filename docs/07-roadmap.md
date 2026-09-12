# 07 — Roadmap

## MVP (solo terminale) — ✅ FATTO
- Rules engine con 48 regole (36 validate + 12 codegen), baseline SDK 57
- Validatore CLI: prende uno screen JSON → sputa errori/warning con fonti
- Schema screen JSON definito (`docs/04`)

## v0.2 — Codegen — ✅ FATTO
- Component library React Native conforme per costruzione
- `dck generate`: dallo screen JSON a progetto Expo completo (struttura SDK 57, Native Tabs, theme.ts dai token)

## v0.3 — Importer + provider layer (IN CORSO — decisioni D21–D24)
- **Importer Figma** ✅: `dck link figma <url>` + `dck screens` + `dck import figma <frame>` (REST API read-only, PAT) — testato su file Figma reale
- **Importer codice** ✅: `dck import code <path.tsx>` (helper Node AST, parsing statico; segue gli import dei componenti custom; roundtrip su generated-app: 0 errori) — 11 test
- **Destinazione codice** ✅ (D28): post-import il CLI chiede nuovo progetto vs esistente; `dck project` per gestire il collegamento; mai sovrascritture senza consenso
- **Provider layer AI** ✅ (D31): rilevamento Ollama/LM Studio/API key, menu due gruppi, probe, routing per task
- **Fix loop AI** ✅ (D31): `dck fix` — l'LLM propone JSON Patch, il validatore approva o rifiuta
- **Importer screenshot**: `dck import shot <png>` (provider layer ✅ + modello vision)

## v0.4 — Plugin Figma + editing bidirezionale (IN CORSO — D29, D31)
- ✅ Plugin: export frame → screen JSON via Plugin API (zero REST, zero rate limit), audit via bridge locale `dck serve`
- ✅ Annotazioni real-time sul canvas (toggle, debounce 900ms): rettangoli rossi/arancio + regola violata
- ✅ Scrittura su canvas: render screen JSON → frame nativi (auto-layout, token risolti, dc_id in pluginData)
- ✅ Render fedele (D32): geometria reale + immagini/icone clonate dal nodo sorgente; fallback strutturale senza geometria
- ✅ Guardia anti-perdita export/fix (D32): backup .preexport.bak + avviso nel pannello
- ✅ Integrazione AI nel plugin: bottoni "Valuta il design" (review consultiva) e "Correggi con AI" (patch gated dal validatore → render automatico)
- ⏳ Interpretazione prompt libero → patch → render automatico (il fix loop copre gia' le violazioni)
- ⏳ Sync token → Variables Figma (D22)
- ⏳ Generatore LLM: prima schermata dal brief

## v0.5 — Chiusura del cerchio
- Export codice pulito nel repo dell'app esistente (sync, non solo copia)
- Valutare componenti Expo UI (stabili da SDK 56) per la component library

## Processo continuo
- Aggiornamento regole a ogni WWDC / Google I/O / release W3C, con changelog versionato
- Aggiornamento registry `models.yaml` all'uscita di nuovi modelli

## Cosa NON fare (promemoria)
- ❌ Editor visuale drag-and-drop proprio (D10)
- ❌ Euristiche UX come errori binari: restano warning (D2)
- ❌ Sync bidirezionale tra peer: solo proposte → validatore → JSON (D3)
- ❌ CLI agent come subprocess: solo riuso credenziali (D7)
