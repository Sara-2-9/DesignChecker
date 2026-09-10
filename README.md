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

🟢 **MVP + v0.2 + importer Figma funzionanti.** Validatore CLI (48 regole, baseline **Expo SDK 57**, verificato settembre 2026) + codegen verso progetto Expo reale + **import da file Figma collegato con audit immediato**. 40 test OK. Decisioni D1–D24.

### Uso (dalla radice del progetto)

```bash
pip install pyyaml        # unica dipendenza

# Validazione
python3 -m designchecker validate examples/home.screen.json           # conforme → exit 0
python3 -m designchecker validate examples/imported-home.screen.json  # violazioni → exit 1
python3 -m designchecker rules                                        # elenco regole

# Codegen: dallo screen JSON a un'app Expo vera
python3 -m designchecker generate examples/home.screen.json --out examples/generated-app
cd examples/generated-app && npm install && npx expo install --fix && npx expo start

# Import da Figma: collega il file, elenca le schermate, importa + audit
python3 -m designchecker link figma https://www.figma.com/design/<key>/il-tuo-file
python3 -m designchecker screens
python3 -m designchecker import figma "Home"
# (test offline senza token: --fixture examples/figma-file.fixture.json)
```

⚠️ **Preview:** Expo Go SDK 56+ non è più sugli store — su iOS usa una dev build (`npx expo run:ios` con Xcode) o `eas go`; su Android Expo Go via CLI (decisione D19).

### Struttura

```
├── designchecker/     ← tokens, validator, report, cli, loader, codegen
├── rules/             ← 6 file: ios-hig, material3, wcag, design-system, expo-rn, ux-heuristics
├── components.catalog.yaml
├── examples/          ← tokens.json, schermate di esempio, generated-app/ (progetto Expo)
├── tests/             ← 30 test (validatore + codegen)
└── docs/              ← la progettazione completa
```

### Prossimi passi (roadmap)

1. ~~Component library RN + codegen~~ ✅ v0.2
2. Plugin Figma (rendering canvas + sync token via Variables + annotation errori)
3. Importer screenshot → screen JSON (provider layer + modello vision)
4. Generatore LLM dal brief + iterazione a patch
