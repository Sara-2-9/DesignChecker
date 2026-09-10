# 06 — Workflow utente

## Scenario A — Nuova app / nuova funzionalità

**Fase 0 — Brief.**
L'utente descrive a parole: *"Un'app per tracciare le spese condivise tra coinquilini."*

**Fase 1 — Proposta.**
Il sistema genera la prima schermata: pattern di navigazione ufficiale (tab bar iOS / navigation bar M3), token di default, componenti conformi. Visibile **subito su Expo Go / simulatore** e sul canvas Figma.

**Fase 2 — Iterazione (da prompt o da Figma).**
L'utente dice *"primario verde salvia, più spazio tra le card"* — oppure sposta e ricolora direttamente in Figma. Ogni modifica:
1. diventa una **proposta** di modifica al JSON,
2. passa dal **validatore**,
3. se viola una regola: avviso immediato con fonte + correzione proposta
   (*"Il verde salvia #8FBF9F su bianco ha contrasto 2.1:1, sotto il 4.5:1 di WCAG 1.4.3. Ti propongo #5E8F6E che lo supera."*),
4. se valida: applicata → re-render simultaneo di Figma e simulatore.

**Fase 3 — Conferma e validazione finale.**
Al "ok" dell'utente: report completo (touch target, contrasto, safe area, gerarchia, warning euristici Fitts/Hick/Jakob). Solo schermate pulite vengono "confermate".

**Fase 4 — Export.**
Codice TypeScript pulito (Expo Router, StyleSheet.create, SafeAreaView, Pressable…) → copiabile nell'app esistente o sincronizzato su repo. Token DTCG → Figma Variables come riferimento documentale.

## Scenario B — Redesign di app esistente (caso d'uso primario attuale)

1. **Import:** screenshot delle schermate attuali (+ file `.tsx` se disponibili — doppia fonte).
2. **Estrazione:** modello vision → screen JSON (bozza da confermare, con flag di confidenza).
3. **Audit:** il validatore produce il report delle violazioni delle schermate attuali.
4. **Redesign proposto:** stessa funzionalità, regole rispettate, token applicati → subito su Expo Go e Figma.
5. **Iterazione:** loop normale (Scenario A, fase 2) — l'utente decide cosa mantenere e cosa cambiare, a parole o su Figma.

## Chi fa cosa

| Utente | Superficie | Esempio |
|---|---|---|
| Visuale, non tecnico | Figma + plugin | Sposta card, cambia colori dalle variabili; vede badge rossi/arancioni sul canvas in tempo reale |
| Tecnico, avvezzo alle convenzioni | Prompt / CLI | *"La lista diventa FlatList con header sticky, primario token brand.500"* |

Entrambe le superfici passano dallo stesso validatore e aggiornano lo stesso JSON: chi lavora su Figma e chi da terminale vedono sempre la stessa cosa.
