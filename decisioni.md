# Registro delle decisioni — DesignChecker

Ogni decisione ha: data, contesto, decisione, motivazione. Le decisioni si possono revocare, ma mai cancellare: si aggiunge una nuova entry che le supera.

---

## D1 — Le regole UI/UX sono dati versionati, non codice
**Contesto:** il sistema deve restare aggiornato sulle regole ufficiali (HIG, Material 3, WCAG), che cambiano a ogni release (WWDC, Google I/O, update W3C).
**Decisione:** ogni regola è una entry YAML con `id`, `source`, `source_url`, `platform`, `severity`, soglia e messaggio. I file di regole vivono in `rules/`.
**Motivazione:** aggiornare il sistema = aggiornare file di dati, non riscrivere il programma. Ogni segnalazione all'utente può citare la fonte ufficiale.
**Nota onesta:** non esiste un feed ufficiale machine-readable delle regole. L'aggiornamento è un costo editoriale (umano o assistito), legato alle release ufficiali.

## D2 — Due severità distinte: errori e warning
**Contesto:** non tutte le regole sono formalizzabili in modo binario.
**Decisione:** `error` = regola ufficiale violata, bloccante, deterministica (touch target, contrasto, safe area). `warning` = euristica UX/psicologica (Fitts, Hick, Jakob), segnalata ma non bloccante.
**Motivazione:** il sistema non deve fingere certezza dove c'è giudizio.

## D3 — Screen JSON come unica fonte di verità
**Contesto:** l'utente vuole modificare sia da Figma sia da prompt → rischio di conflitti di sincronizzazione a due vie.
**Decisione:** non esiste sync bidirezionale tra peer. Ogni modifica (da Figma o da prompt) è una *proposta* di modifica al JSON → passa dal validatore → se valida viene applicata → entrambi i renderer (Figma e Expo) si aggiornano dal JSON.
**Motivazione:** un solo dato che cambia, in un solo posto, in un solo momento. Zero merge conflict. Un solo validatore.

## D4 — Figma è una superficie di editing, non un database
**Contesto:** Figma deve restare la tela per l'utente visuale, coordinata col simulatore.
**Decisione:** plugin Figma dedicato che (1) renderizza il JSON come frame nativi, (2) intercetta le modifiche utente e le traduce in proposte (vedi D3), (3) annota il canvas con errori/warning in tempo reale. Token sincronizzati via Figma Variables (formato DTCG).
**Motivazione:** meccanismi ufficiali esistenti (Plugin API, Variables REST API, precedenti come Design Lint). Figma MCP server tenuto come acceleratore opzionale (costi: piano a pagamento + futuro pricing a consumo).

## D5 — Import per redesign anticipato al MVP
**Contesto:** l'esigenza immediata è il redesign di un'app esistente, non la creazione da zero.
**Decisione:** il MVP include l'importer: screenshot (+ codice sorgente se disponibile) → screen JSON → audit delle violazioni → proposta di redesign.
**Motivazione:** copre il caso d'uso reale dell'utente fin da subito.
**Limite noto:** lo screenshot non contiene la struttura vera (un bottone e un testo colorato sono identici ai pixel). Doppia fonte codice+screenshot molto più affidabile; il report va presentato come bozza da confermare.

## D6 — Provider layer: l'utente sceglie il modello AI
**Contesto:** l'utente deve poter usare l'abbonamento AI che già ha, o modelli locali.
**Decisione:** layer di astrazione provider (adapter per Ollama, LM Studio, OpenAI, Anthropic, Kimi/Moonshot, OpenRouter…). Il core non sa quale modello usa.
**Motivazione:** indipendenza dai provider; privacy e costi sotto controllo dell'utente.

## D7 — Rilevamento automatico e menu a due gruppi
**Contesto:** all'avvio di `dc` l'utente deve vedere subito cosa può usare.
**Decisione:** all'avvio, rilevamento di (a) server locali con API (Ollama, LM Studio → query diretta dei modelli installati), (b) credenziali da CLI agent presenti sul sistema (Kimi Code, Codex, Claude Code → riuso delle credenziali via API diretta, **mai** come subprocess). Menu con due gruppi: **modello unico** (copre tutti i task) vs **combinazione** (un modello per task: generazione / interpretazione prompt / vision).
**Motivazione:** i CLI agent non sono API: chiamarli come subprocess è fragile (output non strutturato, errori non intercettabili). Le loro credenziali invece sbloccano l'API diretta.
**Dettaglio UX:** il registry distingue "può fare tutto" da "può fare tutto *bene*" (`generation_quality: basic|good|excellent`).

## D8 — Capabilities matrix e probe test
**Contesto:** task diversi richiedono capacità diverse (vision obbligatoria per l'import da screenshot; structured output affidabile per tutto).
**Decisione:** capacità note da (a) API Ollama per i locali, (b) registry `models.yaml` versionato per il cloud, (c) **probe test** di ~30s per modelli sconosciuti (micro-prompt JSON + micro-immagine). Se il modello scelto non copre un task, messaggio-guida esplicito.
**Motivazione:** nessun errore generico; i fine-tune locali dell'utente vengono classificati automaticamente.

## D9 — Il validatore è la rete di sicurezza per modelli piccoli
**Contesto:** modelli locali piccoli (0.4–3B, anche LoRA custom) possono produrre output imperfetti.
**Decisione:** qualsiasi output LLM passa dal validatore prima di toccare lo screen JSON. Output invalido → scartato, retry o avviso.
**Motivazione:** rende sicuro usare modelli piccoli; abilita il fine-tuning con qualità verificabile automaticamente (il validatore è anche la metrica di test).

## D10 — Niente editor visuale drag-and-drop nella v1
**Contesto:** tentazione di ricostruire Figma.
**Decisione:** il vincolo è la feature. Editing visuale solo *dentro* Figma tramite plugin, mai un editor nostro.
**Motivazione:** un editor libero ricrea il problema da cui il progetto nasce (libertà senza vincoli, duplicazione).

## D11 — Screen JSON: scheletro fisso + catalogo estensibile + composizione aperta
**Contesto:** il JSON non deve essere né statico né un elenco infinito di casi/componenti.
**Decisione:** tre livelli. (1) Scheletro del nodo fisso: ogni nodo ha `id`, `type`, `props`, `layout`, `style`, `a11y`, `semantics`, `states`, `platform_variants`, `meta`, `children`. (2) Componenti in un catalogo YAML estensibile (`components.catalog.yaml`) dove ogni tipo dichiara i suoi **traits** (`interactive`, `touch_target`, `text`…). (3) Schermate = composizioni aperte di nodi.
**Motivazione:** il validatore controlla i *traits*, non i tipi → componenti custom futuri vengono validati automaticamente senza toccare schema né validatore. È il modello mentale di Figma: pochi primitivi, infinite composizioni.

## D12 — Token solo per riferimento, layout sul denominatore Figma↔flexbox
**Contesto:** coerenza tra design e codice, e traduzione bidirezionale Figma ↔ RN.
**Decisione:** nei nodi solo riferimenti a token DTCG (`{color.brand.primary}`); hex hard-coded = `error` del validatore. Il campo `layout` usa il modello comune auto-layout/flexbox (`direction`, `gap`, `padding`, `sizing: hug|fill|fixed`, `align`, `safe_area`), mappabile 1:1 su entrambi i lati.
**Motivazione:** un solo modello mentale, nessuna perdita nella traduzione, token come unica fonte di stile.

## D13 — Modifiche come JSON Patch, codegen secondo le convenzioni ufficiali Expo
**Contesto:** le modifiche da prompt e da Figma devono essere puntuali, diff-abili e validabili prima dell'applicazione; il codice generato deve seguire le convenzioni ufficiali.
**Decisione:** ogni modifica è una patch RFC 6902 proposta → validata → applicata. Il codegen segue il blog ufficiale Expo sulla struttura delle cartelle (agg. gen 2026): `/src`, routing in `src/app`, route snelli che ritornano screen da `src/screens/`, filename kebab-case (default SDK 55), un named export per componente, `StyleSheet.create` in fondo al file, varianti `.ios.tsx`/`.android.tsx` (da `platform_variants` nei nodi), `theme.ts` generato dai token.
**Motivazione:** patch = stessa pipe di validazione per entrambe le superfici; codegen conforme = codice trasportabile in app esistenti senza rifattorizzare.

## D14 — Dati: solo binding nel JSON, ma prototipo provabile con mock
**Contesto:** il preview su Expo Go deve essere concreto e provabile, non un mockup morto.
**Decisione:** `data_source` nello screen JSON contiene solo nomi di binding. I dati mock vivono in `mocks/*.mock.json`; il codegen genera un data layer isolato (`src/data/` + hook per schermata) così la UI non sa da dove vengono i dati. Azioni cablate davvero: navigazione reale, form editabili, submit che aggiorna il mock in memoria, stati empty/loading/error attivabili. Nuove regole: `expo.no-mock-inline` (error), `expo.action-wired` (warning).
**Motivazione:** il mock è anche il contratto dati dell'app; quando arriva il DB vero si sostituisce un solo file, la UI resta identica.

## D15 — Figma Best Practices come fonte di regole (`rules/figma-bp.yaml`)
**Contesto:** il programma deve seguire anche i pattern ufficiali di Figma (figma.com/best-practices), oltre a W3C/Apple/Android.
**Decisione:** nuovo file di regole dedicato. Particolarità: controlla come viene *costruito il file Figma*, non la schermata. La maggior parte delle regole è "garantita per costruzione" dal renderer (componenti invece di copie, varianti per gli stati, pagine/frame come organizzazione, naming con slash, auto-layout ovunque, variables dai token, overlay per le modali); il validatore interviene solo sugli edit manuali dell'utente (detach istanza = error, naming generico = warning).
**Motivazione:** è la risposta strutturale al problema originale della duplicazione in Figma.

## D16 — `action`: DSL ibrida (oggetti canonici + shorthand)
**Contesto:** il formato delle azioni dei componenti interattivi (scelta rimandata all'utente, che ha delegato la raccomandazione).
**Decisione:** forma canonica = oggetto strutturato (`{ "type": "submit", "form": "...", "on_success": {...}, "on_error": {...} }`), validabile campo per campo. Shorthand accettati solo per `navigate:/route` e `back`, normalizzati dal validatore nella forma canonica.
**Motivazione:** DesignChecker è machine-first: la forma canonica deve essere quella validabile; lo shorthand è zucchero di leggibilità per il 90% dei casi.

## D17 — Versionamento: git + registro delle patch
**Contesto:** come conservare le versioni confermate delle schermate (scelta rimandata all'utente, che ha delegato la raccomandazione).
**Decisione:** git conserva le versioni (ogni conferma = commit, ogni esplorazione = branch — parallelo con il branching di Figma). In più, `history.jsonl` registra per ogni patch: contenuto, prompt/gesto che l'ha generata, esito della validazione. Non per lo storage (ci pensa git) ma per l'audit del "perché".
**Motivazione:** ogni cambiamento ha una ragione tracciata — coerente con la filosofia del progetto.

## D18 — Validatore: regole dichiarative + libreria di check
**Contesto:** come implementare il validatore senza che ogni nuova regola richieda codice.
**Decisione:** le regole YAML dichiarano un `check` (es. `touch_target_min`, `contrast_min`) + `params`; il validatore ha una libreria di ~27 funzioni di controllo. Nuova regola con check esistente = solo YAML. Le regole sui convenzioni di codice che non possono girare sul JSON (Pressable, FlatList, /src…) hanno `phase: codegen` e vengono caricate/documentate ma eseguite più avanti sul codice generato. Filtro piattaforma: ogni regola ha `platform: ios|android|both`.
**Motivazione:** la promessa "le regole sono dati" mantenuta anche nel codice; i 43 controlli del MVP sono alimentati da poche funzioni.
**Stato:** implementato e testato (20 test, suite unittest).

## D19 — Strategia di preview: Expo Go non basta più (SDK 56+)
**Contesto:** Expo Go per SDK 56+ non è più distribuito su App Store/Play Store (solo via CLI su Android; TestFlight/`eas go`/dev build su iOS). Baseline aggiornata a SDK 57 (verifica settembre 2026).
**Decisione:** la preview di DesignChecker punta a: (1) simulatore iOS/Android via `npx expo start` + dev build (`npx expo run:ios`), (2) Expo Go dove disponibile, (3) in futuro preview web con react-native-web per l'iterazione veloce. La CLI lo dichiara esplicitamente dopo ogni `generate`.
**Motivazione:** non promettere un flusso ("apri Expo Go e basta") che Apple/Google non permettono più.

## D20 — Codegen v0.2: generatore di progetto Expo completo
**Contesto:** v0.2 della roadmap — dal JSON al codice.
**Decisione:** `dc generate <screen.json> --out <dir>` genera un progetto Expo completo: `src/theme.ts` (dai token DTCG, alias risolti), route snelli in `src/app/`, schermate in `src/screens/<id>/`, componenti riusabili in `src/components/` (Button, EmptyState…), data layer mock isolato in `src/data/` (D14), Native Tabs compound API per il TabBar, varianti `.ios.tsx/.android.tsx` da `platform_variants`. Convenzioni verificate da test dedicati (10 test codegen).
**Motivazione:** codice trasportabile in un'app esistente senza rifattorizzare; convenzioni ufficiali garantite dal generatore, non dalla disciplina.
**Stato:** implementato e testato (30 test totali OK). Limiti noti: icone con mappatura SF/Material euristica; le route oltre la home vanno generate quando lo schema multi-schermata sarà collegato ad `app.design.json`.
