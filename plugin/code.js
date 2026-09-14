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

// Sfondo nodo: [hex, visualBg]. Gradiente -> media pesata degli stop
// (approssimazione dichiarata in meta.visual_bg, D30); immagine -> [null, 'image'].
function fillHex(fills) {
  if (!Array.isArray(fills)) return [null, null];
  for (const fill of fills) {
    if (fill.visible === false) continue;
    if (fill.type === 'SOLID') return [rgbHex(fill.color), null];
    if (fill.type && fill.type.startsWith('GRADIENT')) {
      const stops = fill.gradientStops || [];
      if (stops.length) {
        const tot = stops.reduce((s, st) => s + (st.color.a == null ? 1 : st.color.a), 0) || 1;
        const avg = { r: 0, g: 0, b: 0 };
        for (const st of stops) {
          const a = st.color.a == null ? 1 : st.color.a;
          avg.r += st.color.r * a; avg.g += st.color.g * a; avg.b += st.color.b * a;
        }
        return [rgbHex({ r: avg.r / tot, g: avg.g / tot, b: avg.b / tot }), 'gradient'];
      }
    }
    if (fill.type === 'IMAGE') return [null, 'image'];
  }
  return [null, null];
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

function withGeo(out, node, bounds, parentBox) {
  // geometria reale relativa al genitore + id Figma (per clonare immagini/
  // icone dal nodo sorgente al momento del render, se esiste ancora nel file)
  if (bounds && bounds.width != null) {
    out.layout = out.layout || {};
    out.layout.frame = {
      x: Math.round(bounds.x - (parentBox ? parentBox.x : bounds.x)),
      y: Math.round(bounds.y - (parentBox ? parentBox.y : bounds.y)),
      w: Math.round(bounds.width),
      h: Math.round(bounds.height),
    };
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
      id: kebab(name), type: 'Icon',
      props: { name: norm(name) || 'icon' },
      layout: {}, style: {},
      meta: { source: 'figma-plugin', confidence: 0.9 },
    }, node, bounds, parentBox);
    pendingAssets.push({ node: node, ref: out });
    return out;
  }

  if (node.type === 'TEXT') {
    const out = {
      id: kebab(name) || 'text', type: 'Text',
      props: { content: node.characters || '', variant: textVariant(Number(node.fontSize) || 16) },
      layout: { sizing: { w: 'hug', h: 'hug' } },
      style: {},
      meta: { source: 'figma-plugin', confidence: 1.0 },
    };
    const color = solidHex(node.fills);
    if (color) out.style.color = tokenOrHex(color);
    return withGeo(out, node, bounds, parentBox);
  }

  if (!['FRAME', 'INSTANCE', 'GROUP', 'RECTANGLE', 'COMPONENT', 'COMPONENT_SET'].includes(node.type)) {
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
    id: kebab(name) || 'node',
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

  const [bg, visualBg] = fillHex(node.fills);
  if (bg && (traits.includes('container') || traits.includes('surface') || topLevel)) {
    out.style.background = tokenOrHex(bg);
  }
  if (visualBg) out.meta.visual_bg = visualBg;

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
    if (children.length && ['Screen', 'Stack', 'Card', 'List'].includes(dcType)) {
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

function exportFrame(node) {
  exportMap = {};
  pendingAssets = [];
  const root = convertNode(node, true, node.absoluteBoundingBox);
  return {
    schema_version: '0.1.0',
    meta: {
      id: kebab(node.name), name: node.name + ' (import plugin Figma)',
      route: '/' + kebab(node.name), status: 'draft',
      source: { kind: 'figma-plugin', confidence: root.meta.confidence },
    },
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
  // "{color.brand.primary}" -> valore; altrimenti ritorna il valore cosi' com'e'
  if (typeof ref === 'string' && ref.startsWith('{') && ref.endsWith('}')) {
    const path = ref.slice(1, -1);
    if (path in TOKEN_FLAT) return TOKEN_FLAT[path];
    return null;
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

function newFrame(dcType, id) {
  const frame = figma.createFrame();
  frame.name = dcType + ': ' + id;
  frame.fills = [];
  return frame;
}

function applyContainerStyle(frame, node, isRoot) {
  const layout = node.layout || {};
  const style = node.style || {};
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
  if (bg) frame.fills = [{ type: 'SOLID', color: bg }];
  const radius = num(tokenValue(style.radius), 0);
  if (radius) frame.cornerRadius = radius;
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
    if (isFab) { frame.primaryAxisSizingMode = 'FIXED'; frame.counterAxisSizingMode = 'FIXED'; frame.resize(56, 56); }
    else {
      frame.primaryAxisSizingMode = 'AUTO'; frame.counterAxisSizingMode = 'FIXED';
      frame.paddingLeft = frame.paddingRight = 16;
      frame.resize(120, num(props.min_height, 48));
      frame.primaryAxisSizingMode = 'AUTO';
    }
    parent.appendChild(frame);
    const label = figma.createText();
    label.fontName = { family: 'Inter', style: 'Medium' };
    label.fontSize = fontSizeFor('body');
    label.characters = props.label || (isFab ? '+' : 'Button');
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
  const frame = newFrame(type, node.id);
  applyContainerStyle(frame, node, isRoot);
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
    t.fontName = { family: 'Inter', style: props.variant === 'title' || props.variant === 'heading' ? 'Bold' : 'Regular' };
    t.fontSize = fontSizeFor(props.variant);
    t.characters = props.content || '';
    const color = hexToFigmaColor(tokenValue(style.color));
    if (color) t.fills = [{ type: 'SOLID', color: color }];
    t.name = 'Text: ' + (node.id || '');
    t.setPluginData('dc_id', node.id || '');
    parent.appendChild(t);
    if (f) { t.x = f.x; t.y = f.y; }
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
  const frame = newFrame(node.type, node.id);
  frame.layoutMode = 'NONE';
  const bg = hexToFigmaColor(tokenValue(style.background));
  frame.fills = bg ? [{ type: 'SOLID', color: bg }] : [];
  if (style.radius != null) frame.cornerRadius = num(tokenValue(style.radius), 0);
  if (f) frame.resize(Math.max(f.w, 1), Math.max(f.h, 1));
  parent.appendChild(frame);
  if (f) { frame.x = f.x; frame.y = f.y; }
  for (const child of kids) {
    await renderNodeFaithful(child, frame);
  }
}

async function renderScreen(screen) {
  await figma.loadFontAsync({ family: 'Inter', style: 'Regular' });
  await figma.loadFontAsync({ family: 'Inter', style: 'Medium' });
  await figma.loadFontAsync({ family: 'Inter', style: 'Bold' });

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
  const sel = figma.currentPage.selection;
  if (sel.length && ['FRAME', 'COMPONENT', 'INSTANCE', 'COMPONENT_SET'].includes(sel[0].type)) return sel[0];
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

figma.on('documentchange', () => {
  if (!watching) return;
  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(exportAndAskValidation, 900);
});

figma.on('selectionchange', () => {
  if (watching) exportAndAskValidation();
});

// ---------------------------------------------------------------- messaggi UI
figma.showUI(__html__, { width: 360, height: 520, title: 'DesignChecker' });

figma.ui.onmessage = async (msg) => {
  if (msg.type === 'init-data') {
    CATALOG = msg.catalog || null;
    HEX_TO_TOKEN = (msg.tokens && msg.tokens.hex_to_token) || {};
    TOKEN_FLAT = (msg.tokens && msg.tokens.flat) || {};
  }
  if (msg.type === 'export-selection') {
    const node = currentTargetNode();
    if (!node) {
      figma.ui.postMessage({ type: 'error', message: 'Seleziona un frame sul canvas (la schermata).' });
      return;
    }
    watchedNodeId = node.id;
    const screen = exportFrame(node);
    const assets = await collectAssets(screen.meta.id);
    figma.ui.postMessage({ type: 'screen-exported', screen: screen, map: exportMap, assets: assets,
                           assets_debug: { found: pendingAssets.length, sent: assets.length } });
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
  if (msg.type === 'close') figma.closePlugin();
};
