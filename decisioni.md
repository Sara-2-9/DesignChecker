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
5. **TabBar → Native Tabs**: il trigger per la route index e' sempre presente (senza, Native Tabs renderizza una schermata vuota); i nomi icona passano per una mappa verso SF Symbols validi (fallback `circle`); un tab "search" diventa `role="search"` (tab di ricerca nativo iOS 26); per ogni tab senza schermata viene generata una route segnaposto (Native Tabs richiede una route reale per trigger). A monte, l'export plugin appiattisce un livello i contenitori intermedi di tab (es. "Tab Bar Buttons") e ricava l'icona dal figlio vettoriale invece che dal nome del layer.
**Motivazione:** `dck generate` su uno screen importato deve dare nel simulatore la stessa composizione vista in Figma — altrimenti il giro Figma→JSON→app perde la meta' del valore.

