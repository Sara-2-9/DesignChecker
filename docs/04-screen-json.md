# 04 — Screen JSON: il contratto centrale (BOZZA v0.1)

## 0. La decisione di fondo: fisso + estensibile + componibile

Lo schema NON è statico e NON è un elenco infinito di casi. È a tre livelli:

| Livello | Fisso o variabile? | Analogia |
|---|---|---|
| **Scheletro del nodo** | 🔒 Fisso — ogni nodo ha la stessa anatomia | I layer di Figma: tutti hanno nome, posizione, vincoli |
| **Catalogo componenti** | 🔓 Estensibile — `components.catalog.yaml` | La libreria di componenti: cresce, ma ogni entry dichiara le sue proprietà |
| **Composizione della schermata** | ♾️ Aperta — alberi di nodi qualsiasi | Le schermate in Figma: infinite combinazioni dei primitivi |

**Perché funziona:** il validatore non controlla "tipi di componente", controlla **traits** (caratteristiche): `interactive`, `touch_target`, `text`, `navigation_chrome`… Ogni componente del catalogo dichiara i suoi traits → anche un componente custom creato domani viene validato automaticamente, senza toccare né lo schema né il validatore.

---

## 1. I file del sistema

```
project/
├── tokens.json              ← design token, formato W3C DTCG 2025.10
├── app.design.json          ← progetto: schermate, flusso di navigazione, piattaforme
├── components.catalog.yaml  ← catalogo componenti (primitivi + custom)
└── screens/
    ├── home.screen.json
    ├── add-expense.screen.json
    └── …
```

### 1.1 `tokens.json` (DTCG 2025.10)

```json
{
  "color": {
    "brand": {
      "primary":   { "$type": "color", "$value": "#5E8F6E" },
      "on-primary":{ "$type": "color", "$value": "#FFFFFF" }
    },
    "surface":     { "$type": "color", "$value": "{color.neutral.50}" }
  },
  "spacing": {
    "2": { "$type": "dimension", "$value": "8" },
    "4": { "$type": "dimension", "$value": "16" },
    "6": { "$type": "dimension", "$value": "24" }
  },
  "typography": {
    "body":  { "$type": "fontSize", "$value": "16" },
    "title": { "$type": "fontSize", "$value": "28" }
  }
}
```

Nei nodi si referenzia con `"{color.brand.primary}"` — **mai hex hard-coded** (il validatore li segnala come `error`: valore non tokenizzato).

### 1.2 `app.design.json`

```json
{
  "schema_version": "0.1.0",
  "app": { "name": "SpeseCondivise", "platforms": ["ios", "android"] },
  "navigation": {
    "root_pattern": "tabs",
    "screens": [
      { "id": "home",        "route": "/",          "file": "screens/home.screen.json" },
      { "id": "groups",      "route": "/groups",    "file": "screens/groups.screen.json" },
      { "id": "add-expense", "route": "/add-expense","file": "screens/add-expense.screen.json",
        "presentation": "modal" }
    ]
  }
}
```

Mappa 1:1 su Expo Router: `route` → file in `src/app/`, `presentation: modal` → opzione dello Stack.

---

## 2. Anatomia del nodo (lo scheletro fisso)

Ogni nodo — dal bottone alla schermata intera — ha **la stessa struttura**:

```json
{
  "id": "add-expense-fab",
  "type": "Fab",

  "props": { },

  "layout": { },

  "style": { },

  "a11y": { },

  "semantics": { },

  "states": { },

  "platform_variants": { },

  "meta": { },

  "children": [ ]
}
```

| Campo | Obbligatorio | Contenuto |
|---|---|---|
| `id` | ✅ | Stabile, kebab-case, unico nella schermata. È il riferimento per diff, validazione e modifiche da prompt/Figma. |
| `type` | ✅ | Un tipo del catalogo (`components.catalog.yaml`). |
| `props` | per tipo | Proprietà specifiche del tipo: testo, icona, azione, dati. **La parte variabile.** |
| `layout` | ✅ | Vincoli di layout (vedi §3). |
| `style` | ✅ | Solo riferimenti a token (`{color…}`, `{spacing…}`). |
| `a11y` | se interattivo | `role`, `label`, `hint`. Obbligatorio se il componente ha trait `interactive`. |
| `semantics` | opz. | Significato UI/UX: `primary_action: true`, `destructive: true`, `navigation_role`… Il validatore lo usa per le regole strutturali (es. "una sola azione primaria"). |
| `states` | opz. | Varianti di stato: `pressed`, `disabled`, `loading`, `empty`, `error` (vedi §5). |
| `platform_variants` | opz. | Divergenze iOS/Android (vedi §6). |
| `meta` | opz. | Provenienza: `source: generated|imported|user`, `confidence` (per l'importer), note. |
| `children` | opz. | Figli, stesso scheletro. |

**Regola d'oro:** ciò che serve al validatore sta in campi fissi (`layout`, `style`, `a11y`, `semantics`); ciò che è specifico del componente sta in `props`. Così lo scheletro copre *tutti* i componenti presenti e futuri.

---

## 3. `layout`: il ponte Figma ↔ React Native

Auto-layout di Figma e flexbox di React Native sono **lo stesso modello mentale** — lo schema usa quel denominatore comune:

```json
"layout": {
  "direction": "column",            // column | row  (= auto-layout Figma = flexDirection RN)
  "gap": "{spacing.4}",             // spacing tra figli (token)
  "padding": {                      // token, mai numeri nudi
    "top": "{spacing.6}", "horizontal": "{spacing.4}"
  },
  "sizing": {
    "w": "fill",                    // hug | fill | fixed
    "h": "hug"
  },
  "align": "start",                 // start | center | end | stretch
  "safe_area": true                 // solo su contenitori top-level
}
```

| Schema | Figma | React Native |
|---|---|---|
| `direction: column` | auto-layout verticale | `flexDirection: 'column'` |
| `gap` | item spacing | `gap` |
| `padding` | padding auto-layout | `padding…` |
| `sizing: hug` | hug contents | (intrinseco) |
| `sizing: fill` | fill container | `flex: 1` / `alignSelf: 'stretch'` |
| `safe_area` | — | `useSafeAreaInsets()` / `SafeAreaView` |

**Il validatore controlla qui:** safe area presente sui layout top-level (regola Expo, `error`); gap/padding tokenizzati; sizing coerenti.

---

## 4. Il catalogo componenti (`components.catalog.yaml`)

I primitivi iniziali (coprono ~90% delle schermate mobile):

```yaml
# === CONTENITORI ===
- type: Screen
  maps_to: { rn: "SafeAreaView + View", figma: "FRAME" }
  traits: [container, top_level]
  rules_apply: [safe-area]

- type: Stack            # colonna o riga generica
  maps_to: { rn: "View", figma: "FRAME(auto-layout)" }
  traits: [container]

- type: Card
  maps_to: { rn: "View", figma: "FRAME(auto-layout)" }
  traits: [container, surface]
  rules_apply: [contrast-surface]

- type: List             # dati ripetuti
  maps_to: { rn: "FlatList", figma: "FRAME + repeated instances" }
  traits: [container, scrollable]
  rules_apply: [flatlist-not-map]

# === TESTO ===
- type: Text
  maps_to: { rn: "Text", figma: "TEXT" }
  traits: [text]
  props: { content: string, variant: "title|heading|body|caption" }
  rules_apply: [contrast-text, dynamic-type]

# === INTERATTIVI ===
- type: Button
  maps_to: { rn: "Pressable", figma: "COMPONENT" }
  traits: [interactive, touch_target, has_label]
  props: { label: string, action: action, variant: "primary|secondary|destructive" }
  defaults: { min_height: 48 }
  rules_apply: [touch-target, contrast-text, a11y-label, one-primary-action]

- type: Fab
  maps_to: { rn: "Pressable", figma: "COMPONENT" }
  traits: [interactive, touch_target, single_action]
  defaults: { size: 56 }   # Material 3
  rules_apply: [touch-target, a11y-label, safe-area-position, one-primary-action]

- type: TextField
  maps_to: { rn: "TextInput", figma: "COMPONENT" }
  traits: [interactive, touch_target, form_input]
  defaults: { min_height: 48 }   # M3: 48–56dp
  rules_apply: [touch-target, a11y-label, contrast-text]

- type: ListRow
  maps_to: { rn: "Pressable", figma: "COMPONENT" }
  traits: [interactive, touch_target]
  defaults: { min_height: 44 }
  rules_apply: [touch-target, a11y-label]

# === NAVIGAZIONE ===
- type: TabBar
  maps_to: { rn: "Expo Router Tabs", figma: "COMPONENT" }
  traits: [navigation_chrome]
  rules_apply: [max-5-tabs, native-chrome, icon-plus-label]

- type: AppHeader
  maps_to: { rn: "View", figma: "FRAME" }
  traits: [navigation_chrome, text]
  rules_apply: [safe-area]

# === MEDIA ===
- type: Icon
  maps_to: { rn: "@expo/vector-icons", figma: "VECTOR" }
  traits: [decorative]
  rules_apply: [icon-with-label-if-critical]   # warning Fitts se da sola su azione critica

- type: Image
  maps_to: { rn: "expo-image", figma: "RECTANGLE(fill)" }
  traits: [media]
  rules_apply: [a11y-label-if-informative]
```

### Componenti custom

L'utente può aggiungere tipi al catalogo. Obbligo: dichiarare `traits` e `rules_apply`. Esempio:

```yaml
- type: BalanceChart
  custom: true
  maps_to: { rn: "components/balance-chart.tsx", figma: "COMPONENT" }
  traits: [media, informative]
  rules_apply: [a11y-label-if-informative, contrast-text]
```

→ Il validatore lo tratta come qualsiasi primitivo. **Estensibilità senza rompere la validazione.**

---

## 5. `states`: gli stati sono nodi, non commenti

```json
"states": {
  "pressed":  { "style": { "background": "{color.brand.primary-pressed}" } },
  "disabled": { "style": { "background": "{color.neutral.200}" },
                "a11y": { "hint": "Non disponibile" } },
  "loading":  { "replace_with": "SkeletonRow" },
  "empty":    { "replace_with": "EmptyState",
                "props": { "message": "Nessuna spesa ancora",
                           "action": { "label": "Aggiungi la prima", "action": "navigate:/add-expense" } } },
  "error":    { "replace_with": "ErrorState",
                "props": { "retry_action": { "label": "Riprova" } } }
}
```

Il validatore verifica: empty state con azione chiara (regola HIG), error state che spiega cosa fare, contrasto dello stato disabled.

---

## 6. `platform_variants`: divergenze iOS/Android dichiarate

```json
{
  "id": "date-picker",
  "type": "DatePicker",
  "platform_variants": {
    "ios":     { "type": "DatePickerWheel" },
    "android": { "type": "DatePickerDialog" }
  }
}
```

→ In codegen diventano `date-picker.ios.tsx` / `date-picker.android.tsx` (convenzione ufficiale Expo: estensioni di piattaforma, stesso props contract, sempre una versione default).

Le convenzioni di piattaforma divergenti (es. posizione del back button, pattern di navigazione) sono *regole del rules engine*, non hack nei singoli JSON.

---

## 7. Esempio completo: Home di "SpeseCondivise"

```json
{
  "schema_version": "0.1.0",
  "meta": {
    "id": "home",
    "name": "Home",
    "route": "/",
    "status": "draft",
    "source": { "kind": "generated", "model": "kimi-k2" },
    "updated_at": "2026-09-10T14:30:00Z"
  },

  "root": {
    "id": "screen-home",
    "type": "Screen",
    "layout": {
      "direction": "column",
      "safe_area": true,
      "sizing": { "w": "fill", "h": "fill" },
      "padding": { "horizontal": "{spacing.4}" }
    },
    "style": { "background": "{color.surface}" },
    "children": [

      {
        "id": "header",
        "type": "AppHeader",
        "props": { "title": "Ciao Sara 👋", "subtitle": "Casa Rossi · 3 membri" },
        "layout": { "sizing": { "w": "fill", "h": "hug" },
                    "padding": { "vertical": "{spacing.4}" } },
        "style": {},
        "a11y": { "role": "header" }
      },

      {
        "id": "balance-card",
        "type": "Card",
        "layout": { "direction": "column", "gap": "{spacing.2}",
                    "padding": { "all": "{spacing.4}" },
                    "sizing": { "w": "fill", "h": "hug" } },
        "style": { "background": "{color.surface-raised}",
                   "radius": "{radius.lg}" },
        "children": [
          {
            "id": "balance-label",
            "type": "Text",
            "props": { "content": "Il tuo saldo", "variant": "caption" },
            "layout": { "sizing": { "w": "hug", "h": "hug" } },
            "style": { "color": "{color.text-secondary}" }
          },
          {
            "id": "balance-value",
            "type": "Text",
            "props": { "content": "+ 24,50 €", "variant": "title" },
            "layout": { "sizing": { "w": "hug", "h": "hug" } },
            "style": { "color": "{color.success}" },
            "a11y": { "label": "Saldo positivo di 24 euro e 50" }
          }
        ]
      },

      {
        "id": "recent-header",
        "type": "Text",
        "props": { "content": "Spese recenti", "variant": "heading" },
        "layout": { "sizing": { "w": "hug", "h": "hug" },
                    "padding": { "top": "{spacing.6}", "bottom": "{spacing.2}" } },
        "style": { "color": "{color.text-primary}" }
      },

      {
        "id": "expense-list",
        "type": "List",
        "props": {
          "data_source": "expenses.recent",
          "row_component": "ExpenseRow",
          "key_extractor": "expense.id"
        },
        "layout": { "sizing": { "w": "fill", "h": "fill" }, "gap": "{spacing.2}" },
        "style": {},
        "states": {
          "loading": { "replace_with": "SkeletonList" },
          "empty":   { "replace_with": "EmptyState",
                       "props": { "message": "Nessuna spesa ancora",
                                  "action": { "label": "Aggiungi la prima spesa",
                                              "action": "navigate:/add-expense" } } },
          "error":   { "replace_with": "ErrorState",
                       "props": { "retry_action": { "label": "Riprova", "action": "reload:expenses.recent" } } }
        }
      },

      {
        "id": "add-expense-fab",
        "type": "Fab",
        "props": { "icon": "plus", "label": "Aggiungi spesa",
                   "action": "navigate:/add-expense" },
        "layout": { "position": "bottom-trailing",
                    "offset": { "x": "{spacing.4}", "y": "{spacing.4}" } },
        "style": { "background": "{color.brand.primary}",
                   "foreground": "{color.brand.on-primary}" },
        "a11y": { "role": "button", "label": "Aggiungi una nuova spesa" },
        "semantics": { "primary_action": true }
      },

      {
        "id": "main-tabs",
        "type": "TabBar",
        "props": {
          "tabs": [
            { "id": "home",    "icon": "house",   "label": "Home",    "route": "/" },
            { "id": "groups",  "icon": "person.2","label": "Gruppi",  "route": "/groups" },
            { "id": "profile", "icon": "person",  "label": "Profilo", "route": "/profile" }
          ]
        },
        "layout": { "position": "bottom" },
        "style": {},
        "semantics": { "navigation_role": "root_tabs" }
      }
    ]
  }
}
```

---

## 8. Come il validatore legge questo JSON

Esecuzione su `home.screen.json`:

```
✓  safe-area            — Screen dichiara safe_area: true
✓  ios.touch-target     — Fab 56pt ≥ 44pt (HIG); ListRow 44pt ✓
✓  m3.fab-size          — Fab 56dp ✓ (Material 3)
✓  wcag.contrast        — {color.success} su {color.surface-raised}: 4.8:1 ✓
✓  tabs.max-items       — 3 tab ≤ 5 ✓ (HIG)
✓  one-primary-action   — solo add-expense-fab ha primary_action ✓
✓  a11y.labels          — tutti gli interattivi hanno label ✓
✓  empty-state          — expense-list ha empty con azione ✓ (HIG)
⚠  ux.fitts             — 'add-expense-fab' è solo-icona: valuta label visibile
                          (azione critica, legge di Fitts — warning, non bloccante)
```

Esempio di violazione (schermata importata dall'app attuale):

```
✗ ERROR ios.touch-target.min — 'edit-expense-btn' è 36pt, sotto il minimo iOS di 44pt
        Fonte: Apple HIG – Accessibility
        → Suggerimento: padding a 44×44pt o hitSlop
✗ ERROR wcag.1.4.3 — 'balance-value' contrasto 2.9:1, richiesto 4.5:1
        Fonte: WCAG 2.2 – SC 1.4.3
        → Suggerimento: {color.success-strong} (#3D7A4E) raggiunge 5.2:1
✗ ERROR expo.no-hardcoded — 7 valori colore non tokenizzati in 'expense-list'
        → Suggerimento: migrazione automatica ai token disponibile
```

---

## 9. Le modifiche come patch (prompt e Figma)

Ogni modifica — da prompt o dal canvas Figma — è una **proposta di patch** sul JSON (formato JSON Patch, RFC 6902):

```json
[
  { "op": "replace", "path": "/tokens/color/brand/primary/$value", "value": "#8FBF9F" }
]
```

Flusso: patch proposta → validatore (qui: contrasto 2.1:1 → **ERROR** WCAG 1.4.3) → rifiutata con alternativa `#5E8F6E` → utente accetta → patch applicata → re-render Figma + Expo.

---

## 10. Mapping codegen → convenzioni ufficiali Expo

Dal JSON al progetto, seguendo la struttura ufficiale Expo (blog expo.dev, aggiornato gen 2026):

```
src/
├── app/
│   ├── _layout.tsx            ← da navigation.root_pattern (Tabs/Stack)
│   ├── index.tsx              ← route "/" → return <Home />
│   ├── groups.tsx             ← route "/groups"
│   └── add-expense.tsx        ← route "/add-expense" (modal)
├── screens/
│   └── home/
│       ├── index.tsx          ← da home.screen.json (albero nodi)
│       └── components/
│           └── expense-row.tsx
├── components/
│   ├── button.tsx             ← dalla component library (uno per type del catalogo)
│   ├── fab.tsx
│   └── date-picker.ios.tsx    ← da platform_variants
├── hooks/  utils/             ← logica non-UI
└── theme.ts                   ← generato da tokens.json
```

Regole di generazione (diventeranno entry del rules engine `expo-rn.yaml`):

| Convenzione | Fonte |
|---|---|
| Cartella `/src`, routing in `src/app` | Expo blog |
| File route snelli che ritornano screen da `src/screens/` | Expo blog |
| Filename kebab-case (`expense-row.tsx`) — default SDK 55 | Expo blog, changelog gen 2026 |
| Un named export per componente | Expo blog |
| `StyleSheet.create` in fondo al file componente | Expo blog ("modern approach") |
| Varianti `.ios.tsx` / `.android.tsx`, mai `Platform.OS` sparsi | Expo blog |
| `Pressable` per interattivi, `FlatList` per liste, `useSafeAreaInsets()` | convenzioni RN ufficiali |
| TypeScript obbligatorio | template ufficiali Expo |

---

## 11. Perché questo schema copre "tutti i casi"

1. **Componenti nuovi** → si aggiungono al catalogo con traits dichiarati (§4). Schema e validatore intoccati.
2. **Schermate complesse** → composizione di nodi annidati (§7). Lo scheletro non cambia.
3. **Design insoliti** → `props` è per-tipo e aperto; i vincoli di regole restano nei campi fissi.
4. **Import incerto da screenshot** → `meta.confidence` marca i nodi da confermare.
5. **Divergenze di piattaforma** → `platform_variants` (§6), non schemi paralleli.
6. **Stati** → `states` (§5), non schermate duplicate.

## Domande chiuse da questa bozza (da registrare in decisioni.md)

- Scheletro fisso + catalogo estensibile + composizione aperta
- Token solo per riferimento DTCG, hex hard-coded = error
- Modifiche come JSON Patch (RFC 6902) con validazione preventiva
- Convenzioni codegen dal blog ufficiale Expo

## 11bis. Dati mock e interattività cablata (deciso)

**Decisione:** `data_source` contiene solo **nomi di binding**, mai logica. MA il codice generato deve essere un **prototipo provabile** su Expo Go: dati mock realistici, azioni dei pulsanti cablate, campi editabili.

### Come funziona

**Nel progetto di design:**

```
project/
├── mocks/
│   ├── expenses.mock.json      ← dati finti ma realistici
│   └── groups.mock.json
└── screens/home.screen.json    ← "data_source": "expenses.recent" (solo binding)
```

**Nel codice generato:**

```
src/
├── data/
│   ├── mock/expenses.ts        ← generato da expenses.mock.json
│   └── use-expenses.ts         ← UNICO punto di accesso ai dati (hook)
└── screens/home/index.tsx      ← la UI non sa da dove vengono i dati
```

**Il contratto:** la UI parla solo con l'hook. Quando arriverà il DB vero, si sostituisce *un solo file* (`use-expenses.ts`) e la UI non cambia. Il mock è quindi anche il "contratto dati" dell'app.

### Cosa è cablato davvero nel prototipo

| Elemento | Comportamento nel preview Expo Go |
|---|---|
| FAB / bottoni di navigazione | Navigazione **reale** via Expo Router |
| Liste | Popolate dal mock, scrollabili, aggiornabili |
| TextField / textarea / form | Editabili, con stati (focus, errore di validazione) |
| Submit | Aggiunge al mock in memoria → la lista si aggiorna live |
| Stati empty/loading/error | Attivabili dal preview per provarli |

### Nuove regole per `expo-rn.yaml`

```yaml
- id: expo.no-mock-inline
  severity: error
  message: "Dati mock inline nel componente UI — i dati passano solo da src/data/ (hook)"
- id: expo.action-wired
  severity: warning
  message: "'{name}' è interattivo ma senza azione — cablala o marcalo 'unimplemented'"
```

## 12. Azioni: la DSL (deciso — D16)

Forma **canonica** = oggetto strutturato:

```json
"action": { "type": "navigate", "route": "/add-expense", "presentation": "modal" }
"action": { "type": "submit", "form": "add-expense-form",
            "on_success": { "type": "back" },
            "on_error":  { "type": "show-state", "state": "error" } }
"action": { "type": "toggle", "target": "dark-mode-switch" }
"action": { "type": "reload", "data_source": "expenses.recent" }
```

**Shorthand** (normalizzati dal validatore nella forma canonica):

```json
"action": "navigate:/add-expense"   // = { "type": "navigate", "route": "/add-expense" }
"action": "back"                    // = { "type": "back" }
```

Tipi iniziali: `navigate`, `back`, `open-modal`, `close-modal`, `submit`, `toggle`, `set-field`, `reload`, `unimplemented` (marcatore esplicito, silenzia il warning `expo.action-wired`).

Il validatore controlla: route esistente in `app.design.json`, stato referenziato esistente nel nodo, form/data_source esistenti.

## 13. Versionamento (deciso — D17)

- **Git** conserva le versioni: ogni conferma = commit, ogni esplorazione = branch (parallelo con Figma branching).
- **`history.jsonl`** (append-only) registra ogni patch applicata: contenuto della patch, prompt o gesto Figma che l'ha generata, esito validazione, timestamp. È l'audit del "perché", non lo storage.

```json
{"ts":"2026-09-10T15:02:11Z","screen":"home","origin":"prompt","prompt":"primario verde salvia","patch":[{"op":"replace","path":"/tokens/color/brand/primary/$value","value":"#5E8F6E"}],"validation":"applied-with-correction","note":"proposto #8FBF9F rifiutato: contrasto 2.1:1 < 4.5:1 (WCAG 1.4.3)"}
```

## 14. Stato dello schema

✅ Tutte le questioni aperte sono chiuse. Lo schema v0.1 è completo e pronto come base per:
1. la component library React Native (i `maps_to.rn` del catalogo),
2. le prime ~40 regole YAML del validatore,
3. il MVP da terminale.

