# 07 — Roadmap

## MVP (solo terminale) — ✅ FATTO
- Rules engine con 48 regole (36 validate + 12 codegen), baseline SDK 57
- Validatore CLI: prende uno screen JSON → sputa errori/warning con fonti
- Schema screen JSON definito (`docs/04`)

## v0.2 — Codegen — ✅ FATTO
- Component library React Native conforme per costruzione
- `dc generate`: dallo screen JSON a progetto Expo completo (struttura SDK 57, Native Tabs, theme.ts dai token)

## v0.3 — Importer + provider layer (IN CORSO — decisioni D21–D24)
- **Importer Figma** ✅: `dc link figma <url>` + `dc screens` + `dc import figma <frame>` (REST API read-only, PAT) — testato su file Figma reale
- **Importer codice** ✅: `dc import code <path.tsx>` (helper Node AST, parsing statico; segue gli import dei componenti custom; roundtrip su generated-app: 0 errori) — 11 test
- **Importer screenshot**: `dc import shot <png>` (provider layer + modello vision)
- Provider layer: rilevamento, menu due gruppi, routing per task, probe test

## v0.4 — Plugin Figma + editing bidirezionale
- Plugin: renderizza JSON → frame nativi (**unica via di scrittura** sul canvas, D21), sync token via Plugin API (D22), intercetta modifiche → proposte → validazione real-time → annotation errori
- Interpretazione prompt → patch (stesso percorso)
- Generatore LLM: proposte di redesign dall'audit, prima schermata dal brief

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
