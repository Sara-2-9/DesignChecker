# 01 — Visione e obiettivi

## Il problema

Il flusso classico "idea → Figma → app" ha tre difetti concreti:

1. **Figma disegna, non valida.** Lascia duplicare componenti, violare convenzioni di piattaforma e produrre layout che non si traducono in codice nativo senza attrito. Gli errori UI/UX si scoprono tardi (o mai).
2. **Il design e il codice vivono separati.** Quello che disegni non è quello che giri sul simulatore; ogni traduzione è manuale e perde pezzi.
3. **Le regole ufficiali esistono ma nessuno le applica per te.** Apple HIG, Material Design 3, WCAG sono documenti in linguaggio naturale: starci dentro richiede esperienza che chi è alle prime armi non ha (e non sa di non avere).

## La soluzione

Un sistema che ribalta il flusso: da "disegno libero che poi interpreto" a **"sistema vincolato dalle regole ufficiali che genera direttamente codice eseguibile"**.

- Il sistema **propone** il design iniziale (o il redesign di uno esistente) già conforme.
- L'utente itera **a parole** (prompt) o **visivamente** (Figma), con **validazione in tempo reale**: ogni violazione viene segnalata subito, con la fonte ufficiale citata e una proposta di correzione.
- Il risultato è **codice Expo/React Native reale**, visibile subito su Expo Go / simulatore, trasportabile in un'app esistente.
- L'utente sceglie **quale AI usare** (cloud o locale), il core non dipende da nessun provider.

## Il differenziale rispetto agli strumenti esistenti

Gli strumenti attuali (Anima, Locofy, Builder.io, GenVibe, Lovable…) **convertono** o **generano** codice, ma nessuno ha un **rules engine ufficiale e versionato** che:

1. propone il design iniziale *già conforme* a HIG / Material 3 / WCAG,
2. blocca o segnala le violazioni *mentre modifichi*,
3. cita la fonte della regola violata.

È la differenza tra un traduttore e un revisore con le regole in mano. I plugin-linter per Figma esistenti (Design Lint, Roller, Contrast) validano coerenza interna e contrasto, **non** le regole di piattaforma (touch target, safe area, pattern di navigazione).

## Obiettivi misurabili del prodotto finito

- Ogni schermata generata passa il 100% delle regole `error` prima di essere mostrata.
- Ogni violazione segnalata include: regola, fonte ufficiale, valore attuale, valore richiesto, correzione proposta.
- Tempo da brief a schermata su simulatore: minuti, non giorni.
- Zero codice "monouso": l'export è componenti TypeScript puliti e riusabili.

## Non-obiettivi (v1)

- ❌ Editor visuale drag-and-drop proprio (decisione D10).
- ❌ Automatizzare le regole di psicologia/UX come verità binarie: restano warning.
- ❌ Supporto web/desktop: solo mobile iOS+Android via Expo.
- ❌ Promessa di "sempre aggiornato automaticamente": l'aggiornamento delle regole è editoriale e versionato (decisione D1).
