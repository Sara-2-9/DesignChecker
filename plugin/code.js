// DesignChecker — code.js (sandbox Figma, Plugin API)
// Girera DENTRO Figma: niente REST, niente rate limit (D21/D26/D29).
// La rete passa SOLO da ui.html; qui: lettura canvas, export screen JSON,
// overlay di annotazione, render JSON -> frame nativi.
/* global figma, __html__ */
'use strict';

// ---------------------------------------------------------------- catalogo/token
// Arrivano dal bridge via UI (init-data). Fallback minimi se offline.
let CATALOG = null;       // {Screen: {traits: [...]}, ...}
let HEX_TO_TOKEN = {};    // "#RRGGBB" -> "color.brand.primary"
let TOKEN_FLAT = {};      // path -> valore risolto (per il render)
let RENDER_THEME = 'light'; // tema usato per risolvere i token multi-tema nel render
let USED_IDS = {};        // dedup id per export: 'bg' x2 -> 'bg', 'bg-2'

function uniqueId(base) {
  base = (base || 'node').trim() || 'node';
  const n = USED_IDS[base] || 0;
  USED_IDS[base] = n + 1;
  return n === 0 ? base : base + '-' + (n + 1);
}

const ALIASES = {
  tabbar: 'TabBar', navbar: 'TabBar', navigationbar: 'TabBar',
  bottombar: 'TabBar', bottomnavigation: 'TabBar',
  header: 'AppHeader', appbar: 'AppHeader', topbar: 'AppHeader',
  fab: 'Fab', floatingactionbutton: 'Fab',
  card: 'Card', list: 'List', flatlist: 'List',
  button: 'Button', textfield: 'TextField', input: 'TextField',
  switch: 'Switch', row: 'ListRow', listrow: 'ListRow',
  listitem: 'ListRow', image: 'Image', icon: 'Icon',
  emptystate: 'EmptyState', errorstate: 'ErrorState',
  skeleton: 'SkeletonList', skeletonlist: 'SkeletonList',
};

// fallback se il bridge e' offline: traits dei tipi principali
const FALLBACK_TRAITS = {
  Screen: ['container', 'top_level'], Stack: ['container'],
  Card: ['container', 'surface'], List: ['container', 'scrollable'],
  Text: ['text'], Button: ['interactive', 'touch_target', 'has_label'],
  Fab: ['interactive', 'touch_target'], TextField: ['interactive', 'touch_target'],
  ListRow: ['interactive', 'touch_target'], Switch: ['interactive', 'touch_target'],
  TabBar: ['navigation_chrome'], AppHeader: ['navigation_chrome', 'text'],
  Icon: ['decorative'], Image: ['media'],
  EmptyState: ['container', 'text'], ErrorState: ['container', 'text'],
  SkeletonList: ['container'],
};

// ---------------------------------------------------------------- utilities
function norm(name) { return (name || '').toLowerCase().replace(/[^a-z0-9]/g, ''); }

function kebab(name) {
  return (name || '')
    .replace(/([a-z0-9])([A-Z])/g, '$1-$2')
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, '-')
    .replace(/-{2,}/g, '-')
    .replace(/^-|-$/g, '');
}

function rgbHex(c) {
  const to = (v) => Math.round(v * 255).toString(16).padStart(2, '0').toUpperCase();
  return '#' + to(c.r) + to(c.g) + to(c.b);
}

function solidHex(fills) {
  if (!Array.isArray(fills)) return null;
  for (const fill of fills) {
    if (fill.type === 'SOLID' && fill.visible !== false) return rgbHex(fill.color);
  }
  return null;
}

// Sfondo nodo: [hex, visualBg, opacity]. Gradiente -> media pesata degli stop
// (approssimazione dichiarata in meta.visual_bg, D30); immagine -> [null, 'image'].
// opacity e' quella del fill scelto (1 se opaco): senza, un #D9D9D9 al 20% con
// vetro veniva registrato come grigio pieno e il render lo ridisegnava solido.
function fillHex(fills) {
  if (!Array.isArray(fills)) return [null, null, 1];
  for (const fill of fills) {
    if (fill.visible === false) continue;
    const op = (fill.opacity == null ? 1 : fill.opacity);
    if (fill.type === 'SOLID') return [rgbHex(fill.color), null, op];
    if (fill.type && fill.type.startsWith('GRADIENT')) {
      const stops = fill.gradientStops || [];
      if (stops.length) {
        const tot = stops.reduce((s, st) => s + (st.color.a == null ? 1 : st.color.a), 0) || 1;
        const avg = { r: 0, g: 0, b: 0 };
        for (const st of stops) {
          const a = st.color.a == null ? 1 : st.color.a;
          avg.r += st.color.r * a; avg.g += st.color.g * a; avg.b += st.color.b * a;
        }
        return [rgbHex({ r: avg.r / tot, g: avg.g / tot, b: avg.b / tot }), 'gradient', op];
      }
    }
    if (fill.type === 'IMAGE') return [null, 'image', op];
  }
  return [null, null, 1];
}

function tokenOrHex(hex) {
  const path = HEX_TO_TOKEN[hex.toUpperCase()];
  return path ? '{' + path + '}' : hex;
}

function spacingToken(px) {
  // nearest entro ±1px sui spacing del bridge
  let best = null, bestDist = 2;
  for (const key of Object.keys(TOKEN_FLAT)) {
    if (!key.startsWith('spacing.')) continue;
    const v = parseFloat(TOKEN_FLAT[key]);
    if (isNaN(v)) continue;
    const d = Math.abs(v - px);
    if (d < bestDist) { best = key; bestDist = d; }
  }
  return best ? '{' + best + '}' : px; // numero nudo: il validatore lo segnala
}

function textVariant(fontSize) {
  if (fontSize >= 24) return 'title';
  if (fontSize >= 18) return 'heading';
  if (fontSize >= 14) return 'body';
  return 'caption';
}

function traitsOf(type) {
  if (CATALOG && CATALOG[type] && CATALOG[type].traits) return CATALOG[type].traits;
  return FALLBACK_TRAITS[type] || [];
}

function catalogMatch(name) {
  const n = norm(name);
  const types = CATALOG ? Object.keys(CATALOG)
    : Object.keys(FALLBACK_TRAITS);
  for (const t of types) if (n === norm(t)) return [t, 0.95];
  if (ALIASES[n]) return [ALIASES[n], 0.9];
  // prefisso: MAI per Screen ("screenshot…" non e' una schermata)
  for (const t of types) if (t !== 'Screen' && n.startsWith(norm(t))) return [t, 0.85];
  for (const a of Object.keys(ALIASES)) if (n.startsWith(a)) return [ALIASES[a], 0.75];
  for (const a of Object.keys(ALIASES)) if (n.endsWith(a)) return [ALIASES[a], 0.7];
  return [null, 0];
}

// chrome di dispositivo nei mockup: NON e' contenuto dell'app, va saltato
const DEVICE_CHROME = /^(status[\s-]?bar|dynamic[\s-]?island|home[\s-]?indicator|notch)/i;

// glifi SF Symbols / private use area: non sono label leggibili
const PUA = /[\uE000-\uF8FF\u{F0000}-\u{FFFFD}\u{100000}-\u{10FFFD}]/u;

function readableLabel(raw, fallback) {
  const text = (raw || '').trim();
  if (!text || PUA.test(text)) return (fallback || 'tab').trim();
  return text;
}

function isIconFontGlyph(s) {
  // glifi di icon-font (es. Material Icons come caratteri PUA): non sono etichette
  const t = (s || '').trim();
  return t.length > 0 && t.length <= 4 && PUA.test(t);
}

function firstText(node) {
  if (!('children' in node)) return null;
  for (const child of node.children) {
    if (child.type === 'TEXT' && !isIconFontGlyph(child.characters)) return child.characters;
    const found = firstText(child);
    if (found) return found;
  }
  return null;
}

function tabNodesOf(bar) {
  // I componenti TabBar spesso annidano i tab in un contenitore intermedio
  // (es. "Tab Bar Buttons"): un figlio diretto SENZA un testo proprio e con
  // piu' di un figlio e' un contenitore → appiattisci un livello.
  const out = [];
  for (const c of bar.children || []) {
    if (c.visible === false) continue;
    const kids = 'children' in c ? c.children.filter((g) => g.visible !== false) : [];
    const ownText = kids.some((g) => g.type === 'TEXT');
    if (kids.length > 1 && !ownText) out.push(...kids);
    else out.push(c);
  }
  // scarta i non-tab: sfondi/decorazioni senza testo ne' icona
  return out.filter(isTabLike);
}

function findIconName(tab) {
  // cerca un discendente il cui nome suggerisce l'icona ("icon/home", "house"…)
  let found = null;
  (function walk(n) {
    if (found || !('children' in n)) return;
    for (const c of n.children) {
      if (found) return;
      const nm = (c.name || '').toLowerCase();
      const looksIcon = /icon|glyph/.test(nm) ||
        (['VECTOR', 'BOOLEAN_OPERATION', 'STAR', 'ELLIPSE'].includes(c.type) && (c.width || 99) <= 32);
      if (looksIcon) {
        const cleaned = nm.replace(/^icons?\/?/, '').trim();
        if (cleaned) { found = cleaned; return; }
      }
      walk(c);
    }
  })(tab);
  return found;
}

function isTabLike(n) {
  // un tab vero ha un'etichetta o un'icona; i contenitori puramente
  // decorativi (sfondi tipo "BG") non sono tab
  return firstText(n) != null || findIconName(n) != null;
}

function tabIcon(tab, label) {
  return kebab(findIconName(tab) || label);
}

function actionFromReactions(node) {
  for (const reaction of node.reactions || []) {
    const action = reaction.action;
    if (action && action.type === 'NODE' && action.destinationId) {
      const dest = figma.getNodeById(action.destinationId);
      return 'navigate:/' + kebab(dest ? dest.name : 'screen');
    }
  }
  return null;
}

// ---------------------------------------------------------------- export
let exportMap = {};      // dc id -> figma node id (per le annotazioni)
let pendingAssets = [];  // [{node, ref}] — nodi Image/Icon da esportare come PNG (D34)
// Geometria fedele (D32): layout.frame di ogni nodo e' relativo al GENITORE
// (non al root) — in render i figli sono posizionati dentro il frame parent.

function backdropBlur(node) {
  // Scorciatoia per il vetro comune (BACKGROUND_BLUR): raggio o null.
  // Per l'array completo (ombre comprese) vedi effectInfo sotto.
  const effs = node.effects;
  if (!Array.isArray(effs)) return null;
  for (const e of effs) {
    if (!e || e.visible === false || e.type !== 'BACKGROUND_BLUR') continue;
    if (typeof e.radius === 'number') return Math.round(e.radius * 10) / 10;
    return 0;
  }
  return null;
}

function effectInfo(node) {
  // Tutti gli effetti visibili in forma seriale: ombre, blur di livello e vetro.
  // Colori via tokenOrHex, resto numeri grezzi. Mai inventare: tipi ignoti saltati.
  const effs = node.effects;
  if (!Array.isArray(effs)) return null;
  const out = [];
  for (const e of effs) {
    if (!e || e.visible === false) continue;
    const t = e.type;
    const isShadow = t === 'DROP_SHADOW' || t === 'INNER_SHADOW';
    const isBlur = t === 'LAYER_BLUR' || t === 'BACKGROUND_BLUR';
    if (!isShadow && !isBlur) continue;
    const item = { type: t };
    if (typeof e.radius === 'number') item.radius = Math.round(e.radius * 10) / 10;
    if (isShadow) {
      if (e.offset && (e.offset.x || e.offset.y)) {
        item.offset = { x: Math.round((e.offset.x || 0) * 10) / 10,
                        y: Math.round((e.offset.y || 0) * 10) / 10 };
      }
      if (typeof e.spread === 'number' && e.spread !== 0) {
        item.spread = Math.round(e.spread * 10) / 10;
      }
      if (e.color) {
        const hex = rgbHex({ r: e.color.r, g: e.color.g, b: e.color.b });
        if (hex) {
          item.color = tokenOrHex(hex);
          const a = (e.color.a == null ? 1 : e.color.a);
          if (a < 1) item.opacity = Math.round(a * 1000) / 1000;
        }
      }
      if (e.blendMode && e.blendMode !== 'NORMAL') item.blendMode = e.blendMode;
    }
    out.push(item);
  }
  return out.length ? out : null;
}

function strokeInfo(node) {
  // Primo bordo solido visibile: {color, weight?, align?} o null.
  // Il colore passa per tokenOrHex come gli sfondi (token restano token,
  // hex restano hex e il validatore li segnala). Opacita' per-fill e pesi
  // misti non modellati: limite noto, mai inventare valori.
  const sts = node.strokes;
  if (!Array.isArray(sts)) return null;
  for (const s of sts) {
    if (!s || s.visible === false || s.type !== 'SOLID') continue;
    const hex = s.color ? rgbHex(s.color) : null;
    if (!hex) continue;
    const out = { color: tokenOrHex(hex) };
    if (typeof node.strokeWeight === 'number') {
      out.weight = Math.round(node.strokeWeight * 100) / 100;
    }
    if (node.strokeAlign && node.strokeAlign !== 'CENTER') out.align = node.strokeAlign;
    return out;
  }
  return null;
}

function withGeo(out, node, bounds, parentBox) {
  // Geometria + id Figma (per clonare immagini/icone dal nodo sorgente).
  // Nodo NON ruotato: x/y del riquadro visivo relativo al genitore
  // (bounds - parentBox: per genitori non ruotati e' la traslazione).
  // Nodo RUOTATO: x/y di Figma sono la TRASLAZIONE (origine locale), mentre
  // absoluteBoundingBox e' il riquadro visivo post-rotazione. Registrare il
  // visivo come traslazione sposta il nodo di (-w,-h) a 180 gradi (bug dei
  // chevron finiti sopra la card): si registrano traslazione e dimensioni
  // non ruotate del nodo, che il render riproduce alla lettera.
  // (L'ordine di assegnazione nel render e' irrilevante: x/y toccano solo la
  // traslazione, rotation solo la sottomatrice 2x2.)
  const rot = (typeof node.rotation === 'number') ? node.rotation : 0;
  if (bounds && bounds.width != null) {
    out.layout = out.layout || {};
    if (rot !== 0 && parentBox && typeof node.x === 'number' && typeof node.y === 'number' &&
        typeof node.width === 'number' && typeof node.height === 'number') {
      out.layout.frame = {
        x: Math.round(node.x * 100) / 100,
        y: Math.round(node.y * 100) / 100,
        w: Math.round(node.width * 100) / 100,
        h: Math.round(node.height * 100) / 100,
      };
    } else {
      out.layout.frame = {
        x: Math.round(bounds.x - (parentBox ? parentBox.x : bounds.x)),
        y: Math.round(bounds.y - (parentBox ? parentBox.y : bounds.y)),
        w: Math.round(bounds.width),
        h: Math.round(bounds.height),
      };
    }
  }
  // rotazione e opacita' valgono per OGNI tipo di nodo (anche testi e icone):
  // senza, il JSON descrive un oggetto diverso da quello disegnato.
  if (typeof node.rotation === 'number' && node.rotation !== 0) {
    out.layout = out.layout || {};
    out.layout.rotation = Math.round(node.rotation * 100) / 100;
  }
  if (typeof node.opacity === 'number' && node.opacity < 1) {
    out.style = out.style || {};
    out.style.opacity = Math.round(node.opacity * 1000) / 1000;
  }
  out.meta = out.meta || {};
  out.meta.figma_node_id = node.id;
  return out;
}

function convertNode(node, topLevel, parentBox) {
  const name = node.name || 'node';
  const bounds = node.absoluteBoundingBox || {};

  // chrome di dispositivo (Status bar, Dynamic Island…): mai validato
  if (!topLevel && DEVICE_CHROME.test(name)) return null;

  if (node.type === 'VECTOR') {
    const out = withGeo({
      id: uniqueId(kebab(name) || 'icon'), type: 'Icon',
      props: { name: norm(name) || 'icon' },
      layout: {}, style: {},
      meta: { source: 'figma-plugin', confidence: 0.9 },
    }, node, bounds, parentBox);
    pendingAssets.push({ node: node, ref: out });
    return out;
  }

  if (node.type === 'TEXT') {
    // Metriche tipografiche vere (non solo variant): misura esatta, famiglia,
    // peso, allineamenti, interlinea, tracking, maiuscole, decorazioni.
    // Solo non-default oltre l'identita' (fontSize/famiglia/peso sempre):
    // i default Figma (LEFT/TOP/ORIGINAL/NONE) si omettono per non gonfiare il JSON.
    const size = Number(node.fontSize) || 16;
    const out = {
      id: uniqueId(kebab(name) || 'text'), type: 'Text',
      props: { content: node.characters || '', variant: textVariant(size),
               fontSize: Math.round(size * 10) / 10 },
      layout: { sizing: { w: 'hug', h: 'hug' } },
      style: {},
      meta: { source: 'figma-plugin', confidence: 1.0 },
    };
    const fn = node.fontName;
    if (fn && typeof fn.family === 'string') {
      out.props.fontFamily = fn.family.slice(0, 60);
      if (typeof fn.style === 'string') out.props.fontStyle = fn.style.slice(0, 40);
    } else if (fn != null) {
      out.meta.mixed_style = true; // run multi-stile: pesi/famiglie non modellati
    }
    if (typeof node.textAlignHorizontal === 'string' && node.textAlignHorizontal !== 'LEFT') {
      out.props.align = node.textAlignHorizontal;
    }
    if (typeof node.textAlignVertical === 'string' && node.textAlignVertical !== 'TOP') {
      out.props.valign = node.textAlignVertical;
    }
    const lh = node.lineHeight;
    if (lh && typeof lh === 'object' && lh.unit && lh.unit !== 'AUTO') {
      out.props.lineHeight = lh.value != null
        ? { unit: lh.unit, value: Math.round(lh.value * 100) / 100 }
        : { unit: lh.unit };
    }
    const ls = node.letterSpacing;
    if (ls && typeof ls === 'object' && typeof ls.value === 'number' && ls.value !== 0) {
      out.props.letterSpacing = { unit: ls.unit || 'PIXELS',
                                  value: Math.round(ls.value * 100) / 100 };
    }
    if (typeof node.textCase === 'string' && node.textCase !== 'ORIGINAL') {
      out.props.textCase = node.textCase;
    }
    if (typeof node.textDecoration === 'string' && node.textDecoration !== 'NONE') {
      out.props.textDecoration = node.textDecoration;
    }
    const color = solidHex(node.fills);
    if (color) out.style.color = tokenOrHex(color);
    return withGeo(out, node, bounds, parentBox);
  }

  if (!['FRAME', 'INSTANCE', 'GROUP', 'RECTANGLE', 'COMPONENT', 'COMPONENT_SET', 'ELLIPSE'].includes(node.type)) {
    return null;
  }

  let dcType, confidence;
  if (topLevel) {
    dcType = 'Screen'; confidence = 1.0;
  } else {
    [dcType, confidence] = catalogMatch(name);
    if (dcType === null) {
      const hasImage = Array.isArray(node.fills) &&
        node.fills.some((f) => f.type === 'IMAGE' && f.visible !== false);
      if (hasImage) { dcType = 'Image'; confidence = 0.7; }
      else { dcType = 'Stack'; confidence = node.type === 'GROUP' ? 0.6 : 0.5; }
    }
  }

  const traits = traitsOf(dcType);
  const out = {
    id: uniqueId(kebab(name) || 'node'),
    type: dcType,
    props: {},
    layout: {},
    style: {},
    meta: { source: 'figma-plugin', confidence: confidence, figma_name: name, figma_type: node.type },
  };
  exportMap[out.id] = node.id;
  withGeo(out, node, bounds, parentBox);

  // layout da auto-layout
  if (node.layoutMode === 'VERTICAL') out.layout.direction = 'column';
  if (node.layoutMode === 'HORIZONTAL') out.layout.direction = 'row';
  if (node.itemSpacing) out.layout.gap = spacingToken(node.itemSpacing);
  const pad = {};
  if (node.paddingLeft && node.paddingLeft === node.paddingRight) pad.horizontal = spacingToken(node.paddingLeft);
  if (node.paddingTop && node.paddingTop === node.paddingBottom) pad.vertical = spacingToken(node.paddingTop);
  if (Object.keys(pad).length) out.layout.padding = pad;
  if (topLevel) {
    out.layout.safe_area = true;
    out.layout.sizing = { w: 'fill', h: 'fill' };
  }

  const [bg, visualBg, bgOpacity] = fillHex(node.fills);
  if (bg && (traits.includes('container') || traits.includes('surface') || topLevel)) {
    out.style.background = tokenOrHex(bg);
    if (bgOpacity != null && bgOpacity < 1) {
      out.style.backgroundOpacity = Math.round(bgOpacity * 1000) / 1000;
    }
  }
  if (visualBg) out.meta.visual_bg = visualBg;
  const glass = backdropBlur(node);
  if (glass != null) out.style.backdropBlur = glass;
  // Array completo degli effetti (vetro qualunque tipo + ombre): il singolo
  // backdropBlur sopra resta per i JSON gia' esportati (retrocompatibilita').
  const effects = effectInfo(node);
  if (effects) out.style.effects = effects;

  // fedelta' visiva (punto 2): angoli, smoothing, bordi, forma ellisse.
  // Prima si esportava solo il primo fill: cerchi diventavano quadrati,
  // anelli/bordi sparivano, le ellissi venivano scartate del tutto.
  if (typeof node.cornerRadius === 'number') {
    out.style.radius = Math.round(node.cornerRadius * 100) / 100;
  } else if (node.cornerRadius !== undefined) {
    out.meta.corner_mixed = true; // angoli diversi: lo schema v0.1 non li modella
  }
  if (typeof node.cornerSmoothing === 'number' && node.cornerSmoothing > 0) {
    out.style.cornerSmoothing = Math.round(node.cornerSmoothing * 100) / 100;
  }
  const border = strokeInfo(node);
  if (border) out.style.border = border;
  if (node.type === 'ELLIPSE') out.meta.shape = 'ellipse';

  // touch target: misure REALI dal canvas
  if (traits.includes('interactive') && bounds.width) {
    out.props.min_height = Math.round(Math.min(bounds.width || 0, bounds.height || 0));
  }

  if (dcType === 'Button') {
    const label = firstText(node);
    if (label) out.props.label = label;
  }
  if (dcType === 'TabBar' && 'children' in node) {
    out.props.tabs = tabNodesOf(node).map((child, i) => {
      const label = readableLabel(firstText(child), child.name).split('/').pop().trim();
      const tab = { id: kebab(label), icon: tabIcon(child, label), label: label,
                    route: i === 0 ? '/' : '/' + kebab(label) };
      // convenzione: il primo tab e' la home (route index); un tab "search"
      // diventa il tab di ricerca nativo iOS (NativeTabs role="search")
      if (/search|cerca/i.test(label) || /search/.test(tab.icon)) tab.role = 'search';
      return tab;
    });
    out.semantics = { navigation_role: 'root_tabs' };
  }

  const action = actionFromReactions(node);
  if (action && traits.includes('interactive')) out.props.action = action;

  if (traits.includes('interactive')) {
    out.a11y = { role: 'button', label: out.props.label || name };
  }

  if ('children' in node) {
    const children = node.children.map((c) => convertNode(c, false, bounds)).filter(Boolean);
    // I componenti mappati non esportano i figli (sono primitivi), TRANNE lo
    // Switch: track+levetta sono la sua verita' visiva (es. "Toggle - Switch":
    // senza figli l'interruttore sparisce dal render e perde lo stato ON).
    if (children.length && ['Screen', 'Stack', 'Card', 'List', 'Switch'].includes(dcType)) {
      out.children = children;
    }
  }
  if (dcType === 'Image' || dcType === 'Icon') {
    pendingAssets.push({ node: node, ref: out });
  }
  return out;
}

// Esporta i nodi Image/Icon come PNG (D34): i bytes viaggiano nel messaggio
// verso la UI, che li inoltra al bridge (li salva in imports/assets/<screen>/);
// il codegen poi li copia nel progetto Expo come require() locali.
async function collectAssets(screenId) {
  const assets = [];
  for (const item of pendingAssets) {
    try {
      const bytes = await item.node.exportAsync({ format: 'PNG' });
      const fname = screenId + '-' + item.ref.id + '.png';
      item.ref.props = item.ref.props || {};
      item.ref.props.asset = 'assets/' + screenId + '/' + fname;
      assets.push({ path: fname, data_base64: figma.base64Encode(bytes) });
    } catch (e) { /* nodo non esportabile: restera' il placeholder */ }
  }
  return assets;
}

// Esporta il frame intero come PNG 2x per la vision del padre (flusso propose).
// Ritorna base64 o null. Separata da collectAssets: e' la vista reale,
// non i singoli asset.
async function exportPreview(node) {
  try {
    const bytes = await node.exportAsync({ format: 'PNG', constraint: { type: 'SCALE', value: 2 } });
    return figma.base64Encode(bytes);
  } catch (e) { return null; }
}

function extractBrand(root) {
  // Brand dello screen = colore saturo piu' "pesante" del frame
  // (occorrenze + area). Neutri/grigi esclusi per saturazione, gradienti
  // approssimati esclusi (visual_bg): il brand e' il colore distintivo.
  // D49: il brand e' un input per-screen letto dal canvas, non piu' il verde
  // demo congelato — ma resta protetto DENTRO lo screen (mai ricolorato).
  function sat(hex) {
    const n = parseInt(hex.slice(1), 16);
    const r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
    return (Math.max(r, g, b) - Math.min(r, g, b)) / 255;
  }
  const scores = {};
  function walk(n) {
    if (!n || typeof n !== 'object') return;
    const st = n.style || {};
    const fr = (n.layout || {}).frame || {};
    const area = (fr.w || 0) * (fr.h || 0);
    const skip = n.meta && n.meta.visual_bg;
    const vals = [st.background, st.color, st.border && st.border.color].filter(Boolean);
    for (const v of vals) {
      if (typeof v !== 'string' || !v.startsWith('#') || skip) continue;
      if (sat(v) < 0.15) continue;
      const key = v.toUpperCase();
      const s = scores[key] || { n: 0, area: 0 };
      s.n += 1;
      s.area += area;
      scores[key] = s;
    }
    for (const c of n.children || []) walk(c);
  }
  walk(root);
  let best = null, bestScore = -1;
  for (const hex of Object.keys(scores)) {
    const s = scores[hex];
    const score = s.n * 1000 + Math.min(s.area, 1000000);
    if (score > bestScore) { bestScore = score; best = hex; }
  }
  return best;
}

function exportFrame(node) {
  exportMap = {};
  USED_IDS = {};
  pendingAssets = [];
  const root = convertNode(node, true, node.absoluteBoundingBox);
  const meta = {
    id: kebab(node.name), name: node.name + ' (import plugin Figma)',
    route: '/' + kebab(node.name), status: 'draft',
    source: { kind: 'figma-plugin', confidence: root.meta.confidence },
  };
  const brand = extractBrand(root);
  if (brand) meta.brand = { 'color.brand.primary': brand };
  return {
    schema_version: '0.1.0',
    meta: meta,
    root: root,
  };
}

// ---------------------------------------------------------------- annotazioni
const OVERLAY_NAME = 'DesignChecker — annotazioni';

function clearAnnotations() {
  const old = figma.currentPage.findOne((n) => n.name === OVERLAY_NAME);
  if (old) old.remove();
}

async function annotate(findings) {
  clearAnnotations();
  const items = [];
  for (const f of findings) {
    if (f.node_id === '(schermata)') continue;
    const figmaId = exportMap[f.node_id];
    if (!figmaId) continue;
    const node = figma.getNodeById(figmaId);
    if (!node || !node.absoluteBoundingBox) continue;
    items.push({ f: f, box: node.absoluteBoundingBox });
  }
  if (!items.length) return;

  await figma.loadFontAsync({ family: 'Inter', style: 'Medium' });
  const overlay = figma.createFrame();
  overlay.name = OVERLAY_NAME;
  overlay.clipsContent = false;
  overlay.fills = [];
  overlay.locked = true;
  const minX = Math.min.apply(null, items.map((i) => i.box.x));
  const minY = Math.min.apply(null, items.map((i) => i.box.y));
  overlay.x = minX; overlay.y = minY;
  overlay.resize(1, 1); // i figli escono dai bordi: clipsContent=false

  for (const item of items) {
    const isError = item.f.severity === 'error';
    const rect = figma.createRectangle();
    rect.x = item.box.x - minX;
    rect.y = item.box.y - minY;
    rect.resize(Math.max(item.box.width, 1), Math.max(item.box.height, 1));
    rect.fills = [];
    rect.strokes = [{ type: 'SOLID', color: isError ? { r: 1, g: 0.23, b: 0.19 } : { r: 1, g: 0.62, b: 0.04 } }];
    rect.strokeWeight = 2;
    rect.dashPattern = [6, 4];
    rect.name = (isError ? '✗ ' : '⚠ ') + item.f.rule_id;
    overlay.appendChild(rect);

    const label = figma.createText();
    label.fontName = { family: 'Inter', style: 'Medium' };
    label.fontSize = 10;
    label.characters = item.f.rule_id;
    label.fills = [{ type: 'SOLID', color: isError ? { r: 1, g: 0.23, b: 0.19 } : { r: 0.85, g: 0.45, b: 0.02 } }];
    label.x = item.box.x - minX;
    label.y = item.box.y - minY - 14;
    label.name = 'label ' + item.f.rule_id;
    overlay.appendChild(label);
  }
  figma.currentPage.appendChild(overlay);
}

// ---------------------------------------------------------------- render JSON -> canvas
function tokenValue(ref) {
  // "{color.brand.primary}" -> valore; altrimenti ritorna il valore cosi' com'e'.
  // I token multi-tema arrivano come {light, dark}: si risolve con il tema
  // dello screen in render (meta.theme). Prima si restituiva l'oggetto cosi'
  // com'era e ogni fill tematizzato diventava trasparente (bug card invisibili).
  if (typeof ref === 'string' && ref.startsWith('{') && ref.endsWith('}')) {
    const path = ref.slice(1, -1);
    if (!(path in TOKEN_FLAT)) return null;
    const v = TOKEN_FLAT[path];
    if (v && typeof v === 'object') return v[RENDER_THEME] || v.light || v.dark || null;
    return v;
  }
  return ref;
}

function hexToFigmaColor(hex) {
  if (typeof hex !== 'string' || !hex.startsWith('#')) return null;
  const n = parseInt(hex.slice(1), 16);
  return { r: ((n >> 16) & 255) / 255, g: ((n >> 8) & 255) / 255, b: (n & 255) / 255 };
}

function num(v, fallback) {
  const n = parseFloat(v);
  return isNaN(n) ? fallback : n;
}

const VARIANT_SIZES = { title: 24, heading: 18, body: 14, caption: 12 };

function fontSizeFor(variant) {
  const tok = TOKEN_FLAT['typography.' + variant];
  return num(tok, VARIANT_SIZES[variant] || 14);
}

async function textFont(family, style, variant) {
  // Prova il font originale del design (es. SF Pro), con fallback a Inter:
  // loadFontAsync fallisce se la famiglia/peso non e' disponibile.
  const want = { family: family || 'Inter',
                 style: style || ((variant === 'title' || variant === 'heading') ? 'Bold' : 'Regular') };
  try { await figma.loadFontAsync(want); return want; } catch (e) { /* fallback sotto */ }
  const fb = { family: 'Inter',
               style: (variant === 'title' || variant === 'heading') ? 'Bold' : 'Regular' };
  try { await figma.loadFontAsync(fb); } catch (e2) { /* Inter precaricato in renderScreen */ }
  return fb;
}

function mapEffect(ef) {
  // JSON -> effetto Figma. Solo campi per-tipo (lo spread su un blur
  // farebbe fallire l'assegnazione): lo strict qui protegge il render.
  if (!ef || typeof ef !== 'object') return null;
  const t = ef.type;
  const isShadow = t === 'DROP_SHADOW' || t === 'INNER_SHADOW';
  const isBlur = t === 'LAYER_BLUR' || t === 'BACKGROUND_BLUR';
  if (!isShadow && !isBlur) return null;
  const out = { type: t, visible: true };
  if (ef.radius != null) out.radius = num(ef.radius, 0);
  if (isShadow) {
    out.offset = { x: num(ef.offset && ef.offset.x, 0), y: num(ef.offset && ef.offset.y, 0) };
    if (ef.spread != null) out.spread = num(ef.spread, 0);
    if (ef.color) {
      const c = hexToFigmaColor(tokenValue(ef.color));
      if (!c) return null;
      out.color = { r: c.r, g: c.g, b: c.b, a: ef.opacity != null ? ef.opacity : 1 };
    } else {
      out.color = { r: 0, g: 0, b: 0, a: 0.25 };
    }
    if (ef.blendMode) out.blendMode = ef.blendMode;
  }
  return out;
}

function applyVisualStyle(frame, node) {
  // Applica gli stili di fedelta' registrati in export (punto 2):
  // bordi, smoothing, opacita', rotazione. Tutto in try/catch per nodo:
  // un campo non applicabile non deve mai bloccare il render.
  const style = node.style || {};
  const layout = node.layout || {};
  try {
    const b = style.border;
    if (b && typeof b === 'object') {
      const bc = hexToFigmaColor(tokenValue(b.color));
      if (bc) {
        frame.strokes = [{ type: 'SOLID', color: bc }];
        if (b.weight != null) frame.strokeWeight = num(b.weight, 1);
        if (b.align) frame.strokeAlign = b.align;
      }
    }
    if (style.cornerSmoothing != null) frame.cornerSmoothing = num(style.cornerSmoothing, 0);
    if (style.opacity != null) frame.opacity = Math.max(0, Math.min(1, num(style.opacity, 1)));
    if (layout.rotation != null) frame.rotation = num(layout.rotation, 0);
    // Effetti: l'array completo vince; il singolo backdropBlur resta per i
    // vecchi JSON (e si somma solo se l'array non ha gia' un vetro).
    try {
      const mapped = (Array.isArray(style.effects) ? style.effects : []).map(mapEffect).filter(Boolean);
      const legacy = (style.backdropBlur != null && !mapped.some((m) => m.type === 'BACKGROUND_BLUR'))
        ? [{ type: 'BACKGROUND_BLUR', radius: num(style.backdropBlur, 8), visible: true }]
        : [];
      if (mapped.length || legacy.length) frame.effects = [...mapped, ...legacy];
    } catch (e2) { /* effetti non supportati: ignora */ }
  } catch (e) { /* singolo stile non applicabile: ignora */ }
}

function newFrame(dcType, id) {
  const frame = figma.createFrame();
  frame.name = dcType + ': ' + id;
  frame.fills = [];
  return frame;
}

function applyContainerStyle(frame, node, isRoot, isEllipse) {
  const layout = node.layout || {};
  const style = node.style || {};
  // Le ellissi non hanno auto-layout: solo riempimento e stili visivi.
  if (isEllipse) {
    const bg = hexToFigmaColor(tokenValue(style.background));
    if (bg) {
      const paint = { type: 'SOLID', color: bg };
      if (style.backgroundOpacity != null) {
        paint.opacity = Math.max(0, Math.min(1, num(style.backgroundOpacity, 1)));
      }
      frame.fills = [paint];
    }
    applyVisualStyle(frame, node);
    try { frame.setPluginData('dc_id', node.id || ''); } catch (e) { /* read-only */ }
    return;
  }
  const dir = layout.direction === 'row' ? 'HORIZONTAL' : 'VERTICAL';
  frame.layoutMode = dir;
  frame.primaryAxisSizingMode = 'AUTO';
  frame.counterAxisSizingMode = isRoot ? 'FIXED' : 'AUTO';
  if (layout.gap != null) frame.itemSpacing = num(tokenValue(layout.gap), 8);
  const pad = layout.padding || {};
  const ph = num(tokenValue(pad.horizontal != null ? pad.horizontal : pad.all), 0);
  const pv = num(tokenValue(pad.vertical != null ? pad.vertical : pad.all), 0);
  frame.paddingLeft = frame.paddingRight = ph;
  frame.paddingTop = frame.paddingBottom = pv;
  const bg = hexToFigmaColor(tokenValue(style.background));
  if (bg) {
    const paint = { type: 'SOLID', color: bg };
    if (style.backgroundOpacity != null) {
      paint.opacity = Math.max(0, Math.min(1, num(style.backgroundOpacity, 1)));
    }
    frame.fills = [paint];
  } else {
    frame.fills = [];
  }
  const radius = num(tokenValue(style.radius), 0);
  if (radius) frame.cornerRadius = radius;
  applyVisualStyle(frame, node);
  if (isRoot) frame.resize(390, 844); // iPhone 14/15 reference
  frame.setPluginData('dc_id', node.id || '');
}

async function renderNode(node, parent, isRoot) {
  const type = node.type;
  const props = node.props || {};

  if (type === 'Text') {
    const t = figma.createText();
    t.fontName = { family: 'Inter', style: props.variant === 'title' || props.variant === 'heading' ? 'Bold' : 'Regular' };
    t.fontSize = fontSizeFor(props.variant);
    t.characters = props.content || '';
    try { t.textAutoResize = 'WIDTH_AND_HEIGHT'; } catch (e) { /* versioni vecchie */ }
    const color = hexToFigmaColor(tokenValue((node.style || {}).color));
    if (color) t.fills = [{ type: 'SOLID', color: color }];
    t.name = 'Text: ' + (node.id || '');
    t.setPluginData('dc_id', node.id || '');
    parent.appendChild(t);
    return;
  }

  if (type === 'Button' || type === 'Fab') {
    const frame = newFrame(type, node.id);
    const isFab = type === 'Fab';
    const bg = hexToFigmaColor(tokenValue((node.style || {}).background)) ||
      hexToFigmaColor(tokenValue('{color.brand.primary}')) || { r: 0.35, g: 0.34, b: 0.84 };
    frame.fills = [{ type: 'SOLID', color: bg }];
    frame.cornerRadius = isFab ? 28 : 12;
    frame.layoutMode = 'HORIZONTAL';
    frame.primaryAxisAlignItems = 'CENTER';
    frame.counterAxisAlignItems = 'CENTER';
    // label visiva: mai la stringa 'Button' su stepper senza label.
    // plus/minus -> glifi, altrimenti props.label; le label a11y verbali
    // ('Increase amount by $5') restano allo screen reader, non sul canvas.
    const nid = String(node.id || '').toLowerCase();
    let visual = props.label || props.content || '';
    if (!visual) {
      if (nid.includes('plus')) visual = '+';
      else if (nid.includes('minus')) visual = '−';
      else visual = 'Button';
    }
    if (isFab) { frame.primaryAxisSizingMode = 'FIXED'; frame.counterAxisSizingMode = 'FIXED'; frame.resize(56, 56); }
    else {
      frame.primaryAxisSizingMode = 'AUTO'; frame.counterAxisSizingMode = 'FIXED';
      frame.paddingLeft = frame.paddingRight = 16;
      const w = Math.max(120, String(visual).length * 9 + 32);
      frame.resize(w, num(props.min_height, 48));
      frame.primaryAxisSizingMode = 'AUTO';
    }
    parent.appendChild(frame);
    const label = figma.createText();
    label.fontName = { family: 'Inter', style: 'Medium' };
    label.fontSize = fontSizeFor('body');
    label.characters = visual;
    label.fills = [{ type: 'SOLID', color: { r: 1, g: 1, b: 1 } }];
    frame.appendChild(label);
    if (isFab && parent.layoutMode) {
      // posizione bassa-destra: il vincolo lo gestisce il designer; qui resta in flusso
    }
    return;
  }

  if (type === 'TextField') {
    const frame = newFrame(type, node.id);
    applyContainerStyle(frame, node, false);
    frame.counterAxisSizingMode = 'FIXED';
    frame.layoutMode = 'HORIZONTAL';
    frame.paddingLeft = frame.paddingRight = 14;
    frame.primaryAxisAlignItems = 'CENTER';
    frame.resize(280, num(props.min_height, 48));
    frame.strokes = [{ type: 'SOLID', color: { r: 0.8, g: 0.8, b: 0.8 } }];
    frame.strokeWeight = 1;
    frame.cornerRadius = 10;
    parent.appendChild(frame);
    const ph = figma.createText();
    ph.fontName = { family: 'Inter', style: 'Regular' };
    ph.fontSize = fontSizeFor('body');
    ph.characters = props.placeholder || 'Placeholder';
    ph.fills = [{ type: 'SOLID', color: { r: 0.6, g: 0.6, b: 0.6 } }];
    frame.appendChild(ph);
    return;
  }

  if (type === 'TabBar') {
    const layout = node.layout || {};
    const frame = newFrame(type, node.id);
    const bg = hexToFigmaColor(tokenValue((node.style || {}).background)) ||
      hexToFigmaColor(tokenValue('{color.surface}')) || { r: 1, g: 1, b: 1 };
    frame.fills = [{ type: 'SOLID', color: bg }];
    frame.layoutMode = 'HORIZONTAL';
    frame.primaryAxisSizingMode = 'FIXED';
    frame.counterAxisSizingMode = 'FIXED';
    frame.primaryAxisAlignItems = 'CENTER';
    frame.counterAxisAlignItems = 'CENTER';
    frame.itemSpacing = num(tokenValue(layout.gap), 8);
    const padH = num(tokenValue(((layout.padding) || {}).horizontal), 24);
    frame.paddingLeft = frame.paddingRight = padH;
    frame.paddingTop = 8;
    frame.paddingBottom = 20; // spazio home indicator
    frame.strokes = [{ type: 'SOLID', color: { r: 0.85, g: 0.85, b: 0.87 } }];
    frame.strokeWeight = 1;
    frame.strokeAlign = 'INSIDE';
    frame.resize(340, num(props.min_height, 80));
    parent.appendChild(frame);
    // fedelta': se l'istanza TabBar sorgente esiste ancora, clona i suoi tab
    // (icone vere); altrimenti celle ricostruite con icona placeholder
    const srcBar = (node.meta || {}).figma_node_id ? figma.getNodeById((node.meta || {}).figma_node_id) : null;
    const srcTabs = srcBar && 'children' in srcBar ? tabNodesOf(srcBar) : [];
    if (srcTabs.length > 0 && srcTabs.length === (props.tabs || []).length) {
      for (const st of srcTabs) {
        const copy = st.clone();
        frame.appendChild(copy);
        try { copy.layoutGrow = 1; } catch (e) { /* istanza rigida: ok */ }
      }
      return;
    }
    for (const tab of props.tabs || []) {
      const cell = figma.createFrame();
      cell.name = 'Tab: ' + (tab.label || tab.id || 'tab');
      cell.fills = [];
      cell.layoutMode = 'VERTICAL';
      cell.primaryAxisAlignItems = 'CENTER';
      cell.counterAxisAlignItems = 'CENTER';
      cell.itemSpacing = 4;
      cell.layoutGrow = 1; // i tab si spartiscono la larghezza
      frame.appendChild(cell);
      const icon = figma.createFrame();
      icon.name = 'icon: ' + (tab.icon || '');
      icon.resize(24, 24);
      icon.cornerRadius = 6;
      icon.fills = [{ type: 'SOLID', color: { r: 0.55, g: 0.57, b: 0.62 } }];
      cell.appendChild(icon);
      const label = figma.createText();
      label.fontName = { family: 'Inter', style: 'Medium' };
      label.fontSize = fontSizeFor('caption');
      label.characters = tab.label || '';
      label.fills = [{ type: 'SOLID', color: { r: 0.35, g: 0.37, b: 0.42 } }];
      cell.appendChild(label);
    }
    return;
  }

  if (type === 'Image' || type === 'Icon') {
    const frame = newFrame(type, node.id);
    const size = type === 'Icon' ? 24 : 120;
    frame.resize(size, size);
    frame.fills = [{ type: 'SOLID', color: { r: 0.9, g: 0.9, b: 0.92 } }];
    frame.cornerRadius = type === 'Icon' ? 6 : 12;
    parent.appendChild(frame);
    return;
  }

  // contenitori: Screen / Stack / Card / List / AppHeader / EmptyState / ListRow / ...
  // (piu' le ellissi: meta.shape === 'ellipse' -> createEllipse)
  const isEllipse = node.meta && node.meta.shape === 'ellipse';
  const frame = isEllipse ? figma.createEllipse() : newFrame(type, node.id);
  if (isEllipse) frame.name = type + ': ' + (node.id || '');
  applyContainerStyle(frame, node, isRoot, isEllipse);
  if (type === 'ListRow') {
    frame.layoutMode = 'HORIZONTAL';
    frame.counterAxisSizingMode = 'FIXED';
    frame.resize(340, num(props.min_height, 48));
    frame.primaryAxisAlignItems = 'CENTER';
  }
  if (type === 'EmptyState') {
    frame.primaryAxisAlignItems = 'CENTER';
    frame.counterAxisAlignItems = 'CENTER';
  }
  parent.appendChild(frame);

  if (type === 'EmptyState' && props.message && !(node.children || []).length) {
    const t = figma.createText();
    t.fontName = { family: 'Inter', style: 'Regular' };
    t.fontSize = fontSizeFor('body');
    t.characters = props.message;
    frame.appendChild(t);
  }

  for (const child of node.children || []) {
    if (isEllipse) break; // le ellissi non contengono figli (né in Figma né qui)
    await renderNode(child, frame, false);
  }
}

// ------------------------------------------------------ render fedele (D32)
// Se il JSON porta la geometria reale (layout.frame, presente negli export
// plugin da D32), il render usa posizionamento assoluto invece di auto-layout
// e clona immagini/icone dal nodo Figma sorgente (stesso file, stesso id).

function hasGeometry(screen) {
  const f = screen && screen.root && screen.root.layout && screen.root.layout.frame;
  return !!(f && f.w > 0 && f.h > 0);
}

async function renderNodeFaithful(node, parent) {
  const f = (node.layout || {}).frame;
  const style = node.style || {};
  const props = node.props || {};
  const meta = node.meta || {};

  if (node.type === 'Text') {
    const t = figma.createText();
    t.fontName = await textFont(props.fontFamily, props.fontStyle, props.variant);
    t.fontSize = num(props.fontSize, fontSizeFor(props.variant));
    t.characters = props.content || '';
    try {
      if (props.align) t.textAlignHorizontal = props.align;
      if (props.valign) t.textAlignVertical = props.valign;
      if (props.lineHeight) t.lineHeight = props.lineHeight;
      if (props.letterSpacing) t.letterSpacing = props.letterSpacing;
      if (props.textCase) t.textCase = props.textCase;
      if (props.textDecoration) t.textDecoration = props.textDecoration;
    } catch (e) { /* valore non valido per questo font: ignora */ }
    try { t.textAutoResize = 'WIDTH_AND_HEIGHT'; } catch (e) { /* versioni vecchie */ }
    const color = hexToFigmaColor(tokenValue(style.color));
    if (color) t.fills = [{ type: 'SOLID', color: color }];
    t.name = 'Text: ' + (node.id || '');
    t.setPluginData('dc_id', node.id || '');
    parent.appendChild(t);
    if (f) { t.x = f.x; t.y = f.y; }
    // se il frame storico e' piu' stretto del testo allungato, allarga:
    // evita 'Add $15 to wal' troncato quando il co-fix manca nei vecchi JSON.
    try {
      if (f && t.width > f.w) { t.resize(Math.ceil(t.width), Math.max(t.height, 1)); }
    } catch (e) { /* ok */ }
    applyVisualStyle(t, node); // stili visivi (v. nota sui container)
    return;
  }

  // Immagini e icone: cloniamo il nodo sorgente (massima fedelta', zero byte
  // nel JSON). Funziona solo se il frame originale esiste ancora nel file.
  if ((node.type === 'Image' || node.type === 'Icon') && meta.figma_node_id) {
    const src = figma.getNodeById(meta.figma_node_id);
    if (src) {
      const copy = src.clone();
      parent.appendChild(copy);
      copy.name = node.type + ': ' + (node.id || '');
      try { copy.setPluginData('dc_id', node.id || ''); } catch (e) { /* read-only */ }
      if (f) {
        copy.x = f.x; copy.y = f.y;
        try { copy.resize(Math.max(f.w, 1), Math.max(f.h, 1)); } catch (e) { /* vector/locked */ }
      }
      return;
    }
    // sorgente non piu' disponibile: placeholder
  }

  // Tipi complessi senza figli nel JSON (Button, TabBar, TextField…):
  // riusa il builder auto-layout, poi riposiziona/ridimensiona in assoluto.
  const kids = node.children || [];
  if (!kids.length && node.type !== 'Screen' && node.type !== 'Stack' &&
      node.type !== 'Card' && node.type !== 'List') {
    await renderNode(node, parent, false);
    const created = parent.children[parent.children.length - 1];
    if (created && f) {
      created.x = f.x; created.y = f.y;
      if (created.type !== 'TEXT') {
        try { created.resize(Math.max(f.w, 1), Math.max(f.h, 1)); } catch (e) { /* ok */ }
      }
    }
    return;
  }

  // Contenitori: frame assoluto, niente auto-layout. Niente clipsContent:
  // nell'originale i contenuti possono legittimamente debordare dai gruppi;
  // il clip lo fa solo il root (in renderScreen).
  // Le ellissi tornano ellissi (createEllipse): prima diventavano rettangoli.
  const isEllipse = meta.shape === 'ellipse';
  const frame = isEllipse ? figma.createEllipse() : newFrame(node.type, node.id);
  if (isEllipse) {
    frame.name = (node.type || 'Stack') + ': ' + (node.id || '');
    try { frame.setPluginData('dc_id', node.id || ''); } catch (e) { /* read-only */ }
  } else {
    frame.layoutMode = 'NONE';
  }
  const bg = hexToFigmaColor(tokenValue(style.background));
  if (bg) {
    // Opacita' del fill (es. #D9D9D9 al 20% del back in vetro): senza,
    // il render ridisegnava il colore pieno e il cerchio usciva grigio solido.
    const paint = { type: 'SOLID', color: bg };
    if (style.backgroundOpacity != null) {
      paint.opacity = Math.max(0, Math.min(1, num(style.backgroundOpacity, 1)));
    }
    frame.fills = [paint];
  } else {
    frame.fills = [];
  }
  if (!isEllipse && style.radius != null) frame.cornerRadius = num(tokenValue(style.radius), 0);
  if (f) frame.resize(Math.max(f.w, 1), Math.max(f.h, 1));
  parent.appendChild(frame);
  if (f) { frame.x = f.x; frame.y = f.y; }
  // Stili visivi DOPO geometria (solo ordine di scrittura: x/y e rotation
  // toccano parti diverse della matrice, quindi l'ordine e' indifferente).
  // La correttezza per i nodi ruotati sta nei VALORI registrati da withGeo
  // (traslazione, non bbox visivo), non qui.
  applyVisualStyle(frame, node);
  if (!isEllipse) {
    for (const child of kids) {
      await renderNodeFaithful(child, frame);
    }
  }
}

async function renderScreen(screen) {
  await figma.loadFontAsync({ family: 'Inter', style: 'Regular' });
  await figma.loadFontAsync({ family: 'Inter', style: 'Medium' });
  await figma.loadFontAsync({ family: 'Inter', style: 'Bold' });

  // Tema per la risoluzione dei token {light, dark} (punto 1):
  // senza, i token tematizzati restano oggetti e i fill spariscono.
  RENDER_THEME = (screen.meta && screen.meta.theme) || 'light';

  let frame;
  if (hasGeometry(screen)) {
    // modalita' fedele: root con geometria reale, figli in assoluto
    const rf = screen.root.layout.frame;
    const root = newFrame(screen.root.type || 'Screen', screen.root.id);
    root.layoutMode = 'NONE';
    const bg = hexToFigmaColor(tokenValue((screen.root.style || {}).background));
    root.fills = bg ? [{ type: 'SOLID', color: bg }] : [];
    root.resize(Math.max(rf.w, 1), Math.max(rf.h, 1));
    root.clipsContent = true;
    figma.currentPage.appendChild(root);
    for (const child of screen.root.children || []) {
      await renderNodeFaithful(child, root);
    }
    frame = root;
  } else {
    const holder = figma.createFrame();
    holder.name = 'holder';
    figma.currentPage.appendChild(holder);
    await renderNode(screen.root, holder, true);
    frame = holder.children[0] || holder;
    if (frame !== holder) {
      figma.currentPage.appendChild(frame); // sgancia dal holder
      holder.remove();
    }
  }
  const center = figma.viewport.center;
  frame.x = Math.round(center.x - frame.width / 2);
  frame.y = Math.round(center.y - frame.height / 2);
  frame.name = 'Screen: ' + (screen.meta.name || screen.meta.id);
  figma.currentPage.selection = [frame];
  figma.viewport.scrollAndZoomIntoView([frame]);
  return frame;
}

// ---------------------------------------------------------------- real-time
let watching = false;
let watchedNodeId = null;
let debounceTimer = null;

function currentTargetNode() {
  const d = describeSelection();
  if (d && d.valid) return figma.getNodeById(d.id);
  if (watchedNodeId) {
    const node = figma.getNodeById(watchedNodeId);
    if (node) return node;
  }
  return null;
}

async function exportAndAskValidation() {
  const node = currentTargetNode();
  if (!node) return;
  watchedNodeId = node.id;
  const screen = exportFrame(node);
  const assets = await collectAssets(screen.meta.id);
  figma.ui.postMessage({ type: 'screen-exported', screen: screen, map: exportMap, assets: assets });
}

// Propose: stesso export + PNG vista reale per la vision del padre.
// Il messaggio 'propose-exported' porta screen + preview_base64 + assets.
async function exportForPropose() {
  const node = currentTargetNode();
  if (!node) {
    const d = describeSelection();
    figma.ui.postMessage({ type: 'error', message: d
      ? 'Hai selezionato "' + d.name + '" (' + d.kind + '): non e\' un frame. Seleziona il frame della schermata.'
      : 'Seleziona un frame sul canvas (la schermata).' });
    return;
  }
  watchedNodeId = node.id;
  const screen = exportFrame(node);
  const assets = await collectAssets(screen.meta.id);
  const preview = await exportPreview(node);
  figma.ui.postMessage({ type: 'propose-exported', screen: screen, map: exportMap,
                         assets: assets, preview_base64: preview });
}

figma.on('documentchange', () => {
  if (!watching) return;
  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(exportAndAskValidation, 900);
});

// D43: la selezione viene SEMPRE comunicata alla UI (anche senza watch) —
// il plugin deve dire cosa vede, non lasciare l'utente nel dubbio.
const EXPORTABLE = ['FRAME', 'COMPONENT', 'INSTANCE', 'COMPONENT_SET'];

function describeSelection() {
  const sel = figma.currentPage.selection;
  if (!sel.length) return null;
  const n = sel[0];
  return { id: n.id, name: n.name, kind: n.type, valid: EXPORTABLE.includes(n.type) };
}

figma.on('selectionchange', () => {
  const d = describeSelection();
  figma.ui.postMessage({ type: 'selection-changed', node: d });
  if (watching && d && d.valid) exportAndAskValidation();
});

// ---------------------------------------------------------------- messaggi UI
figma.showUI(__html__, { width: 360, height: 520, title: 'DesignChecker' });

figma.ui.onmessage = async (msg) => {
  if (msg.type === 'init-data') {
    CATALOG = msg.catalog || null;
    HEX_TO_TOKEN = (msg.tokens && msg.tokens.hex_to_token) || {};
    TOKEN_FLAT = (msg.tokens && msg.tokens.flat) || {};
  }
  if (msg.type === 'ui-ready') {
    // all'apertura la UI chiede lo stato della selezione corrente (D43)
    figma.ui.postMessage({ type: 'selection-changed', node: describeSelection() });
  }
  if (msg.type === 'export-selection') {
    const node = currentTargetNode();
    if (!node) {
      const d = describeSelection();
      figma.ui.postMessage({ type: 'error', message: d
        ? 'Hai selezionato "' + d.name + '" (' + d.kind + '): non e\' un frame. Seleziona il frame della schermata.'
        : 'Seleziona un frame sul canvas (la schermata).' });
      return;
    }
    watchedNodeId = node.id;
    const screen = exportFrame(node);
    const assets = await collectAssets(screen.meta.id);
    const preview = await exportPreview(node);
    figma.ui.postMessage({ type: 'screen-exported', screen: screen, map: exportMap, assets: assets,
                           preview_base64: preview,
                           assets_debug: { found: pendingAssets.length, sent: assets.length } });
  }
  if (msg.type === 'export-propose') {
    await exportForPropose();
    return;
  }
  if (msg.type === 'export-describe') {
    // dck describe: basta il PNG del frame (niente screen JSON, niente asset).
    const node = currentTargetNode();
    if (!node) {
      const d = describeSelection();
      figma.ui.postMessage({ type: 'error', message: d
        ? 'Hai selezionato "' + d.name + '" (' + d.kind + '): non e\' un frame. Seleziona il frame della schermata.'
        : 'Seleziona un frame sul canvas (la schermata).' });
      return;
    }
    const preview = await exportPreview(node);
    if (!preview) {
      figma.ui.postMessage({ type: 'error', message: 'Export PNG non riuscito: riprova.' });
      return;
    }
    figma.ui.postMessage({ type: 'describe-exported', preview_base64: preview,
                           frameName: node.name });
    return;
  }
  if (msg.type === 'export-describe-json') {
    // Describe+JSON: screen JSON + PNG (niente asset: alla scheda bastano
    // struttura e anteprima). Condivide l'export fedele del propose.
    const node = currentTargetNode();
    if (!node) {
      const d = describeSelection();
      figma.ui.postMessage({ type: 'error', message: d
        ? 'Hai selezionato "' + d.name + '" (' + d.kind + '): non e\' un frame. Seleziona il frame della schermata.'
        : 'Seleziona un frame sul canvas (la schermata).' });
      return;
    }
    const screen = exportFrame(node);
    const preview = await exportPreview(node);
    if (!preview) {
      figma.ui.postMessage({ type: 'error', message: 'Export PNG non riuscito: riprova.' });
      return;
    }
    figma.ui.postMessage({ type: 'describe-json-exported', screen: screen,
                           preview_base64: preview, frameName: node.name });
    return;
  }
  if (msg.type === 'annotate') {
    exportMap = msg.map || exportMap;
    await annotate(msg.findings || []);
  }
  if (msg.type === 'clear-annotations') clearAnnotations();
  if (msg.type === 'watch-start') { watching = true; exportAndAskValidation(); }
  if (msg.type === 'watch-stop') { watching = false; clearAnnotations(); }
  if (msg.type === 'render') {
    try {
      const frame = await renderScreen(msg.screen);
      figma.ui.postMessage({ type: 'rendered', name: frame.name });
    } catch (e) {
      figma.ui.postMessage({ type: 'error', message: 'Render fallito: ' + (e.message || e) });
    }
  }
  if (msg.type === 'render-proposal') {
    // Proposta AI: nuovo frame accanto all'originale, mai sovrascrittura.
    try {
      const frame = await renderScreen(msg.screen);
      frame.name = '[AI] ' + frame.name;
      frame.x = frame.x + frame.width + 120; // a destra dell'originale
      figma.currentPage.selection = [frame];
      figma.viewport.scrollAndZoomIntoView([frame]);
      figma.ui.postMessage({ type: 'rendered', name: frame.name });
    } catch (e) {
      figma.ui.postMessage({ type: 'error', message: 'Render proposta fallito: ' + (e.message || e) });
    }
  }
  if (msg.type === 'close') figma.closePlugin();
};
