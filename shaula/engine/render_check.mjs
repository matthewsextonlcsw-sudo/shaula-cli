/* Headless render proof for a filled SPA — fixture-agnostic.

   app.js renders all content client-side via route template functions and a
   `posts` array, then auto-runs navigate() on load using `document`,
   `window`, `location`, and `history`. We provide just enough of a DOM/host
   shim to let app.js execute, invoke every route, and assert the produced HTML
   is real, filled, and free of {{tokens}} / AI-GENERATE markers.

   THE REFRAME: the deterministic (no-LLM) engine produces a DIFFERENT honest
   output than any one golden fixture (generic method steps, generic posts, etc).
   So this proof checks STRUCTURE + that the *practice's own data* landed in the
   render — it never hard-codes a specific method acronym or post title. Expected
   values are read from the supplied practice.json, so the same proof passes for
   cedar-sage, the couples fixture, or any future practice.

   Pure Node, no packages.

   USAGE
     node render_check.mjs [--out <dir>] [--practice <practice.json>]
   Defaults: --out ../sites/cedar-sage  --practice ../fixtures/cedar-sage/practice.json
*/

import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';

// --- argv ------------------------------------------------------------------
function argOf(flag, fallback) {
  const i = process.argv.indexOf(flag);
  return i !== -1 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}
const HERE = import.meta.dirname;
const OUT = path.resolve(argOf('--out', path.join(HERE, '..', 'sites', 'cedar-sage')));
const PRACTICE = path.resolve(
  argOf('--practice', path.join(HERE, '..', 'fixtures', 'cedar-sage', 'practice.json')),
);

const appSrc = readFileSync(path.join(OUT, 'app.js'), 'utf8');
const practice = JSON.parse(readFileSync(PRACTICE, 'utf8'));

// --- minimal DOM/host shim -------------------------------------------------
function makeEl(id = '') {
  return {
    id, hidden: false, innerHTML: '', className: '', dataset: {},
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    style: {},
    addEventListener() {}, removeEventListener() {},
    querySelectorAll() { return []; }, querySelector() { return null; },
    appendChild() {}, removeChild() {}, replaceWith() {}, remove() {},
    setAttribute() {}, getAttribute() { return null; }, closest() { return null; },
    parentElement: null,
  };
}
const routeEls = {};
const ids = ['home','about','approach','method','journey','who','fees','writing','contact','privacy'];
ids.forEach(id => { routeEls['route-' + id] = makeEl('route-' + id); });

const documentShim = {
  getElementById: id => routeEls[id] || null,
  querySelectorAll: () => [],
  querySelector: () => null,
  createElement: () => makeEl(),
  addEventListener() {},
  body: makeEl(),
};
const windowShim = {
  scrollTo() {}, IntersectionObserver: undefined,
  addEventListener() {}, setTimeout: (fn) => { try { fn(); } catch (_) {} return 0; },
};
const context = {
  document: documentShim,
  window: windowShim,
  location: { hash: '', href: '' },
  history: { replaceState() {} },
  setTimeout: (fn) => { try { fn(); } catch (_) {} return 0; },
  clearTimeout() {}, fetch: async () => { throw new Error('no fetch in shim'); },
  URL: { createObjectURL: () => 'blob:stub' },
  console,
};
context.globalThis = context;
context.self = context;

vm.createContext(context);
vm.runInContext(appSrc, context, { filename: 'app.js' });

// app.js defines `routes` and `posts` as top-level const/let — pull them out.
const routes = vm.runInContext('routes', context);
const posts = vm.runInContext('posts', context);

const TOKEN_RE = /\{\{[a-zA-Z0-9_]+\}\}/g;
const results = {};
let totalTokenLeaks = 0;
let totalMarkers = 0;
let totalChars = 0;

for (const name of Object.keys(routes)) {
  let html = '';
  let err = null;
  try { html = routes[name](); } catch (e) { err = e.message; }
  const tokenLeaks = (html.match(TOKEN_RE) || []);
  const markers = (html.match(/AI-GENERATE/g) || []).length;
  totalTokenLeaks += tokenLeaks.length;
  totalMarkers += markers;
  totalChars += html.length;
  results[name] = {
    ok: !err && html.length > 200,
    chars: html.length,
    tokenLeaks: tokenLeaks.length,
    markers,
    error: err,
    sampleLeaks: tokenLeaks.slice(0, 3),
  };
}

// --- structural spot-checks, driven by THIS practice's data ----------------
// Helper: a rendered string may HTML-escape `& < >` (values land in HTML text
// via `${...}`), so accept either the raw value or its escaped form.
function esc(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
function hasVal(html, val) {
  if (!val) return true; // absent token in this fixture → not asserted
  return html.includes(val) || html.includes(esc(val));
}

const aboutHTML = routes.about();
const feesHTML = routes.fees();
const methodHTML = routes.method();
const writingHTML = routes.writing();
const homeHTML = routes.home();
// Identity data legitimately lives wherever the template's design puts it (the
// hero is tagline-driven and may carry no business name), so assert it appears
// across the WHOLE rendered site, not in one specific route.
const allHTML = Object.keys(routes).map(n => { try { return routes[n](); } catch (_) { return ''; } }).join('\n');

// Expected values pulled from practice.json (fixture-agnostic).
const ownerName = practice.owner_name || '';
const businessName = practice.business_name || '';
const credentialFull = practice.credential_full || '';
const feeAmount = practice.session_fee_amount || (practice.session_fee || '').replace(/[^0-9]/g, '');

// The honest-posts invariant: the deterministic floor ships ZERO essays (it
// never fabricates dates/reading times/links); the publisher prepends real,
// linked entries as approved essays go live. So: every present post must
// carry a working href, and an empty array must render the honest
// "first essays" state — never anchors to pages that don't exist.
const EMPTY_STATE_MARKER = 'The first essays are being written';
const spot = {
  site_has_owner: hasVal(allHTML, ownerName),
  site_has_business: hasVal(allHTML, businessName),
  about_has_credential_full: hasVal(aboutHTML, credentialFull),
  fees_has_amount: hasVal(feesHTML, feeAmount),
  // Structural invariants the deterministic engine guarantees for every fixture:
  method_step_rows: (methodHTML.match(/method-row/g) || []).length, // expect 6
  posts_count: posts.length,                                        // 0 at the floor
  posts_all_linked: posts.every(p => p.href),                       // no dead cards, ever
  writing_honest_when_empty:
    posts.length > 0 || (writingHTML.includes(EMPTY_STATE_MARKER) && homeHTML.includes(EMPTY_STATE_MARKER)),
};

// Which spot-checks are hard requirements (must be true/satisfy the bound).
const spotFailures = [];
if (!spot.site_has_owner) spotFailures.push('owner_name missing from rendered site');
if (!spot.site_has_business) spotFailures.push('business_name missing from rendered site');
if (!spot.about_has_credential_full) spotFailures.push('credential_full missing from about route');
if (!spot.fees_has_amount) spotFailures.push('session fee amount missing from fees route');
if (spot.method_step_rows !== 6) spotFailures.push(`method-row count = ${spot.method_step_rows}, expected 6`);
if (!spot.posts_all_linked) spotFailures.push('a post card has no real page (href missing) — fabricated listing');
if (!spot.writing_honest_when_empty) spotFailures.push('zero posts but the honest empty state is missing from home/writing');

console.log(JSON.stringify({
  out: OUT,
  practice: PRACTICE,
  routesRendered: Object.keys(results).length,
  totalRenderedChars: totalChars,
  totalTokenLeaks,
  totalMarkers,
  perRoute: results,
  spotChecks: spot,
  spotFailures,
}, null, 2));

if (totalTokenLeaks > 0 || totalMarkers > 0) {
  console.error('\nFAIL: token leaks or markers found in rendered output.');
  process.exit(1);
}
const anyBad = Object.values(results).some(r => !r.ok);
if (anyBad) { console.error('\nFAIL: a route failed to render.'); process.exit(1); }
if (spotFailures.length) {
  console.error('\nFAIL: structural spot-checks failed:\n  - ' + spotFailures.join('\n  - '));
  process.exit(1);
}
console.log('\nPASS: all routes render real, filled HTML; 0 token leaks, 0 markers; '
  + 'practice data present; 6 method rows; ' + posts.length + ' posts (all real-linked'
  + (posts.length === 0 ? '; honest empty state shown' : '') + ').');
