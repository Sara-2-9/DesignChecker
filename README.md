# DesignChecker

**Dal design all'app reale, con le regole ufficiali dalla tua parte.**

DesignChecker è un sistema che collega design e codice: propone e ridisegna schermate di app mobile (Expo / React Native) già conformi alle regole ufficiali di UI/UX (Apple HIG, Material Design 3, WCAG, convenzioni Expo), valida ogni modifica in tempo reale segnalando errori e warning con la fonte della regola, e tiene sincronizzati Figma, simulatore Expo Go e codice esportabile.

## Principi guida

1. **Le regole sono dati, non codice** — regole in YAML versionate con fonte ufficiale citata; aggiornare il sistema = aggiornare i dati.
2. **Una sola fonte di verità** — lo screen JSON + i token DTCG. Figma e il prompt sono *superfici di editing*, non peer da sincronizzare.
3. **Validazione sempre, prima di tutto** — ogni modifica passa dal validatore prima di toccare la fonte di verità. Errori (bloccanti, regole ufficiali) vs warning (euristiche UX).
4. **L'LLM è intercambiabile** — il core è deterministico; l'AI è dietro un provider layer e l'utente sceglie il modello (cloud o locale).
5. **Figma resta la tela visuale** — ma vincolata: si modifica *dentro* le regole, con feedback immediato.

## Documentazione

| Doc | Contenuto | Stato |
|---|---|---|
| [decisioni.md](decisioni.md) | Registro delle decisioni progettuali | ✅ aggiornato |
| [docs/01-visione-e-obiettivi.md](docs/01-visione-e-obiettivi.md) | Problema, soluzione, differenziale | ✅ |
| [docs/02-architettura.md](docs/02-architettura.md) | Livelli del sistema, flussi di sincronizzazione | ✅ |
| [docs/03-rules-engine.md](docs/03-rules-engine.md) | Regole ufficiali, fonti, schema YAML delle regole | ✅ |
| [docs/04-screen-json.md](docs/04-screen-json.md) | Schema dello screen JSON (il contratto centrale) | ✅ v0.1 completo |
| [docs/05-provider-layer.md](docs/05-provider-layer.md) | Scelta del modello AI, capabilities, menu | ✅ |
| [docs/06-workflow-utente.md](docs/06-workflow-utente.md) | Flussi d'uso: brief, iterazione, import per redesign | ✅ |
| [docs/07-roadmap.md](docs/07-roadmap.md) | MVP → v0.4 | ✅ |

## Stato del progetto

🟢 **MVP → v0.4 (plugin Figma + AI) funzionanti.** Validatore CLI (48 regole, baseline **Expo SDK 57**, verificato settembre 2026) + codegen Expo (anche **fedele alla geometria Figma**, D33) + import da Figma (REST o **plugin**, zero rate limit) e da codice .tsx + generazione in progetto nuovo/esistente + **annotazioni real-time sul canvas Figma** + **integrazione AI** (review consultiva + fix con validatore gatekeeper, provider a scelta dell'utente) + **immagini vere nell'app** (PNG esportati dal plugin → `require()` nel progetto Expo, D34) + **AI con regolamento completo e contesto opzionale** (D35) + **autogen dell'app a ogni export/fix** (`dck serve --autogen`, D36) + **osservabilità completa** (log live del bridge + `dck trace`, D37) + **prompt e risposte AI completi nel log** (`dck serve --verbose`, D38) + **selezione piattaforma iOS/Android/Custom** nel plugin, con la "quadra" cross-platform nel validatore e nell'AI (D39) + **tema dark/light rilevato automaticamente** (luminanza dello sfondo, StatusBar e AI calibrati — l'AI non diventa mai il validatore, D40). 145 test OK. Decisioni D1–D40.

### Installazione (una volta sola)

```bash
cd ~/Desktop/DesignChecker
bash install.sh        # crea venv + dipendenze + comando globale
# apri un nuovo terminale, poi da QUALSIASI cartella:
designchecker version
```

### Uso

```bash
# dentro il progetto puoi anche usare: python3 -m designchecker ...

# Validazione
python3 -m designchecker validate examples/home.screen.json           # conforme → exit 0
python3 -m designchecker validate examples/imported-home.screen.json  # violazioni → exit 1
python3 -m designchecker rules                                        # elenco regole

# Codegen: dallo screen JSON a un'app Expo vera
python3 -m designchecker generate examples/home.screen.json --out examples/generated-app
cd examples/generated-app && npm install && npx expo start
# (le dipendenze del package.json generato sono gia' allineate a SDK 57)
# Se lo screen ha geometria Figma (layout.frame), il codegen usa posizionamento
# assoluto: nel simulatore vedi la stessa composizione del canvas (D33).
# Se lo screen arriva dal plugin, immagini e icone sono i PNG veri esportati
# da Figma (D34): finiscono in src/assets/ e vengono caricate con require().

# Import da Figma: collega il file, elenca le schermate, importa + audit
python3 -m designchecker link figma https://www.figma.com/design/<key>/il-tuo-file
python3 -m designchecker screens
python3 -m designchecker import figma "Home"
# (test offline senza token: --fixture examples/figma-file.fixture.json)

# Import da codice: punta una schermata .tsx dell'app esistente → screen JSON + audit
python3 -m designchecker import code percorso/alla/tua/screens/home/index.tsx
# (parsing statico AST via Node; segue anche i componenti custom importati)

# Dopo OGNI import ti viene chiesto dove generare il codice Expo:
#   [i] progetto collegato · [n] nuovo progetto su Desktop · [e] altro progetto · [s] no
# Il progetto scelto resta collegato (config locale). Gestione manuale:
designchecker project                 # mostra il progetto collegato
designchecker project ~/Desktop/mia-app   # collega/cambia
designchecker project --forget        # scollega

# AI: l'utente sceglie il provider (locale Ollama/LM Studio, o cloud con API key)
designchecker ai                      # rileva i provider, menu due gruppi, probe, salva la scelta
designchecker ai --probe              # ri-testa il provider salvato
designchecker review imports/home2.screen.json   # valutazione qualitativa del design (consultiva)
designchecker fix imports/home2.screen.json      # l'AI propone una patch, il validatore approva
```

Provider cloud supportati (selezionabili in `dck ai` incollando la API key):
- **Kimi Code** — se hai un abbonamento Kimi con Kimi Code incluso: genera la chiave
  dalla console Kimi Code (kimi.com/code) e incollala in `dck ai`. Usa la quota
  dell'abbonamento, non crediti API separati. ⚠️ Le chiavi della console Kimi Code,
  di platform.kimi.ai e di platform.moonshot.cn NON sono intercambiabili (401).
- **Kimi API pay-as-you-go**, **Claude**, **OpenAI** — con la rispettiva API key
- **HuggingFace Inference** — token da huggingface.co/settings/tokens; crediti
  mensili gratuiti inclusi anche negli account free
- **Endpoint custom** OpenAI-compatibile (base URL + modello + chiave)

L'AI non tocca mai il JSON senza permesso del validatore deterministico: una patch
è applicata solo se riduce gli errori senza aumentare i warning (decisione D31).

### Plugin Figma (real-time + scrittura canvas, senza rate limit)

```bash
# 1. In un terminale, dalla cartella del progetto:
designchecker serve          # bridge locale su http://localhost:7357 (lasciarlo aperto)
designchecker serve --autogen ~/Desktop/la-mia-app   # + rigenera l'app Expo a ogni export/fix (D36)
designchecker serve --quiet                          # senza il log live (di default attivo, D37)
designchecker serve --verbose                        # + prompt e risposte AI completi nel log (D38)
```

Mentre il bridge gira, il suo terminale è il **registro di bordo**: ogni evento
(/import con nodi/asset/violazioni/file scritti, /validate, /screen, /review,
/fix con durata e provider) è una riga timestamped. Per la mappa completa e
statica della pipeline su uno screen specifico:

```bash
designchecker trace examples/home.screen.json   # 6 fasi: LETTURA → VALIDAZIONE → BRIDGE → AI → CODEGEN → APP (D37)
```

2. In Figma (desktop o browser): **Menu → Plugins → Development → Import plugin from manifest…** → seleziona `DesignChecker/plugin/manifest.json`
3. Seleziona un frame-schermata sul canvas → **Plugins → Development → DesignChecker**
4. Scegli la **Piattaforma** dal menu in alto (iOS / Android / Custom / Entrambe, D39): determina quali regole applica il validatore e come ragiona l'AI. "Custom" = design cross-platform: vale il vincolo più stretto tra iOS e Android, le convenzioni di una sola piattaforma diventano warning. Accanto, il **Tema** (D40): Auto lo rileva dalla luminanza dello sfondo, oppure forza Light/Dark — guida validatore, AI e StatusBar del codice generato
5. **"Esporta selezione e valida"** → audit con errori/warning + rettangoli rossi/arancio disegnati sul canvas sui nodi che violano le regole. Immagini e icone del frame vengono esportate come PNG veri in `imports/assets/<schermata>/` (D34)
6. Attiva **"Tempo reale"**: ogni modifica al frame viene ri-validata (debounce ~1s) e le annotazioni si aggiornano da sole
7. **Scrittura**: inserisci l'id di uno screen importato (es. `home2`) → **Render** → il plugin crea il frame nativo sul canvas dal JSON. Con gli export del plugin il render è **fedele**: geometria reale e immagini/icone clonate dall'originale (D32)
8. **AI** (dopo `designchecker ai`): **"Valuta il design"** per un parere qualitativo, **"Correggi con AI"** per una patch automatica — accettata solo se il validatore conferma il miglioramento, poi renderizzata sul canvas
```

⚠️ **Preview:** Expo Go SDK 56+ non è più sugli store — su iOS usa una dev build (`npx expo run:ios` con Xcode) o `eas go`; su Android Expo Go via CLI (decisione D19).

### Struttura

```
├── designchecker/     ← tokens, validator, report, cli, loader, codegen, importer_figma, importer_code, serve (bridge), ai (provider), patcher (fix loop)
├── plugin/            ← plugin Figma (manifest.json, code.js, ui.html): export, annotazioni real-time, render canvas, valuta/correggi con AI
├── tools/             ← tsx2json.cjs: parser statico TSX (Node + @babel/parser) per dck import code
├── rules/             ← 6 file: ios-hig, material3, wcag, design-system, expo-rn, ux-heuristics
├── components.catalog.yaml
├── examples/          ← tokens.json, schermate di esempio, generated-app/ (progetto Expo)
├── tests/             ← 145 test (validatore + codegen + importer + bridge + AI + log/trace + piattaforme + tema)
└── docs/              ← la progettazione completa
```

### Prossimi passi (roadmap)

1. ~~Component library RN + codegen~~ ✅ v0.2
2. Plugin Figma (rendering canvas + sync token via Variables + annotation errori)
3. Importer screenshot → screen JSON (provider layer + modello vision)
4. Generatore LLM dal brief + iterazione a patch
