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

## D21 — Importer Figma: REST API in lettura, plugin come unica via di scrittura
**Contesto:** l'utente deve poter collegare un file Figma e far leggere le schermate al programma.
**Decisione:** lettura via REST API con Personal Access Token (scope `file_content:read`, scadenza max 90 giorni — il CLI avvisa alla scadenza). Scrittura SOLO via plugin DesignChecker, perché: la REST API non può modificare nodi; l'MCP server ufficiale è riservato a client approvati (VS Code, Cursor, Claude Code, Codex) e rifiuta custom OAuth app e PAT.
**Motivazione:** unica architettura possibile per un tool custom nel 2026, verificata sulle fonti ufficiali.
**Limiti gestiti:** rate limit severi su piano Starter (Tier 1 ~10 req/min; View/Collab ~20/mese) — caching del file tree, messaggi chiari su 429.
**Scope del PAT (minimo privilegio):** solo `users:read` (verifica token in `dc link`) e `file_content:read` (lettura frame). Nient'altro: i permessi di scrittura REST non esistono per il canvas, quindi nessuno scope di scrittura serve.

## D27 — Real-time e scrittura Figma: solo plugin, mai REST/webhook
**Contesto:** il sistema deve avvisare in tempo reale durante l'editing in Figma e applicare sul canvas le modifiche confermate da prompt.
**Decisione:** entrambe le capacità sono del plugin (v0.4): la Plugin API osserva le modifiche del documento in locale (→ proposte → validatore → annotation immediate) e riscrive il canvas dopo l'applicazione delle patch. REST API esclusa (solo snapshot, read-only, rate limit); webhook Figma valutati e scartati (eventi grossolani tipo "file salvato", non editing live).
**Motivazione:** il tempo reale richiede di stare *dentro* Figma; il plugin è l'unico componente che ci sta.

## D22 — Correzione a D4: sync token via plugin, non via Variables REST API
**Contesto:** D4 assumeva il sync dei token via Figma Variables REST API.
**Decisione:** gli endpoint Variables REST sono gated al piano Enterprise. Il sync token DTCG ↔ Figma Variables avviene tramite il plugin (Plugin API: variabili locali senza vincoli di piano).
**Motivazione:** non legare DesignChecker a un piano Enterprise.

## D23 — Importer codice da terminale: parsing AST via helper Node
**Contesto:** l'utente deve poter puntare una schermata di un'app esistente da terminale (`dc import code <path.tsx>`).
**Decisione:** un piccolo helper Node (`tools/tsx2json.cjs`, @babel/parser) estrae albero JSX + `StyleSheet.create` + import relativi in JSON; `designchecker/importer_code.py` lo converte in screen JSON. Il codice non viene MAI eseguito (parsing statico). Implementato con: riconoscimento elementi RN nativi (Pressable→Button, FlatList→List…), match componenti custom al catalogo per nome (con suffissi: "ExpenseRow"→ListRow), **inseguimento degli import relativi** (legge il file del componente custom per touch size/a11y/azioni reali, con cache e guardia anti-cicli), merge delle props del sito d'uso (`<EmptyState message=… onAction=… />`), riferimenti `theme.*`→token DTCG se il path esiste, hex→token inverso, azioni da `router.push/back`, euristiche (Pressable absolute ~56→Fab; View con nome "…card"→Card). Node è già prerequisito (Expo).
**Motivazione:** per il redesign dell'app esistente, il codice è la fonte di verità.

## D24 — Tre importer, un'unica interfaccia
**Contesto:** Figma, codice, screenshot: tre sorgenti con fedeltà diverse.
**Decisione:** tutti producono screen JSON con `meta.source` e `meta.confidence` per nodo, e tutti sfociano nello stesso audit del validatore. Comandi: `dc link figma <url>`, `dc screens`, `dc import figma <frame>`, `dc import code <path>`, `dc import shot <png>` (quest'ultimo con provider vision, v0.3). Mappatura frame→catalogo in cascata: istanze nominate → convenzione naming → euristica LLM.
**Motivazione:** Figma dà geometria perfetta, codice dà semantica perfetta, screenshot copre il resto.

## D25 — Distribuzione CLI: wrapper globale, venv invisibile
**Contesto:** l'utente non deve digitare `python3 -m designchecker` né attivare il venv a mano.
**Decisione:** `install.sh` (una tantum) crea il venv, installa le dipendenze e scrive un wrapper eseguibile in `~/.local/bin/designchecker` (+ alias `dc`) che invoca il Python del venv con PYTHONPATH puntato al progetto. Il venv esiste ancora ma è invisibile; il comando funziona da qualsiasi directory (root detection: cwd → parenti → package dir).
**Motivazione:** UX da tool vero, zero attrito quotidiano.

## D26 — Rate limit Figma: caching ora, plugin come strada senza limiti
**Contesto:** la REST API ha rate limit tiered (severi su piano Starter: ~10 req/min Tier 1; seat View/Collab ~20/mese).
**Decisione:** (1) MVP: chiamate minime (`depth=2` per l'elenco, `/nodes` solo per il frame scelto) + caching del tree su disco (`.designchecker/cache/`). (2) La soluzione strutturale è il **plugin DesignChecker** (v0.4): la Plugin API gira *dentro* Figma (desktop o browser) in locale — zero chiamate REST, zero rate limit. (3) Un "MCP custom" da solo non risolve: l'MCP ufficiale è chiuso ai client approvati (D21); i bridge MCP community esistenti sono infatti plugin Figma con un server locale davanti — cioè esattamente la nostra strada (2). (4) L'app desktop Figma non espone API proprie: il plugin è il modo in cui si "usa l'app installata".
**Motivazione:** non combattere i limiti: aggirarli architetturalmente con il componente che dobbiamo comunque costruire.

## D28 — Destinazione del codice: prompt interattivo post-import
**Contesto:** l'utente non parte con un'app Expo esistente: dopo `dc import` il sistema deve chiedere DOVE materializzare il codice, non assumere nulla.
**Decisione:** dopo ogni import (figma|code) + audit, il CLI chiede: **[i]** progetto collegato (se già scelto in passato, default) / **[n]** nuovo progetto (scaffold completo su `~/Desktop/<nome>`) / **[e]** altro progetto esistente (validato con `is_expo_project`: package.json con dipendenza `expo`) / **[s]** solo import. Il progetto scelto è salvato in `~/.designchecker/config.json` (chiave `project`) e gestibile con `dc project [<path>]` / `dc project --forget`. Nei progetti esistenti si scrivono SOLO i file della schermata (`Codegen.project_files`/`generate_into`: niente package.json/app.json/_layout), e **mai sovrascritture senza consenso esplicito** (lista conflitti → conferma). In modalità non interattiva (pipe/CI) nessun prompt: solo il suggerimento di `dc generate`.
**Motivazione:** il flusso "design → app vera" deve partire da zero senza attrito, ma rispettare il principio di non distruggere mai lavoro esistente.

## D29 — Plugin Figma: architettura a ponte locale
**Contesto:** D21/D26/D27 dicono che real-time e scrittura passano solo dal plugin; serve l'architettura concreta, e il test reale ha confermato il problema (429 ricorrenti su REST Starter).
**Decisione:** il plugin (`plugin/manifest.json` + `code.js` + `ui.html`) gira dentro Figma con la Plugin API — zero chiamate REST. Tre componenti:
1. **code.js** (sandbox): export frame→screen JSON (stessa cascata di mapping dell'importer REST: alias naming → catalogo → fallback strutturale; geometria reale da `absoluteBoundingBox`; azioni da `reactions` di prototyping), overlay di annotazione (rettangoli rossi/arancio tratteggiati + etichetta regola, in un frame `DesignChecker — annotazioni` auto-pulito), **render JSON→frame nativi** (la scrittura su canvas) con auto-layout, token risolti, font Inter caricati via `loadFontAsync`.
2. **ui.html** (iframe): unico punto di rete del plugin (la sandbox non ha fetch); UI con stato bridge, export+valida, toggle **tempo reale** (documentchange → debounce 900ms → re-export → valida → annotazioni), render da id schermata.
3. **`dc serve`** (stdlib HTTP solo su 127.0.0.1, porta 7357): espone al plugin il validatore Python (`/validate`, `/import`), catalogo (`/catalog`), token (`/tokens` con mappa piatta risolta + reverse hex) e gli screen importati (`/screen/<id>`, con sanitizzazione anti path-traversal). Il validatore resta UNICO, in Python: niente doppia implementazione delle regole in JS.
Comunicazione: code.js ↔ ui.html via `postMessage`; ui.html ↔ bridge via fetch (domini in allowlist del manifest). Con bridge offline il plugin avvisa e l'export resta possibile (fallback: alias + traits embedded).
**Motivazione:** un solo motore di regole (Python), zero rate limit, real-time locale, scrittura sul canvas possibile solo dal componente che la Figma permette.

## D30 — Eccezioni giustificate e sfondi non uniformi
**Contesto:** il primo audit reale via plugin ha mostrato due limiti: (1) i controlli di contrasto confrontano il testo col token di sfondo dichiarato, ma su gradienti/immagini il calcolo puo' non riflettere la realta'; (2) esistono casi legittimi in cui una regola va violata consapevolmente.
**Decisione:** (1) gli exporter (plugin + REST) leggono anche i fill GRADIENT_*: lo sfondo diventa la **media pesata degli stop**, marcata `meta.visual_bg: "gradient"` (o `"image"`); `ds.no-hardcoded-value` esenta questi nodi (e' una lettura del canvas, non una decisione hard-coded). (2) Meccanismo di **eccezioni motivate**: `meta.exceptions: [{rule: "<id o prefisso>", reason: "..."}]` su un nodo rimuove i finding coperti; `reason` vuota = eccezione ignorata. Le eccezioni applicate sono conteggiate e stampate nel report (CLI e pannello plugin), mai silenziose. Id composti (`main-tabs/profile`) risalgono al nodo radice; `(schermata)` al root.
**Motivazione:** un validatore credibile deve distinguere "violazione inconsapevole" da "scelta motivata" — e deve dichiarare le proprie approssimazioni.

## D31 — Integrazione AI: provider a scelta, validatore come gatekeeper
**Contesto:** il design system deve poter *valutare* e *correggere* il design con un modello AI, senza tradire i principi fondativi: l'utente sceglie il provider (D6), le regole deterministiche restano l'arbitro (D3), nessuna azione opaca (D4).
**Decisione:**
1. **Layer provider** (`designchecker/ai.py`): rilevamento automatico — **gruppo A (locale)**: Ollama (`:11434`) e LM Studio (`:1234`) via HTTP; **gruppo B (cloud)**: **Kimi Code** (endpoint abbonamento `api.kimi.com/coding/v1`, OpenAI-compatibile — attenzione: le chiavi Kimi Code, platform.kimi.ai e platform.moonshot.cn NON sono intercambiabili), Kimi API pay-as-you-go, Claude, OpenAI, **HuggingFace Inference** (`router.huggingface.co/v1`, crediti free mensili), **endpoint custom** OpenAI-compatibile. Le chiavi si incollano interattivamente in `dc ai` (getpass, niente echo) e finiscono in `~/.designchecker/config.json` (chmod 600, mai nel repo). I CLI agent installati (claude, gemini, codex) sono solo **segnalati**: DesignChecker non li esegue come subprocess. `dc ai` mostra il menu a due gruppi, fa il **probe** ("rispondi solo: ok") e salva la scelta. Routing per attivita': euristica sui nomi modello (es. preferenza a qwen/coder per le patch JSON).
2. **`dc review <screen.json>`**: valutazione qualitativa (gerarchia, ritmo, psicologia UX) in italiano. E' **consultiva**: il modello vede i finding deterministici e deve aggiungere giudizio, non ripeterli. Non tocca il JSON.
3. **`dc fix <screen.json>`**: il modello propone una **JSON Patch RFC 6902**; un applicatore minimale interno (solo add/remove/replace, max 40 op, niente dipendenze) la applica a una copia; il **validatore deterministico decide**: accettata solo se riduce gli errori senza aumentare i warning. Rifiutata → feedback al modello e un secondo tentativo; poi basta, file invariato. Accettata → salvataggio con backup `.bak` e diff delle operazioni stampato.
4. **Nel plugin**: due bottoni ("Valuta il design", "Correggi con AI") attivi solo se `dc ai` e' configurato (lo dice `/health`); dopo un fix accettato il pannello aggiorna i finding e **renderizza la versione corretta sul canvas**.
**Motivazione:** il valore dell'AI e' massimo dove il determinismo non arriva (giudizio estetico, proposte di fix); il rischio dell'AI e' massimo dove il determinismo basta (applicare modifiche). Il gatekeeper risolve la tensione: l'LLM propone, la regola dispone.

## D32 — Render fedele: geometria reale + clonazione immagini dal sorgente
**Contesto:** il primo render JSON→canvas era uno "scheletro a blocchi" (auto-layout con dimensioni di default, immagini come placeholder grigi): utile per la struttura, non per valutare il design.
**Decisione:**
1. **Export**: ogni nodo porta `layout.frame: {x, y, w, h}` (coordinate **relative al genitore**, da `absoluteBoundingBox` — in render i figli sono posizionati dentro il frame parent; una prima versione root-relativa spostava/clippava i nodi annidati) e `meta.figma_node_id`. Il validatore ignora entrambi (verificato: findings invariati). `clipsContent` solo sul root: i contenuti possono legittimamente debordare dai gruppi.
2. **Render**: se il JSON ha geometria, il plugin usa **posizionamento assoluto** (niente auto-layout, `clipsContent`); altrimenti resta il render strutturale come fallback (JSON scritti a mano, codegen).
3. **Immagini e icone**: non ricreabili dal JSON senza portarsi dietro i byte — il renderer **clona il nodo Figma sorgente** via `figma_node_id` (stesso file, stesso documento: copia perfetta, zero dati nel JSON). Se il nodo sorgente non esiste piu', placeholder come prima.
4. **Container e testi** sono ricostruiti dal JSON (non clonati): cosi' i fix AI (colori, token) sono visibili nel render — clonare tutto renderebbe invisibili le correzioni.
5. **Guardia anti-perdita** (stessa tornata): `/import` non sovrascrive piu' alla cieca — se il file su disco e' stato modificato fuori dal canale export (es. fix AI), il bridge salva `.preexport.bak` e avvisa il pannello prima di sovrascrivere.
**Motivazione:** il render serve a valutare il design corretto: deve assomigliare all'originale, ma riflettere le decisioni del sistema (token, fix), non fotocopiare gli errori.

## D33 — Codegen con geometria: posizionamento assoluto nel simulatore
**Contesto:** il codegen Expo ignorava `layout.frame`: anche per schermate importate da Figma generava layout a flusso (flex + padding), quindi l'anteprima nel simulatore non somigliava al canvas.
**Decisione:**
1. Se un nodo ha `layout.frame`, il codegen emette `position: 'absolute'` + `left/top/width/height` (coordinate parent-relative, come in Figma); le regole di sizing a flusso (flex, alignSelf) si applicano solo in assenza di frame. Il root resta `flex: 1` (il frame del root e' il device, non un vincolo del genitore).
2. Root **senza** `SafeAreaView` quando c'e' geometria: le coordinate partono da 0,0 del device (come in Figma), la status bar resta gestita da `expo-status-bar` — SafeAreaView sposterebbe tutto in basso.
3. Le immagini restano placeholder nel simulatore: i byte non escono da Figma (stessa limitazione del JSON). La TabBar resta delegata a `src/app/_layout.tsx` (Native Tabs di expo-router), non viene emessa come View assoluta.
4. Il componente `Button` della libreria accetta ora la prop `style` (mergiata nel Pressable): senza, un Button importato perdeva posizione e dimensione dal frame. Il `Fab` con frame usa il frame (niente anchor bottom/right in conflitto). Fix collaterali emersi al primo avvio reale nel simulatore: `Image` mancava dagli import react-native; `theme.ts` esponeva il gruppo DTCG `color` mentre gli stili referenziano `theme.colors` (rinominato in `_theme_tree`); dipendenze del package.json fissate alle versioni esatte SDK 57 (react/react-dom/RN esatte, niente caret) + typescript in devDeps (evita l'install interattivo al primo `expo start`).
5. **TabBar → Native Tabs**: il trigger per la route index e' sempre presente (senza, Native Tabs renderizza una schermata vuota); i nomi icona passano per una mappa verso SF Symbols validi (fallback `circle`); un tab "search" diventa `role="search"` (tab di ricerca nativo iOS 26); per ogni tab senza schermata viene generata una route segnaposto (Native Tabs richiede una route reale per trigger). A monte, l'export plugin appiattisce un livello i contenitori intermedi di tab (es. "Tab Bar Buttons"), ricava l'icona dal figlio vettoriale invece che dal nome del layer e scarta i figli senza testo ne' icona (sfondi tipo "BG" non sono tab).
6. **Immagini**: un `<Image source={{uri:''}}>` renderizza un box nero + warning RN (`source.uri should not be an empty string`) — il codegen emette invece un placeholder `View` neutro con commento. Le immagini vere restano un limite noto: i byte non escono da Figma (possibile evoluzione: `exportAsync` nel plugin → asset su disco → `require()` nel codegen).
**Motivazione:** `dck generate` su uno screen importato deve dare nel simulatore la stessa composizione vista in Figma — altrimenti il giro Figma→JSON→app perde la meta' del valore.


## D34 — Immagini vere nell'app: export PNG dal plugin → asset del progetto
**Contesto:** D32 clonava le immagini nel render Figma (stesso documento, nessun byte nel JSON) e D33 lasciava placeholder nel simulatore: il giro Figma→app restava senza le immagini vere.
**Decisione:** pipeline asset in tre stadi, tutta locale:
1. **Export (plugin code.js)**: i nodi `Image`/`Icon` (incluse le icone `VECTOR`) vengono raccolti durante `convertNode` in `pendingAssets`; dopo l'export, `collectAssets()` chiama `node.exportAsync({format:'PNG'})` + `figma.base64Encode` per ciascuno, scrive `props.asset: "assets/<screen_id>/<fname>"` nel nodo JSON e allega `assets: [{path, data_base64}]` al messaggio `screen-exported`. Nodi non esportabili → si resta al placeholder (try/catch per nodo).
2. **Bridge (`/import`)**: decodifica il base64 e salva in `imports/assets/<screen_id>/<fname>`, con **sanitizzazione al basename** (mai scrivere fuori da imports/assets/) e tolleranza ai payload rotti. Risposta con `assets_saved`.
3. **Codegen**: se il nodo ha `props.asset` e il file esiste in `imports/assets/<screen_id>/`, emette `<Image source={require('../../assets/<fname>')} />` e copia i byte in `src/assets/` del progetto (sia `generate` sia `generate_into`). Se l'asset manca, resta il placeholder D33 — nessun uri vuoto, nessun riferimento rotto.
**Motivazione:** i byte delle immagini non devono vivere nel JSON del design system (resta diff-abile e leggero), ma l'anteprima nel simulatore deve mostrare il design reale: il PNG e' un artefatto della pipeline (Figma → disco → progetto Expo), non del modello dati.

## D35 — L'AI vede il regolamento completo + contesto opzionale dell'utente
**Contesto:** in D31 il modello riceveva solo le violazioni trovate dal validatore, non il regolamento intero, e non sapeva nulla dello scopo dell'app: rischio di "correzioni" che distruggono scelte intenzionali (es. un contrasto basso voluto per estetica in un'app creativa).
**Decisione:**
1. **Regolamento completo nei prompt**: `build_fix_prompt` e `build_review_prompt` includono `rules_summary(rules)` — tutte le regole (id, severity, messaggio) in forma compatta. Il modello propone sapendo tutto cio' che il validatore controllera'; il validatore resta comunque l'arbitro finale (gatekeeper invariato).
2. **Contesto opzionale dell'utente**: campo di testo nel pannello plugin (sezione AI) e flag `--context` in `dck fix`/`dck review`. Il testo (es. "app di vibe coding in cui le persone creano app e visualizzano quelle degli altri") entra nel prompt in una sezione delimitata `CONTESTO DELL'APP`, dichiarata come *descrizione, non istruzione tecnica* (igiene anti prompt-injection: il modello la usa per capire le scelte, non per cambiare le regole del gioco). La review la usa per calibrare il giudizio; il fix per non "correggere" scelte motivate.
**Motivazione:** l'AI da' il meglio quando sa sia *cosa sara' controllato* sia *perche' il design esiste*. Le regole restano deterministiche e sovrane; il contesto influenza solo la proposta, mai il verdetto.

## D36 — Autogen: il bridge rigenera l'app Expo a ogni export/fix
**Contesto:** il giro Figma → validazione → fix → app richiedeva passaggi manuali a terminale (`dck generate`, cartella da creare) a ogni iterazione: attrito nel punto del flusso dove la velocita' conta di piu'.
**Decisione:**
1. **`dck serve --autogen [PATH]`** (default `~/Desktop/dck-preview`): dopo ogni `/import` (export dal canvas) e dopo ogni fix AI accettato, il bridge **rigenera il progetto Expo** chiamando il codegen direttamente (stesso processo Python, stessi Codegen/tokens/catalog/assets) e ritorna `app: {ok, path, files, metro}` nella risposta; il plugin lo mostra nello status.
2. **Protezione anti-sovrascrittura**: la cartella di autogen contiene il marker `.designchecker-autogen`; se la cartella esiste, e' piena e NON ha il marker, il bridge rifiuta di scriverci (mai distruggere lavoro altrui). La cartella autogen e' dichiaratamente gestita: non modificarla a mano.
3. **Metro rilevato, non avviato**: il bridge controlla `localhost:8081/status` e lo riporta (`health.metro`, `app.metro`). Avviare Metro dal bridge e' volutamente escluso: e' un dev server interattivo di lunga durata (port, watchman, log); avviarlo come subprocess nascosto crea piu' guasti che passaggi risparmiati. Il compromesso: **una sola volta per sessione** l'utente avvia `npx expo start` nella cartella (e `npm install` solo alla primissima creazione); da li' in poi ogni export/fix aggiorna l'app da solo via Fast Refresh — zero terminale nel loop.
**Motivazione:** il loop creativo ideale e': modifichi in Figma → il frame corretto appare sul canvas → l'app nel simulatore si aggiorna da sola. Tutto cio' che e' deterministico (generazione file) deve sparire dal cammino dell'utente; cio' che e' un processo vivo (Metro) si avvia una volta e resta.

## D37 — Osservabilità: log live del bridge + `dck trace` (2026-07)

Richiesta: vedere dal terminale tutto ciò che succede — plugin, validazione, AI,
codegen, file usati/scritti.

1. **Log live del bridge** — `dck serve` ora stampa una riga timestamped per ogni
   evento: avvio (autogen? porta?), /import (nodi, asset, violazioni, KB, file
   scritti, autogen), /validate, /screen/<id>, /review (provider, durata, caratteri),
   /fix (patch applicate, righe del log, durata). Attivo di default; `--quiet` lo
   spegne. Così il terminale del bridge diventa il "registro di bordo" di ogni giro.
2. **`dck trace <screen.json>`** — mappa statica dell'intera pipeline in 6 fasi
   (LETTURA → VALIDAZIONE → BRIDGE → AI → CODEGEN → APP): quali file legge, cosa
   scrive e dove, cosa manda all'AI e cosa accetta indietro, quali file genera
   (lista completa da `Codegen.full_project_files()`), come arrivano sul telefono.
   Legge davvero lo screen e le regole, quindi i conteggi sono quelli reali.
3. **Codegen refactor** — lo scaffold completo estratto in `full_project_files()`
   così `trace` elenca davvero tutti i file generati (prima mancavano package.json,
   app.json, tsconfig, _layout).

126 test OK.

## D38 — Verbose AI: prompt e risposte completi nel log del bridge (2026-07)

Richiesta: vedere ESATTAMENTE cosa viene inviato all'AI e cosa torna indietro.

1. **`dck serve --verbose`** — per ogni /review e /fix il log mostra il PROMPT
   completo (system + user, delimitati `┌─ … │ … └─` con conteggio caratteri/righe)
   e la RISPOSTA grezza del modello, prima di qualsiasi parsing. Nel fix multi-
   tentativo vengono stampati solo i messaggi NUOVI di ogni tentativo (il feedback
   del validatore), non tutta la conversazione ripetuta.
2. **Default invariato e leggibile** — senza `--verbose` il log resta il riepilogo
   di una riga per evento (D37): il traffico AI completo e' lungo (decine di KB),
   va mostrato solo a richiesta. Il banner di avvio suggerisce `--verbose`.
3. **Punto di intercettazione unico** — il dump avviene nel wrapper di `chat_fn`
   e in `ai_review`, cioe' nel bridge: patcher e provider restano invariati.

129 test OK.

## D39 — Piattaforma dichiarata: iOS / Android / Custom (2026-07)

Richiesta: distinguere design iOS, Android e custom — il check e l'AI devono
applicare le regole giuste per la piattaforma per cui il design e' pensato.

1. **Selettore nel plugin** — menu Piattaforma sopra "Esporta selezione"
   (iOS default, Android, Custom, Entrambe). Inviata con /import, /validate,
   /review, /fix; cambiarla rivalida subito lo screen corrente (senza scrivere).
   Il bridge la salva in `meta.platform`: diventa parte del contratto, ereditata
   da review/fix/trace/CLI. Caricando uno screen dal bridge il selettore si allinea.
2. **Semantica nel validatore** — `rules_for_platform()` (funzione pura):
   - ios/android: regole both + quelle della piattaforma;
   - both: tutte (comportamento storico);
   - **custom = la quadra**: regole both invariate; check presenti su entrambe le
     piattaforme (es. touch_target_min 44pt iOS / 48dp Android) FUSI in una regola
     `custom.*` col vincolo piu' stretto (il design funziona su entrambe);
     convenzioni di una sola piattaforma (es. max 5 tab iOS) retrocesse a
     warning: utili da sapere, non bloccanti per un linguaggio proprio.
   Effetto reale su imported-home: ios 10 err/12 warn, android 9/13,
   custom 9/14, both 12/13 (niente piu' doppioni iOS+Android sullo stesso nodo).
3. **AI calibrata** — `_platform_block()` nei prompt di fix e review: per custom
   il modello sa che deve trovare la quadra (vincoli stretti si', convenzioni di
   una sola piattaforma no). Il regolamento mostrato all'AI e' quello filtrato/
   fuso per la piattaforma — mai regole che il validatore non applichera'.
4. **CLI** — `--platform` accetta anche `custom` (validate, import, fix, review);
   fix/review default: meta.platform del file, altrimenti both. `dck trace`
   mostra la piattaforma nella fase LETTURA e VALIDAZIONE.

Nota: alcune regole in ios-hig.yaml sono dichiarate `platform: both`
(accessibilita' universale) pur avendo id ios.* — e' voluto.

134 test OK.

## D40 — Tema dark/light: rilevamento deterministico, MAI AI come validatore (2026-07)

Richiesta: il sistema non riconosce se un design e' dark o light mode; valutare
se introdurre l'AI come controllore/validatore al posto del check deterministico.

**Decisione architetturale: l'AI non diventa MAI il validatore.** Il validatore
e' l'arbitro del sistema: se fosse un LLM, lo stesso design darebbe verdetti
diversi a ogni export (campionamento), il gatekeeper del fix non avrebbe piu' un
criterio affidabile, ogni export costerebbe una chiamata (secondi/minuti vs
millisecondi) e non sarebbe riproducibile ne' testabile. L'AI resta dove serve
giudizio: review consultiva e proposte di patch, sempre sotto validazione.

**La proprieta' mancante (dark/light) e' deterministica, non serve l'AI:**
1. **Rilevamento** — `detect_theme()`: luminanza relativa WCAG dello sfondo
   radice (< 0.5 → dark). Gestisce hex, ref DTCG e forma legacy "token:".
   Priorita': scelta esplicita > meta.theme salvata > rilevamento.
2. **Plugin** — selettore Tema (Auto/Light/Dark, default Auto) accanto a
   Piattaforma; lo status mostra il tema rilevato ("[ios · tema dark]");
   il bridge salva `meta.theme` nel contratto; codegen e AI lo ereditano.
3. **Regole tema-aware** — il Context del validatore ora porta `theme`;
   prima regola: `ux.dark.pure-black` (warning): in dark mode lo sfondo
   radice nero puro cancella la percezione di elevazione (M3 dark theme).
4. **Codegen** — `<StatusBar style="light|dark" />` (expo-status-bar) e
   `userInterfaceStyle` in app.json seguono meta.theme.
5. **AI calibrata** — `_theme_block()` nei prompt: il modello sa se il design
   e' dark/light e ragiona di conseguenza (es. niente ombre come enfasi in
   dark mode).
6. **CLI** — `dck validate --theme auto|light|dark`; `dck trace` mostra il tema.

145 test OK.

## D41 — Patch per id di nodo (addio indici numerici) + timeout realistico (2026-07)

Sintomo reale (log verbose di Sara): il modello risponde con patch RFC 6902 a
indici numerici (/root/children/0/children/5/...) e SBAGLIA gli indici →
"replace: chiave inesistente"; al secondo tentativo il provider va in timeout
(120s troppo pochi per prompt da 25+ KB).

1. **Dialetto semplificato** — il prompt del fix ora chiede operazioni
   {op, node, key, value}: il modello indirizza per ID di nodo (che vede nei
   NODI COINVOLTI), MAI per indici. `normalize_ops()` traduce qui, in modo
   deterministico, id → JSON Pointer reale. La forma RFC 6902 con "path"
   resta accettata (retrocompatibile).
2. **Upsert** — replace/add su chiave di nodo diventano RFC "add" con
   auto-vivificazione dei dizionari intermedi (style/background su nodo senza
   style funziona). Sparisce tutta la classe d'errore "chiave inesistente".
   Il gatekeeper resta il validatore: la patch si applica solo se migliora.
3. **Timeout** — CHAT_TIMEOUT 120s → 300s: i modelli "for coding" su schermate
   grandi impiegano minuti. (Il modo giusto di ridurre il tempo resta schermate
   piu' piccole o fix mirati, non timeout stretti.)

150 test OK.

## D42 — Palette multi-tema + identita' cromatica inviolabile (2026-09)

Sintomo reale (screenshot di Sara): specificato iOS + Dark, il fix e' stato
ACCETTATO (25→9 errori) ma ha trasformato il design scuro in un mockup
chiaro: #000000 → {color.surface} (panna #F7F7F5), brand blu #0088FF →
{color.brand.primary} (verde salvia #5E8F6E). Analisi: il catch-22 —
(a) hex hard-coded = errore; (b) il gatekeeper accetta solo patch che
riducono gli errori; (c) la palette era SOLO light → l'AI era costretta a
"vandalizzare" il design per far passare la patch. Nessuna regola misurava
la fedelta' cromatica. Cure scelte da Sara: A + E (escluse: guard rail di
fedelta' nel gatekeeper, ricalibrazione della regola hex, fix del
pure-black sugli sfondi effettivi).

**A — Palette multi-tema nei token (la cura vera).** Un $value puo' ora
essere {"light": ..., "dark": ...} (varianti anche alias). Il PATH resta
unico — {color.surface} e' il token giusto su entrambi i temi, e' il valore
a cambiare: surface #F7F7F5/#121212, surface-raised #FFFFFF/#1C1C1E,
text-primary #1A1A1A/#F2F2F2, text-secondary #5A5A5A/#A3A3A8, nuovi
neutral.700/800/900. Il brand resta invariante (il brand e' il brand).
Conseguenze a catena, tutte deterministiche:
1. TokenStore.resolve_path/resolve_value accettano theme= (cache per tema).
2. Il validatore risolve i colori NEL tema del design (ctx.theme): il
   contrasto di #FFFFFF su {color.surface} e' errore in light (~1:1) e ok
   in dark (~17:1) — stesso JSON, verdetto giusto per il tema.
3. hex_to_token_map() copre TUTTE le varianti: in import #121212 diventa
   {color.surface}, non un hex nudo. A parita' di hex vince il token
   semantico (dichiarato prima dei primitivi).
4. codegen theme_ts() emette i valori del tema dello screen: un design
   dark genera una theme.ts scura.
5. Il prompt di fix elenca i token come "path → valore nel tema attivo":
   il modello VEDE i colori veri (dark su design dark) invece di indovinare
   dal nome. serve e cli costruiscono il catalogo con resolve_path(p, theme).

**E — Istruzione di identita' cromatica nel system prompt.** "IDENTITA'
CROMATICA INVIOLABILE: dark resta dark, il brand resta il brand. Sostituisci
un hex con un token SOLO se cromaticamente equivalente; se nessun token e'
equivalente, MANTIENI l'hex e segnalalo con note "palette-gap": la
violazione resta aperta, ed e' il comportamento corretto." Il gatekeeper
resta comparativo: una patch che mantiene un hex passa se riduce le ALTRE
violazioni. (normalize_ops ignora il campo "note": e' solo comunicazione
all'utente nel log.)

164 test OK.

## D43 — Feedback di selezione: il plugin dice sempre cosa vede (2026-09)

Sintomo (Sara): selezionando un frame in Figma a volte il plugin "non sente"
la selezione e nei log non appare mai "Frame <nome> selezionato". Diagnosi:
1. `selectionchange` in code.js agiva SOLO con il watch attivo — senza watch
   non c'era proprio nulla in ascolto, zero feedback.
2. Selezionando un elemento DENTRO il frame (testo, bottone) invece del
   frame, `currentTargetNode()` lo scartava silenziosamente tenendo il nodo
   vecchio — dall'esterno: "non ha sentito niente".
3. La selezione vive dentro Figma: il bridge (terminale) non poteva vederla.

Cura:
1. **code.js** — `selectionchange` posta SEMPRE alla UI `selection-changed`
   {id, name, kind, valid} (o null). Con watch attivo, l'export parte solo
   se la NUOVA selezione e' valida (niente piu' export silenzioso del nodo
   vecchio). All'apertura la UI manda `ui-ready` e riceve subito lo stato
   della selezione (anche a bridge spento). Errore export piu' onesto:
   "hai selezionato 'X' (TEXT): non e' un frame".
2. **ui.html** — riga dedicata sopra il bottone: 'selezionato: "Pay"
   (FRAME)' / 'nessuna selezione' / '"X" e' un TEXT, non un frame…'.
3. **bridge** — nuovo endpoint POST /client-log (solo log, nessuna
   scrittura, messaggio troncato a 200): la UI inoltra fire-and-forget
   "frame 'Pay' selezionato" → `[HH:MM:SS] 🖥 plugin: frame "Pay"
   selezionato` nel terminale. --quiet lo silenzia come gli altri log.

170 test OK.

## D44 — Gate in due giudizi: safety deterministica + qualità dal padre (2026-09)

Sintomo reale (Pay-Frame): proposta UX sensata (CTA riposizionata, stepper
corretto, label VoiceOver, Terms leggibile) RIFIUTATA con 23→22 per
"miglioramento insufficiente (1 < 2)". La diagnosi cieca del padre misurava
UX dal PNG, il gate contava hex nel JSON: "cosa fare" e "cosa conta" erano
disallineati. Di converso, togliere il gate avrebbe fatto passare chiavi
morte (`props/label` su Text), conflitti ("ultimo vince" su 4 CTA diverse),
hex su nodi già tokenizzati e `source_url` inventati — tutti visti nei log.

Decisione: il gate resta, ma diviso in due giudizi.
1. SAFETY deterministica e bloccante (invariata e rafforzata): la patch si
   applica, zero nuovi errori, warning non in aumento, conteggio non
   peggiorato. Le ops colpevoli di regressione si scartano da sole (gate
   tollerante): 2 hex cattivi non uccidono più 10 fix buoni.
2. QUALITY con doppia base: basta una — (a) conteggio (soglia di prima) o
   (b) padre: le ops coprono almeno 2 delle 5 priorità della diagnosi cieca
   (match per sottoalbero: fix sul discendente/antenato conta). La base
   usata è registrata (`quality`, `coverage`) in log ed eval.
Motivazione: il determinismo dove è forte (sicurezza), il giudizio dove
serve gusto (qualità) — dal padre che ha visto il PNG, contato in modo
deterministico e testabile. L'AI non diventa validatore (D40 confermata):
la copertura blind è calcolata qui, non chiesta al modello.

## D49 — Brand per-screen letto dal frame (supera D42) (2026-09)

Sintomo reale: il brand demo verde (#5E8F6E, nato con lo scaffold e mai
ratificato) combatteva il blu vero dei design (#0088FF), flaggandolo come
errore; chiedere all'AI di mapparlo sul verde vandalizzava l'identita'.
Decisione (revoca esplicita di D42 sul punto, come D42 stessa prevede):
il brand e' un input per-screen, non un invariante globale.
1. Import (plugin + REST): estrazione deterministica — hex saturo dominante
   per occorrenze+area, neutri e gradienti esclusi — in meta.brand
   ({"color.brand.primary": "#0088FF"}); loggato in /import. Senza brand
   vale il default di tokens.json (vecchio comportamento).
2. Validatore: il brand dello screen e' esente da ds.no-hardcoded-value
   (e' identita', non anonimo). Resta protetto DENTRO lo screen: nessun fix
   puo' ricolorarlo (safety del gate invariata).
3. Prompt: valori effettivi (brand vero, non verde demo) nelle liste token;
   sezioni BRAND DELLO SCREEN intoccabile in fix e propose.
4. Codegen: theme.ts usa il brand dello screen.
Ogni frame puo' avere il suo brand (Pay-Frame blu, Settings ciano).

## D45 — Fedelta' del round-trip Figma↔JSON: angoli, bordi, opacita', rotazione, ellissi, token tematizzati (2026-09)

Sintomo reale (round-trip Settings-Frame, export->render senza modifiche):
card senza sfondo, cerchio back diventato quadrato chiaro, toggle sparito,
bordi/anelli persi. Diagnosi su JSON+codice+PNG esportate:
1. il render non risolveva i token multi-tema ({light,dark} passati come
   oggetti a hexToFigmaColor -> fill vuoto -> superfici trasparenti);
2. l'export non registrava mai cornerRadius, strokes, opacity, rotation e
   scartava le ELLIPSE (levetta del toggle); i componenti mappati perdevano
   comunque i figli per disegno.
Decisione (punti 1-2):
1. render: TOKEN_FLAT tematizzati risolti col tema dello screen
   (meta.theme, fallback light come TokenStore).
2. export (plugin + REST, stessa forma): style.radius (numero grezzo),
   style.cornerSmoothing, style.border {color, weight?, align?},
   style.opacity (<1), layout.rotation (!=0), meta.shape='ellipse' per le
   ellissi (render con createEllipse); meta.corner_mixed se gli angoli
   differiscono (schema v0.1 non li modella). Rotazione/opacita' per OGNI
   tipo di nodo via withGeo. Mai inventare: solo campi presenti col tipo
   giusto. I nuovi campi non creano finding (numeri/oggetti, non hex):
   contratto bloccato da test. Vettori in SVG, boundVariables, effects e
   semantica auto-layout restano P1 (schema v0.2).

## D46 — Vetro, opacita' fill e figli dello Switch nel round-trip (2026-09)

Sintomo reale (round-trip Settings-Frame): back ridisegnato grigio solido
(era #D9D9D9 al 20% + vetro), toggle sparito del tutto.
Diagnosi: export leggeva solo il primo fill opaco e ignorava opacita'
per-fill ed effetti; i componenti mappati perdevano i figli per disegno
(fatale per lo Switch, dove track+levetta sono tutto); la REST non matchava
i suffissi di nome mentre il plugin si.
Decisione: fillHex riporta anche opacita' del fill
(style.backgroundOpacity) e export registra style.backdropBlur dal
BACKGROUND_BLUR; il render applica entrambi. Switch tiene i figli in
entrambi gli importer; match per suffisso anche nella REST (parita' col
plugin). Solo BACKGROUND_BLUR per ora; ombre e figli dei Button restano P1.

## D47 — Rotazione: registrare la traslazione, non il bbox visivo (2026-09)

Sintomo reale (round-trip Settings-Frame, secondo giro): chevron spariti e
track blu del toggle mancante (levetta bianca presente).
Diagnosi: 1) i gruppi chevron hanno rotation:-180 registrata, ma il frame
registrato era il bbox VISIVO post-rotazione mentre Figma legge x/y come
TRASLAZIONE (origine locale): a -180 gradi il nodo finiva spostato di
(-w,-h), sopra la card. (Nota di onesta': un primo fix sull'ordine di
assegnazione nel render era un placebo — x/y e rotation toccano parti
diverse della matrice, l'ordine e' indifferente. Il bug era nei VALORI:
withGeo ora registra traslazione+dimensioni non ruotate per i nodi ruotati,
che il render riproduce alla lettera. Lo stesso fix spiega il "flip" del
primo giro: senza supporto rotazione si vedeva l'icona non ruotata "<".)
2) il fill blu e' proprio del nodo Switch, che non aveva trait
surface/container: entrambi gli importer lo scartavano.
Decisione: withGeo usa node.x/y/width/height per i nodi ruotati (genitore
non ruotato; caso annidato-ruotato resta limite noto). Trait surface allo
Switch in catalogo + condizione surface anche nella REST (il plugin
l'aveva gia'). Neutro per il validatore: nessuna regola chiave su surface.

## D48 — Metriche tipografiche vere ed effetti generici nel round-trip (2026-09)

Sintomo reale: testi quasi giusti ma mai uguali (taglie a bucket, pesi
appiattiti, niente allineamenti) e vetro catturato solo se BACKGROUND_BLUR.
Decisione: export testi con fontSize esatta, fontFamily/fontStyle (dal
PostScript nella REST, da fontName nel plugin), align/valign non-default,
lineHeight, letterSpacing, textCase, textDecoration; flag meta.mixed_style
per i run multi-stile (non modellati, dichiarati). Render con font
originale + fallback Inter. Export effetti in style.effects[] (ombre,
layer blur, vetro, qualunque combinazione; colori via token, resto grezzo);
il singolo backdropBlur resta per i vecchi JSON. Validatore e codegen
leggono solo variant: zero nuovi finding (contratto da test). Fuori:
segmenti multi-stile, font custom nel codegen, semantica auto-layout.

## D50 — dck describe: scheda di stile da PNG (2026-09)

Richiesta: descrivere a parole stile e caratteristiche di un frame dal solo
PNG. Decisione: comando `dck describe <png> [--context] [--platform]
[--out]` (modulo `designchecker/describer.py`, prompt con 7 sezioni fisse:
sintesi, palette, tipografia, layout/ritmo, componenti, stile/mood,
piattaforma; max 300 parole). Regole dichiarate nel prompt: mai hex
esatti, mai misure in pixel, mai inventare testi illeggibili o stati.
Non tocca JSON, non valida: artefatto leggibile (brief, doc design system,
DNA da allegare alle proposte). Richiede modello con vision, altrimenti
errore esplicito.

## D51 — Rimossi review/fix, describe anche in XL (2026-09)

Decisione di strada (non tecnica): i bottoni "Valuta il design" e "Correggi
con AI" lasciano il posto alle schede di stile. Rimossi dal plugin e, in
profondita', dal codice: endpoint /review e /fix, ai_review/ai_fix,
comandi dck, build_fix/review_prompt, fix_loop e relativi helper/test.
Restano: validatore, gate e flusso padre+figli (propose), describe short
(+ opzione XL: analisi per zona, prompt dedicato) da CLI e da plugin con
bottone proprio. README aggiornato; decisioni D31/D35 restano agli atti
come storia.

## D54 — Schede describe salvate in imports (2026-09)

Richiesta: ritrovare le schede come file. Decisione: ogni describe riuscita
via bridge salva `imports/<frame>.describe[.md|-xl.md|-json.md]` per flavor
(short/XL/JSON), con header (frame, flavor, data, modello); ultima vince
(sovrascrittura). Nomi sanitizzati, mai fuori da imports/ (frame ostili:
testo restituito, niente file). La CLI resta esplicita (--out). Niente
oramai: consultive sul design, ma tracciate su disco.

Estensione: la Describe+JSON salva anche lo screen come
`imports/<id>.screen.json` (stesso file di Esporta: elencato in /screens,
ispezionabile, renderizzabile da Scrivi-su-canvas), con stessa guardia
anti-perdita di /import (.preexport.bak) e sidecar sha aggiornato.


## D52 — Describe+JSON ancorata (2026-09)

La scheda XL da solo PNG convince ma resta impressionistica. Nuova
funzionalita': stesso PNG + screen JSON compattato (stessa forma dei
figli), prompt dedicato con sezione "Concordanze e discordanze" — valori
esatti solo dal JSON, percepito solo dal PNG, i disaccordi segnalati.
Bottone plugin "Describe+JSON", flag CLI `--screen`, endpoint /describe
esteso (screen opzionale). Consultiva come le altre describe.

## D53 — Scheda describe allegata al padre di propose (2026-09)

Richiesta: che al padre di propose arrivi la descrizione da una Describe,
e che le Describe non lascino file orfani. Verificato: nessuna describe
salva JSON (consultive per disegno) — la lista file per il Render resta
imports/*.screen.json via /screens; per portare in Figma il JSON di una
Describe+JSON basta Esporta selezione + Render.
Decisione: l'ultima scheda ({frame, flavor, text}) viaggia in memoria e
viene allegata al POST /propose; run_propose la riusa in diagnosi cieca
e figli SOLO se descrive lo stesso screen (match deterministico su
meta.id/nome, mai giudizio LLM; mismatch scartato e loggato). Anche da
CLI con --brief (file markdown, vale per quello screen). Nessun salvataggio
aggiuntivo: niente file, niente orfani.

## D54 — Schede describe salvate in imports (2026-09)

Richiesta: ritrovare le schede come file. Decisione: ogni describe riuscita
via bridge salva `imports/<frame>.describe[.md|-xl.md|-json.md]` per flavor
(short/XL/JSON), con header (frame, flavor, data, modello); ultima vince
(sovrascrittura). Nomi sanitizzati, mai fuori da imports/ (frame ostili:
testo restituito, niente file). La CLI resta esplicita (--out). Niente
oramai: consultive sul design, ma tracciate su disco.
