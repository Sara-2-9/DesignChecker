# 07 — Roadmap

## MVP (solo terminale)
- Rules engine con ~40 regole numeriche (touch target, contrasto, spacing, tipografia, safe area)
- Validatore CLI: prende uno screen JSON → sputa errori/warning con fonti
- **Importer con audit** (decisione D5): screenshot (+codice) → JSON → report violazioni
- Schema screen JSON definito (prerequisito: `docs/04`)

✅ *Copre già il bisogno immediato: capire cosa non va nelle schermate attuali.*

## v0.2 — Doppio rendering
- Component library React Native conforme per costruzione → rendering su Expo Go
- Plugin Figma: renderizza il JSON come frame nativi, sincronizza token via Variables (DTCG)
- Da qui: Figma e simulatore coordinati, stesso JSON

## v0.3 — Editing bidirezionale + redesign assistito
- Plugin Figma intercetta modifiche canvas → proposte → validazione real-time → annotation errori sul canvas
- Interpretazione prompt → proposte di modifica (stesso percorso)
- Generatore LLM: proposte di redesign dall'audit, proposte di prima schermata dal brief
- Provider layer completo: rilevamento, menu due gruppi, routing per task, probe test

## v0.4 — Chiusura del cerchio
- Export codice pulito nel repo dell'app esistente (sync, non solo copia)
- Opzionale: Figma MCP per "code to canvas" (catturare l'app vera come layer Figma) — valutare costi piano

## Processo continuo
- Aggiornamento regole a ogni WWDC / Google I/O / release W3C, con changelog versionato
- Aggiornamento registry `models.yaml` all'uscita di nuovi modelli

## Cosa NON fare (promemoria)
- ❌ Editor visuale drag-and-drop proprio (D10)
- ❌ Euristiche UX come errori binari: restano warning (D2)
- ❌ Sync bidirezionale tra peer: solo proposte → validatore → JSON (D3)
- ❌ CLI agent come subprocess: solo riuso credenziali (D7)
