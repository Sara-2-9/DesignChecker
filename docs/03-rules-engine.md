# 03 — Rules Engine: le regole ufficiali

## Principio

Le regole sono **dati YAML versionati**, non codice (decisione D1). Ogni regola cita la fonte ufficiale e la sua versione. Aggiornare DesignChecker alle ultime novità = aggiornare i file in `rules/`, con changelog legato alle release ufficiali (WWDC a giugno, Google I/O a maggio, update W3C).

## Struttura dei file

```
rules/
├── ios-hig.yaml          ← Apple Human Interface Guidelines
├── material3.yaml        ← Material Design 3 (Android)
├── wcag.yaml             ← WCAG 2.2 (accessibilità, base legale EU)
├── expo-rn.yaml          ← convenzioni Expo / React Native
├── figma-bp.yaml         ← Figma Best Practices (figma.com/best-practices)
└── ux-heuristics.yaml    ← leggi UX e psicologia (severità: warning)
```

> Nota: `figma-bp.yaml` è speciale — controlla **come viene costruito il file Figma**, non la schermata. Molte sue regole sono "garantite per costruzione" dal renderer Figma; il validatore interviene solo se l'utente le viola editando a mano il canvas. Vedi sezione dedicata in fondo.

## Schema di una regola

```yaml
- id: ios.touch-target.min
  source: "Apple HIG – Accessibility"
  source_url: "https://developer.apple.com/design/human-interface-guidelines/accessibility"
  platform: ios            # ios | android | both | web
  severity: error          # error (bloccante) | warning (euristico)
  check: "interactive.min_size_pt >= 44"
  message: "Target '{name}' è {actual}pt, sotto il minimo iOS di 44pt"
  suggestion: "Porta l'area touch ad almeno 44×44pt"
  rule_version: "2025-06"  # versione della fonte al momento della codifica
```

## Severità (decisione D2)

- **`error`** — regola ufficiale violata, deterministica, bloccante. La modifica non viene applicata senza correzione.
- **`warning`** — euristica UX/psicologica. La modifica viene applicata ma segnalata, con spiegazione.

## Regole numeriche di base (fonti verificate)

### Vincoli dimensionali

| Regola | Valore | Fonte | Severità |
|---|---|---|---|
| Touch target iOS (default) | 44×44 pt (min. assoluto 28×28) | Apple HIG – Accessibility | error |
| Padding attorno a elementi con bordo | ~12 pt (~24 pt senza bordo) | Apple HIG | warning |
| Touch target Android | 48×48 dp | Material Design 3 | error |
| Spacing minimo tra target | 8 dp | Material Design 3 | error |
| FAB | 56 dp | Material Design 3 | error |
| Bottom navigation height | 48–56 dp | Material Design 3 | error |
| Text field height | 48–56 dp | Material Design 3 | error |
| Target minimo legale (AA) | 24×24 px o 24 px di distanza | WCAG 2.2 – SC 2.5.8 | error |
| Target enhanced (AAA) | 44×44 px | WCAG 2.2 – SC 2.5.5 | warning |

**Soglia operativa del validatore:** il massimo tra le piattaforme target → 44 pt (iOS) / 48 dp (Android), automaticamente sopra WCAG AA.

### Accessibilità e tipografia

| Regola | Valore | Fonte | Severità |
|---|---|---|---|
| Contrasto testo normale | ≥ 4.5:1 | WCAG 1.4.3 | error |
| Contrasto testo grande | ≥ 3:1 | WCAG 1.4.3 | error |
| Supporto Dynamic Type / font scaling | obbligatorio | Apple HIG / WCAG | error |
| Label accessibile (VoiceOver/TalkBack) su ogni interattivo | obbligatorio | WCAG 4.1.2 | error |
| Colore mai unico veicolo di significato | + icona/label/forma | WCAG 1.4.1 | error |
| Rispetto Reduce Motion | obbligatorio | WCAG 2.3.3 / HIG | warning |
| Verifica in dark e light mode | obbligatoria | HIG / M3 | error |

### Navigazione e struttura

| Regola | Fonte | Severità |
|---|---|---|
| Tab bar iOS / navigation bar M3 di sistema, no chrome custom che sostituisce i nativi | Apple HIG / M3 | error |
| Max ~5 item nella tab bar | Apple HIG | error |
| Un'unica azione primaria per schermata | HIG / M3 | error |
| Empty state con azione chiara, mai schermate vuote | HIG | warning |
| Errori che spiegano cosa fare | HIG | warning |

### Convenzioni Expo / React Native

| Regola | Severità |
|---|---|
| SafeAreaView / useSafeAreaInsets() sui layout top-level (notch, aree di sistema) | error |
| Pressable per i bottoni (non TouchableOpacity deprecati) | warning |
| FlatList per liste (no map su ScrollView) | warning |
| StyleSheet.create, niente stili inline ripetuti | warning |
| Expo Router per la navigazione | warning |
| Flexbox only (no CSS Grid) | error |
| TypeScript-first | warning |

## Euristiche UX (sempre `warning`)

| Euristica | Traduzione in controllo |
|---|---|
| **Fitts** | Azioni primarie in basso (zona pollice); target grandi per azioni frequenti; mai solo-icona per azioni critiche (icona + label) |
| **Hick** | Warning se > N azioni equivalenti in una schermata; menu con troppe voci → suggerire chunking/progressive disclosure |
| **Jakob** | Warning su pattern di navigazione non convenzionali (gli utenti si aspettano ciò che già conoscono) |
| **Miller (7±2)** | Chunking di liste e gruppi |
| **Peak-end rule, effetto estetica-usabilità** | Checklist qualitativa nel report finale, non validazione automatica |

## Figma Best Practices (`figma-bp.yaml`)

Fonte: figma.com/best-practices (guide ufficiali: components/styles/shared libraries, variants, organizzazione file, branching, UX writing, prototyping). Queste regole non riguardano la schermata ma **la costruzione del file Figma** — quindi lavorano sul renderer Figma, non sullo screen JSON.

| Regola Figma ufficiale | Come la applichiamo | Severità |
|---|---|---|
| Componenti riusabili al posto di copie staccate ("change once, update everywhere") | Il renderer crea **COMPONENT Figma** dal catalogo; le schermate usano istanze. La duplicazione è impossibile per costruzione. Se l'utente stacca un'istanza a mano → avviso | error (detach) |
| Varianti per stati/temi/variazioni (non frame separati) | `states` del nodo → varianti del componente Figma | garantita per costruzione |
| Organizzazione libreria con **pagine e frame** come contenitori (es. pagina "Buttons", frame "Primary"/"Secondary") | Il file Figma generato ha una pagina "Components" organizzata per categoria del catalogo | garantita per costruzione |
| Naming con slash (`Component/State`, `Icon/Name`), mai nomi generici ("Rectangle 1") | Layer nominati da `type`/`id` del nodo. Se l'utente rinomina con nome generico → avviso | warning |
| Auto-layout ovunque, mai posizionamento assoluto | Il modello `layout` dello schema È auto-layout | garantita per costruzione |
| Styles/Variables per colori e tipografia | Token DTCG → Figma Variables | garantita per costruzione |
| Overlays per modali/dropdown (non schermate duplicate) | `presentation: modal` nello screen JSON → overlay in Figma | garantita per costruzione |
| Branching per esplorare idee senza toccare il main | Le proposte di modifica = branch concettuali; parallelo con git (D13) | workflow |
| Contenuti/UX writing curati, microcopy reale | Il generatore produce testi realistici (no lorem ipsum) | warning |

**Nota di principio:** le best practice Figma nascono per *umani che usano Figma a mano*. DesignChecker *genera* il file Figma, quindi la maggior parte diventa "garantita per costruzione"; il validatore resta come guardia per gli edit manuali sul canvas.

## Processo di aggiornamento delle regole

1. Release ufficiale (WWDC / Google I/O / W3C / aggiornamenti guide Figma) → review delle fonti.
2. Aggiornamento/aggiunta entry YAML con `rule_version` aggiornata.
3. Changelog delle regole + bump di versione di DesignChecker.
4. Le regole vecchie restano nella storia: mai cancellare, deprecare.
