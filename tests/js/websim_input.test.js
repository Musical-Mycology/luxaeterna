/* Behavioral tests for the WebSim page's input handlers.
 *
 * Same harness shape as websim_layout.test.js: the page script is
 * extracted from PAGE_HTML by tests/backends/test_websim_input_page.py
 * and handed here as argv[2]. The WebSocket stub additionally captures
 * sends and models readyState; timers are captured so the click delay
 * window can be stepped deterministically.
 */
const assert = require('node:assert');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(process.argv[2], 'utf8');

const tests = [];
function test(name, fn) { tests.push([name, fn]); }

function makeCanvas() {
  const ctx2d = {
    clearRect: () => {}, fillRect: () => {}, beginPath: () => {},
    arc: () => {}, fill: () => {},
    createRadialGradient: () => ({ addColorStop: () => {} }),
    set fillStyle(v) {}, get fillStyle() { return null; },
  };
  return { width: 320, height: 420, clientWidth: 320, getContext: () => ctx2d };
}

function run() {
  const canvas = makeCanvas();
  const status = { textContent: '' };
  const timers = [];
  const sandbox = {
    console, Math, JSON, Uint8Array, Date,
    setTimeout: (fn, ms) => { timers.push([fn, ms]); return timers.length; },
    clearTimeout: (id) => { if (timers[id - 1]) timers[id - 1][0] = null; },
    location: { protocol: 'http:', host: 'localhost:1' },
    document: { getElementById: (id) => (id === 'c' ? canvas : status) },
    window: { innerWidth: 800, innerHeight: 600, addEventListener: () => {} },
  };
  sandbox.WebSocket = function () {
    sandbox.__sock = this;
    this.readyState = 1;
    this.sent = [];
    this.send = (m) => this.sent.push(m);
  };
  sandbox.WebSocket.OPEN = 1;
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox);
  const sock = sandbox.__sock;
  assert.ok(sock, 'the page script did not construct a WebSocket');
  const fireTimers = () => {
    for (const t of timers.splice(0)) if (t[0]) t[0]();
  };
  const gestures = () => sock.sent
    .filter((m) => typeof m === 'string')
    .map((m) => JSON.parse(m));
  return { canvas, sock, fireTimers, gestures };
}

test('a tap sends immediately on pointerup, no delay window', () => {
  const { canvas, gestures } = run();
  canvas.onpointerdown({ offsetX: 100, offsetY: 100 });
  canvas.onpointerup({ offsetX: 100, offsetY: 100 });
  assert.deepStrictEqual(gestures(), [{ type: 'tap', count: 1 }]);
});

test('a pointerup with no preceding pointerdown sends nothing', () => {
  const { canvas, gestures } = run();
  canvas.onpointerup({ offsetX: 100, offsetY: 100 });
  assert.deepStrictEqual(gestures(), []);
});

test('a drag maps canvas x onto gamma in [-90, 90]', () => {
  const { canvas, gestures } = run();
  canvas.onpointerdown({ offsetX: 160, offsetY: 100 });
  canvas.onpointermove({ offsetX: 320, offsetY: 100 });  // right edge
  canvas.onpointerup({ offsetX: 320, offsetY: 100 });
  const tilts = gestures().filter((g) => g.type === 'tilt');
  assert.ok(tilts.length >= 1);
  assert.strictEqual(tilts[tilts.length - 1].gamma, 90);
});

test('drag tilts are rate-bounded to one per 50 ms', () => {
  const { canvas, gestures } = run();
  canvas.onpointerdown({ offsetX: 0, offsetY: 100 });
  for (let x = 0; x <= 320; x += 8) canvas.onpointermove({ offsetX: x, offsetY: 100 });
  canvas.onpointerup({ offsetX: 320, offsetY: 100 });
  const tilts = gestures().filter((g) => g.type === 'tilt');
  // Date.now() does not advance inside one test run, so the throttle
  // admits only the first move (plus the final pointerup flush).
  assert.ok(tilts.length <= 2, `expected <= 2 tilts, got ${tilts.length}`);
});

test('a real drag suppresses the tap that follows it', () => {
  const { canvas, gestures } = run();
  canvas.onpointerdown({ offsetX: 100, offsetY: 100 });
  canvas.onpointermove({ offsetX: 200, offsetY: 100 });
  canvas.onpointerup({ offsetX: 200, offsetY: 100 });
  assert.deepStrictEqual(gestures().filter((g) => g.type === 'tap'), []);
});

test('nothing is sent when the socket is not open', () => {
  const { canvas, sock, gestures } = run();
  sock.readyState = 3;                                    // CLOSED
  canvas.onpointerdown({ offsetX: 100, offsetY: 100 });
  canvas.onpointerup({ offsetX: 100, offsetY: 100 });
  assert.deepStrictEqual(gestures(), []);
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log('ok', name); }
  catch (err) { failed += 1; console.error('FAIL', name); console.error(err); }
}
process.exit(failed ? 1 : 0);
