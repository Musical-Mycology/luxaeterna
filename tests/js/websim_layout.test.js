/* Behavioral tests for the WebSim page script.
 *
 * The script under test is extracted from PAGE_HTML by
 * tests/backends/test_websim_layout.py and handed here as argv[2], so the
 * served page stays the single source of truth and cannot drift from what is
 * asserted here.
 *
 * The script is driven through its own entry point rather than by poking its
 * internals: the WebSocket stub captures the instance the script constructs,
 * and each test calls that instance's onmessage handler exactly as a real
 * browser would. Nothing here reaches for a private variable, so the tests
 * keep working if the script's internal names change.
 */
const assert = require('node:assert');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(process.argv[2], 'utf8');

const tests = [];
function test(name, fn) { tests.push([name, fn]); }
const round4 = (v) => Math.round(v * 1e4) / 1e4;

function makeCanvas() {
  const ops = [];
  const ctx2d = {
    clearRect: (...a) => ops.push(['clearRect', ...a]),
    fillRect: (...a) => ops.push(['fillRect', ...a]),
    beginPath: () => ops.push(['beginPath']),
    arc: (...a) => ops.push(['arc', ...a]),
    fill: () => ops.push(['fill']),
    createRadialGradient: (...a) => {
      ops.push(['gradient', ...a]);
      return { addColorStop: () => {} };
    },
    set fillStyle(v) { ops.push(['fillStyle', v]); },
    get fillStyle() { return null; },
  };
  return { width: 320, height: 420, getContext: () => ctx2d, ops };
}

/* Run the page script against one capability and (optionally) one frame.
   Returns the canvas stub, the status-line stub and the registered window
   listeners, so a test can also fire a resize.

   Pass cap as null to model a browser that has connected but not yet been
   handed the capability blob. That is a real state the page must survive:
   the resize listener is registered at script load, so a window resized
   mid-handshake fires it before any geometry exists. */
function run(cap, frameBytes, viewport) {
  const canvas = makeCanvas();
  const status = { textContent: '' };
  const listeners = {};
  const sandbox = {
    console, Math, JSON, Uint8Array,
    location: { protocol: 'http:', host: 'localhost:1' },
    document: { getElementById: (id) => (id === 'c' ? canvas : status) },
    window: {
      innerWidth: (viewport && viewport.w) || 800,
      innerHeight: (viewport && viewport.h) || 600,
      addEventListener: (name, fn) => { listeners[name] = fn; },
    },
  };
  sandbox.WebSocket = function () { sandbox.__sock = this; };
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox);

  const sock = sandbox.__sock;
  assert.ok(sock, 'the page script did not construct a WebSocket');
  if (cap) sock.onmessage({ data: JSON.stringify(cap) });  // capability first
  if (frameBytes) sock.onmessage({ data: new Uint8Array(frameBytes) });
  return { canvas, status, listeners, sock };
}

/* Every drawn mark's centre, in draw order. A glow and its dot share a centre,
   so consecutive duplicates collapse to one mark per pixel. */
function marks(canvas) {
  const out = [];
  for (const op of canvas.ops) {
    let p = null;
    if (op[0] === 'arc') p = [op[1], op[2]];
    else if (op[0] === 'fillRect') p = [op[1] + op[3] / 2, op[2] + op[4] / 2];
    if (!p) continue;
    const prev = out[out.length - 1];
    if (prev && prev[0] === p[0] && prev[1] === p[1]) continue;
    out.push(p);
  }
  return out;
}

function shroomCap() {
  return {
    type: 'capability', surface_id: 'ie0', pixel_count: 12, color_order: 'GRB',
    zones: [
      { name: 'ring', start: 0, count: 8 },
      { name: 'stem', start: 8, count: 4 },
      { name: 'primary', start: 0, count: 12 },
    ],
  };
}

/* A Room fixture's shape: named zones, no ring and no stem. Mirrors what
   mm-terrarium's harness/room_surface.py to_fixture_capability() produces. */
function linearCap(n) {
  const third = Math.floor(n / 3);
  return {
    type: 'capability', surface_id: 'room_demo_array', pixel_count: n,
    color_order: 'GRB',
    zones: [
      { name: 'left', start: 0, count: third },
      { name: 'center', start: third, count: third },
      { name: 'right', start: 2 * third, count: n - 2 * third },
      { name: 'primary', start: 0, count: n },
    ],
  };
}

// --- Task 2: the Shroom layout must never change -------------------------

test('shroom ring and stem positions are exactly as declared', () => {
  const { canvas } = run(shroomCap(), new Uint8Array(36));
  const got = marks(canvas).map(([x, y]) => [round4(x), round4(y)]);
  assert.deepStrictEqual(got, [
    [160, 60], [223.6396, 86.3604], [250, 150], [223.6396, 213.6396],
    [160, 240], [96.3604, 213.6396], [70, 150], [96.3604, 86.3604],
    [160, 270], [160, 308], [160, 346], [160, 384],
  ]);
});

test('shroom canvas keeps its fixed 320x420', () => {
  const { canvas } = run(shroomCap(), new Uint8Array(36));
  assert.strictEqual(canvas.width, 320);
  assert.strictEqual(canvas.height, 420);
});

test('a zero-pixel capability draws nothing and does not throw', () => {
  const cap = {
    type: 'capability', surface_id: 'empty', pixel_count: 0,
    color_order: 'GRB', zones: [{ name: 'primary', start: 0, count: 0 }],
  };
  const { canvas } = run(cap, new Uint8Array(0));
  assert.strictEqual(marks(canvas).length, 0);
});

// --- Task 3: a linear surface fits the canvas -----------------------------

test('an 864px linear surface draws every pixel within canvas bounds', () => {
  const { canvas } = run(linearCap(864), new Uint8Array(864 * 3), { w: 1440, h: 900 });
  const pts = marks(canvas);
  assert.strictEqual(pts.length, 864, `drew ${pts.length} marks, want 864`);
  for (const [x, y] of pts) {
    assert.ok(x >= 0 && x <= canvas.width,
      `x ${x} outside 0..${canvas.width}`);
    assert.ok(y >= 0 && y <= canvas.height,
      `y ${y} outside 0..${canvas.height}`);
  }
});

test('an 864px linear surface is strictly increasing and evenly spaced', () => {
  const { canvas } = run(linearCap(864), new Uint8Array(864 * 3), { w: 1440, h: 900 });
  const xs = marks(canvas).map((p) => p[0]);
  const step = xs[1] - xs[0];
  assert.ok(step > 0, 'positions must increase left to right');
  for (let i = 1; i < xs.length; i++) {
    assert.ok(xs[i] > xs[i - 1], `position ${i} did not increase`);
    assert.ok(Math.abs((xs[i] - xs[i - 1]) - step) < 1e-9,
      `uneven spacing at ${i}: ${xs[i] - xs[i - 1]} vs ${step}`);
  }
});

test('a dense linear surface draws marks at least one pixel wide', () => {
  const { canvas } = run(linearCap(864), new Uint8Array(864 * 3), { w: 1440, h: 900 });
  const widths = canvas.ops.filter((o) => o[0] === 'fillRect').map((o) => o[3]);
  assert.strictEqual(widths.length, 864,
    'a sub-3px pitch should draw rects, not radial gradients');
  for (const w of widths) assert.ok(w >= 1, `mark width ${w} is under one pixel`);
});

test('a sparse linear surface still gets round glowing dots', () => {
  const { canvas } = run(linearCap(60), new Uint8Array(60 * 3), { w: 800, h: 600 });
  const arcs = canvas.ops.filter((o) => o[0] === 'arc');
  assert.ok(arcs.length > 0, 'a 12.7px pitch should draw arcs, not rects');
  const radii = arcs.map((o) => o[3]);
  for (const r of radii) assert.ok(r > 0, `radius ${r} must be positive`);
});

test('a resize before the capability arrives is a no-op', () => {
  /* The listener is registered at script load, so a browser resized during
     the connect handshake fires it with no cap and no canvas geometry. */
  const { canvas, listeners } = run(null, null, { w: 1440, h: 900 });
  assert.ok(listeners.resize, 'the page must register a resize listener');
  assert.doesNotThrow(() => listeners.resize());
  assert.strictEqual(canvas.ops.length, 0, 'nothing may be drawn before cap');
});

test('a resize relays out and repaints the last frame', () => {
  const { canvas, listeners } = run(linearCap(864), new Uint8Array(864 * 3),
                                    { w: 1440, h: 900 });
  const before = marks(canvas).length;
  assert.ok(listeners.resize, 'the page must register a resize listener');
  canvas.ops.length = 0;
  listeners.resize();
  assert.strictEqual(marks(canvas).length, before,
    'a resize must repaint every pixel of the held frame');
});

// --- runner --------------------------------------------------------------

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log(`ok   ${name}`); }
  catch (e) { failed++; console.error(`FAIL ${name}\n     ${e.message}`); }
}
process.exit(failed ? 1 : 0);
