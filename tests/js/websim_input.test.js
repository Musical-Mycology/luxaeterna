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
  // Date.now() is the page's only clock; a fake one that moves only when a
  // test sets clock.ms makes press durations deterministic.
  const clock = { ms: 1000 };
  const listeners = {};
  const sandbox = {
    console, Math, JSON, Uint8Array,
    Date: { now: () => clock.ms },
    setTimeout: (fn, ms) => { timers.push([fn, ms]); return timers.length; },
    clearTimeout: (id) => { if (timers[id - 1]) timers[id - 1][0] = null; },
    location: { protocol: 'http:', host: 'localhost:1' },
    document: { getElementById: (id) => (id === 'c' ? canvas : status) },
    window: {
      innerWidth: 800, innerHeight: 600,
      addEventListener: (type, fn) => { listeners[type] = fn; },
    },
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
  const key = (k, repeat = false) => listeners.keydown({ key: k, repeat });
  return { canvas, sock, fireTimers, gestures, clock, key, status };
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

test('a press held for the hold window sends a hold with its duration', () => {
  const { canvas, clock, gestures } = run();
  canvas.onpointerdown({ offsetX: 100, offsetY: 100 });
  clock.ms += 1250;
  canvas.onpointerup({ offsetX: 100, offsetY: 100 });
  assert.deepStrictEqual(gestures(), [{ type: 'hold', held_seconds: 1.25 }]);
});

test('a press released just under the hold window is still a tap', () => {
  const { canvas, clock, gestures } = run();
  canvas.onpointerdown({ offsetX: 100, offsetY: 100 });
  clock.ms += 399;
  canvas.onpointerup({ offsetX: 100, offsetY: 100 });
  assert.deepStrictEqual(gestures(), [{ type: 'tap', count: 1 }]);
});

test('a slow drag is a tilt, never a hold', () => {
  const { canvas, clock, gestures } = run();
  canvas.onpointerdown({ offsetX: 100, offsetY: 100 });
  clock.ms += 2000;
  canvas.onpointermove({ offsetX: 200, offsetY: 100 });
  canvas.onpointerup({ offsetX: 200, offsetY: 100 });
  assert.deepStrictEqual(gestures().filter((g) => g.type !== 'tilt'), []);
});

test('arrow keys swing left (negative g) and right (positive g)', () => {
  const { key, gestures } = run();
  key('ArrowLeft');
  key('ArrowRight');
  assert.deepStrictEqual(gestures(), [
    { type: 'swing', signed_peak_g: -2 },
    { type: 'swing', signed_peak_g: 2 },
  ]);
});

test('a held-down arrow key swings once, and other keys do nothing', () => {
  const { key, gestures } = run();
  key('ArrowLeft');
  key('ArrowLeft', true);                                 // auto-repeat
  key('a');
  key('ArrowUp');
  assert.deepStrictEqual(gestures(), [{ type: 'swing', signed_peak_g: -2 }]);
});

test('the status line names the hold and swing it sent', () => {
  const { canvas, clock, key, status } = run();
  canvas.onpointerdown({ offsetX: 100, offsetY: 100 });
  clock.ms += 500;
  canvas.onpointerup({ offsetX: 100, offsetY: 100 });
  assert.strictEqual(status.textContent, 'sent hold 0.50s');
  key('ArrowRight');
  assert.strictEqual(status.textContent, 'sent swing +2g');
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log('ok', name); }
  catch (err) { failed += 1; console.error('FAIL', name); console.error(err); }
}
process.exit(failed ? 1 : 0);
