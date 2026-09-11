#!/usr/bin/env node
// tsx2json.cjs — parser statico TSX -> JSON semplificato per DesignChecker (D23).
// NON esegue il codice: legge solo la struttura (AST via @babel/parser).
// Uso: node tsx2json.cjs <file.tsx>  ->  JSON su stdout
// Output: { file, styles: {nome: {prop: value}}, tree: <elemento> }
// value: {kind:'number'|'string'|'bool', value} | {kind:'ref', path} | {kind:'expr'}
// elemento: { tag, props: {nome: value|action|style_ref}, text, children: [...] }
'use strict';

const fs = require('fs');
const { parse } = require('@babel/parser');

const file = process.argv[2];
if (!file) {
  console.error('uso: node tsx2json.cjs <file.tsx>');
  process.exit(2);
}
const code = fs.readFileSync(file, 'utf8');
const ast = parse(code, {
  sourceType: 'module',
  plugins: ['jsx', 'typescript'],
  errorRecovery: true,
});

// ------------------------------------------------------------- generic walk
function* walk(node) {
  if (!node || typeof node !== 'object') return;
  yield node;
  for (const key of Object.keys(node)) {
    const child = node[key];
    if (Array.isArray(child)) {
      for (const c of child) if (c && typeof c.type === 'string') yield* walk(c);
    } else if (child && typeof child.type === 'string') {
      yield* walk(child);
    }
  }
}

// theme.colors.brand.primary -> "theme.colors.brand.primary"; styles['x'] -> "styles.x"
function memberPath(node) {
  const parts = [];
  let cur = node;
  while (cur && cur.type === 'MemberExpression') {
    if (cur.property.type === 'Identifier' && !cur.computed) parts.unshift(cur.property.name);
    else if (cur.property.type === 'StringLiteral') parts.unshift(cur.property.value);
    else if (cur.property.type === 'NumericLiteral') parts.unshift(String(cur.property.value));
    else return null;
    cur = cur.object;
  }
  if (cur && cur.type === 'Identifier') parts.unshift(cur.name);
  else return null;
  return parts.join('.');
}

// ------------------------------------------------------------- valori stile
function styleValue(node) {
  if (!node) return { kind: 'expr' };
  switch (node.type) {
    case 'NumericLiteral':
      return { kind: 'number', value: node.value };
    case 'StringLiteral':
      return { kind: 'string', value: node.value };
    case 'BooleanLiteral':
      return { kind: 'bool', value: node.value };
    case 'UnaryExpression':
      if (node.operator === '-' && node.argument.type === 'NumericLiteral')
        return { kind: 'number', value: -node.argument.value };
      return { kind: 'expr' };
    case 'MemberExpression': {
      const path = memberPath(node);
      return path ? { kind: 'ref', path } : { kind: 'expr' };
    }
    default:
      return { kind: 'expr' };
  }
}

// StyleSheet.create({ ... })
function extractStyles() {
  const styles = {};
  for (const node of walk(ast)) {
    if (node.type !== 'CallExpression') continue;
    const callee = node.callee;
    if (callee.type !== 'MemberExpression') continue;
    const obj = callee.object, prop = callee.property;
    if (!(obj.type === 'Identifier' && obj.name === 'StyleSheet')) continue;
    if (!(prop.type === 'Identifier' && prop.name === 'create')) continue;
    const arg = node.arguments[0];
    if (!arg || arg.type !== 'ObjectExpression') continue;
    for (const entry of arg.properties) {
      if (entry.type !== 'ObjectProperty') continue;
      const name = entry.key.type === 'Identifier' ? entry.key.name : entry.key.value;
      const body = {};
      if (entry.value.type === 'ObjectExpression') {
        for (const p of entry.value.properties) {
          if (p.type !== 'ObjectProperty') continue;
          const key = p.key.type === 'Identifier' ? p.key.name : p.key.value;
          body[key] = styleValue(p.value);
        }
      }
      styles[name] = body;
    }
  }
  return styles;
}

// ------------------------------------------------------------- azioni
// () => router.push('/x') -> {kind:'action', verb:'navigate', target:'/x'}
function actionFrom(fn) {
  let body = fn.body;
  if (body.type === 'BlockStatement') {
    const first = body.body[0];
    body = first && first.type === 'ExpressionStatement' ? first.expression : null;
  }
  if (!body) return { kind: 'action', verb: 'none' };
  if (body.type === 'CallExpression') {
    const callee = body.callee;
    if (callee.type === 'MemberExpression' && callee.property.type === 'Identifier') {
      const verb = callee.property.name;
      const arg0 = body.arguments[0];
      const target = arg0 && arg0.type === 'StringLiteral' ? arg0.value : null;
      if (['push', 'navigate', 'replace'].includes(verb) && target)
        return { kind: 'action', verb: 'navigate', target };
      if (['back', 'dismiss', 'goBack'].includes(verb))
        return { kind: 'action', verb: 'back' };
      return { kind: 'action', verb: 'call', name: verb };
    }
    if (callee.type === 'Identifier')
      return { kind: 'action', verb: 'call', name: callee.name };
  }
  if (body.type === 'Identifier') return { kind: 'action', verb: 'call', name: body.name };
  return { kind: 'action', verb: 'custom' };
}

// ------------------------------------------------------------- JSX
function jsxAttrValue(attr) {
  const v = attr.value;
  if (!v) return { kind: 'bool', value: true };
  if (v.type === 'StringLiteral') return { kind: 'string', value: v.value };
  if (v.type !== 'JSXExpressionContainer') return { kind: 'expr' };
  const e = v.expression;
  switch (e.type) {
    case 'StringLiteral': return { kind: 'string', value: e.value };
    case 'NumericLiteral': return { kind: 'number', value: e.value };
    case 'BooleanLiteral': return { kind: 'bool', value: e.value };
    case 'ArrowFunctionExpression': {
      let body = e.body;
      if (body.type === 'ParenthesizedExpression') body = body.expression;
      // style={({pressed}) => [styles.x, ...]} -> style_ref
      if (attr.name.name === 'style') {
        const refs = [];
        const scan = (n) => {
          if (n && n.type === 'MemberExpression') {
            const p = memberPath(n);
            if (p && p.startsWith('styles.')) refs.push(p.slice(7));
          }
        };
        if (body.type === 'ArrayExpression') body.elements.forEach(scan); else scan(body);
        if (refs.length) return { kind: 'style_ref', name: refs[0], extra: refs.slice(1) };
      }
      // renderItem={({item}) => <Row .../>} -> jsx inline
      if (body.type === 'JSXElement')
        return { kind: 'jsx', element: jsxElement(body) };
      return actionFrom(e);
    }
    case 'CallExpression': return { kind: 'action', ...actionFrom({ body: e }) };
    case 'MemberExpression': {
      const path = memberPath(e);
      if (path && path.startsWith('styles.')) return { kind: 'style_ref', name: path.slice(7) };
      return path ? { kind: 'ref', path } : { kind: 'expr' };
    }
    case 'ArrayExpression': {
      // [styles.x, cond && {...}] -> prendiamo i riferimenti a styles.*
      const refs = [];
      for (const el of e.elements) {
        if (!el) continue;
        if (el.type === 'MemberExpression') {
          const path = memberPath(el);
          if (path && path.startsWith('styles.')) refs.push(path.slice(7));
        }
      }
      return refs.length ? { kind: 'style_ref', name: refs[0], extra: refs.slice(1) } : { kind: 'expr' };
    }
    default:
      if (e.type === 'JSXElement') return { kind: 'jsx', element: jsxElement(e) };
      if (e.type === 'Identifier') return { kind: 'expr', name: e.name };
      return { kind: 'expr' };
  }
}

function jsxElement(node) {
  const nameNode = node.openingElement.name;
  const tag = nameNode.type === 'JSXIdentifier'
    ? nameNode.name
    : nameNode.type === 'JSXMemberExpression'
      ? [nameNode.object.name, nameNode.property.name].join('.')
      : 'Unknown';
  const props = {};
  for (const attr of node.openingElement.attributes) {
    if (attr.type !== 'JSXAttribute') continue;
    props[attr.name.name] = jsxAttrValue(attr);
  }
  let text = '';
  const children = [];
  for (const child of node.children) {
    if (child.type === 'JSXText') {
      const t = child.value.trim();
      if (t) text += (text ? ' ' : '') + t;
    } else if (child.type === 'JSXElement') {
      children.push(jsxElement(child));
    } else if (child.type === 'JSXExpressionContainer') {
      const e = child.expression;
      if (e.type === 'JSXElement') children.push(jsxElement(e));
      else if (e.type === 'StringLiteral') text += (text ? ' ' : '') + e.value;
      else if (e.type !== 'JSXEmptyExpression') text += (text ? ' ' : '') + '{…}';
    }
  }
  return { tag, props, text, children };
}

// il JSX "principale": il return con piu' discendenti (la schermata, non i sotto-componenti)
function countDesc(el) {
  return 1 + el.children.reduce((n, c) => n + countDesc(c), 0);
}

function extractTree() {
  let best = null, bestCount = 0;
  for (const node of walk(ast)) {
    if (node.type !== 'ReturnStatement' || !node.argument) continue;
    let arg = node.argument;
    if (arg.type === 'ParenthesizedExpression') arg = arg.expression;
    if (arg.type !== 'JSXElement' && arg.type !== 'JSXFragment') continue;
    const el = arg.type === 'JSXFragment'
      ? { tag: 'Fragment', props: {}, text: '', children: arg.children.filter(c => c.type === 'JSXElement').map(jsxElement) }
      : jsxElement(arg);
    const n = countDesc(el);
    if (n > bestCount) { best = el; bestCount = n; }
  }
  return best;
}

// import relativi: {ExpenseRow: './components/expense-row', ...}
function extractImports() {
  const imports = {};
  for (const node of (ast.program && ast.program.body) || []) {
    if (node.type !== 'ImportDeclaration') continue;
    const source = node.source && node.source.value;
    if (!source || !source.startsWith('.')) continue;
    for (const spec of node.specifiers || []) {
      if (spec.type === 'ImportSpecifier' || spec.type === 'ImportDefaultSpecifier')
        imports[spec.local.name] = source;
    }
  }
  return imports;
}

const out = { file, imports: extractImports(), styles: extractStyles(), tree: extractTree() };
if (!out.tree) {
  console.error('Nessun JSX principale trovato nel file.');
  process.exit(2);
}
process.stdout.write(JSON.stringify(out));
