# WebSim Linear Surface Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `WebSimBackend`'s served page render a linear Room surface of any
declared size in one fitted row, and replay the last frame to a browser that
connects after it was sent.

**Architecture:** One production file changes, `luxaeterna/backends/websim.py`.
Two independent defects: Python-side (the backend forgets the frame it is
displaying) and JavaScript-side (`PAGE_HTML`'s `pos()` fallback uses a fixed
24 px pitch on a fixed 320 px canvas). The Python fix lands first because it is
self-contained. The JS fix lands behind a characterization test that pins the
existing 12-LED Shroom layout, so the one layout that works today cannot
silently regress while the other is being built.

**Tech Stack:** Python 3.10+, `websockets` >= 13 (optional extra, tests
`importorskip` it), plain canvas JavaScript with no libraries and no build step,
Node's built-in `vm` and `node:assert` for the JS tests (no npm, no
`package.json`, no dependencies).

**Spec:** `docs/superpowers/specs/2026-08-19-websim-linear-surface-layout-design.md`

## Global Constraints

- **Branch:** `claude/websim-linear-surface-layout`, already created, spec
  already committed at `c1be32d`.
- **Do not stage `docs/deployment.md`.** It carries an unrelated, stale
  uncommitted edit that predates this work. Every `git add` in this plan names
  explicit paths for that reason. Never use `git add -A` or `git add .`.
- **Run the suite as** `.venv/bin/python -m pytest tests -q` from
  `/Users/chris/projects/luxaeterna`. Baseline before this plan: **220 passed**.
- **`pos()`'s `ring` and `stem` branches must not change**, byte for byte. The
  canonical 12-LED Shroom is the only layout in production use today.
- **No new runtime dependency.** The page stays self-contained: no CDN, no
  external stylesheet, no library. The JS tests use only Node built-ins.
- **No mm-terrarium code changes.** The backend-side replay makes its
  `--identify-blocks` path correct as written. mm-terrarium's venv installs
  luxaeterna editable from `/Users/chris/projects/luxaeterna`, so changes here
  are picked up with no reinstall.
- **Margin constant is 20 px** (`MARGIN`), pitch threshold for the dense
  rendering path is **3 px**.

---

## File Structure

| File | Responsibility | Task |
|------|----------------|------|
| `luxaeterna/backends/websim.py` | Backend: remember and replay the last frame. Page: fitted linear layout. | 1, 3 |
| `tests/backends/test_websim_serve.py` | Existing. Gains three replay tests. | 1 |
| `tests/js/websim_layout.test.js` | New. Drives the real page script under `vm` with a canvas stub. | 2, 3 |
| `tests/backends/test_websim_layout.py` | New. Extracts the page script, shells out to node, skips cleanly without it. | 2 |

The JS test file holds every page-behavior assertion, and the Python wrapper
holds only the extraction and the subprocess call. That split is what keeps the
served page the single source of truth: the wrapper reads `PAGE_HTML` at test
time, so the page and the tests cannot drift.

---

### Task 1: The backend remembers and replays its last frame

**Files:**
- Modify: `luxaeterna/backends/websim.py` (`__init__`, `send`, `_handle`)
- Test: `tests/backends/test_websim_serve.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `WebSimBackend._last_frame: bytes | None`, private. No public API
  change. Later tasks do not depend on it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/backends/test_websim_serve.py`:

```python
def test_client_connecting_after_a_send_receives_the_last_frame():
    """A consumer that paints once, then waits, must still be visible to a
    browser that opens later. harness/room_simulator.py --identify-blocks in
    mm-terrarium is exactly that consumer: it sends one static frame at
    startup and then sleeps, and a human necessarily opens the printed URL
    after that."""
    pytest.importorskip("websockets")
    from websockets.sync.client import connect

    b = WebSimBackend(capability=shroom_capability(), host="127.0.0.1", port=0)
    b.open()
    try:
        b.send(bytearray(range(36)) + bytearray(512 - 36))   # nobody attached yet
        with connect(f"ws://127.0.0.1:{b.port}/ws") as c:
            cap = json.loads(c.recv())
            assert cap["type"] == "capability"           # capability still first
            frame = c.recv()                             # replayed, with no new send
            assert bytes(frame) == bytes(range(36))
    finally:
        b.close()


def test_client_connecting_before_any_send_receives_only_the_capability():
    pytest.importorskip("websockets")
    from websockets.sync.client import connect

    b = WebSimBackend(capability=shroom_capability(), host="127.0.0.1", port=0)
    b.open()
    try:
        with connect(f"ws://127.0.0.1:{b.port}/ws") as c:
            cap = json.loads(c.recv())
            assert cap["type"] == "capability"
            with pytest.raises(TimeoutError):
                c.recv(timeout=0.25)                     # nothing to replay
    finally:
        b.close()


def test_a_later_client_receives_the_last_frame_while_the_first_is_attached():
    pytest.importorskip("websockets")
    from websockets.sync.client import connect

    b = WebSimBackend(capability=shroom_capability(), host="127.0.0.1", port=0)
    b.open()
    try:
        with connect(f"ws://127.0.0.1:{b.port}/ws") as first:
            json.loads(first.recv())
            b.send(bytearray(range(36)) + bytearray(512 - 36))
            assert bytes(first.recv()) == bytes(range(36))
            with connect(f"ws://127.0.0.1:{b.port}/ws") as second:
                json.loads(second.recv())
                assert bytes(second.recv()) == bytes(range(36))
    finally:
        b.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /Users/chris/projects/luxaeterna && .venv/bin/python -m pytest tests/backends/test_websim_serve.py -v
```

Expected: `test_client_connecting_after_a_send_receives_the_last_frame` and
`test_a_later_client_receives_the_last_frame_while_the_first_is_attached` both
FAIL by timing out inside `c.recv()`, because no frame is ever replayed.
`test_client_connecting_before_any_send_receives_only_the_capability` PASSES
already; it is a guard against over-shooting the fix by replaying something
that was never sent.

- [ ] **Step 3: Implement the replay**

Three edits in `luxaeterna/backends/websim.py`.

In `__init__`, after `self.frames: list[bytes] = []`:

```python
        self._last_frame: bytes | None = None
```

In `send()`, immediately after `self.frames.append(payload)`:

```python
        self._last_frame = payload
```

In `_handle()`, after the capability write:

```python
            connection.send(json.dumps(capability_message(self._cap)))
            last = self._last_frame          # read once; send() may replace it
            if last is not None:
                connection.send(last)
            for _ in connection:                     # hold open until close
                pass
```

Note the local `last`. It reads the attribute once rather than twice, which is
tidy but guards nothing: `_last_frame` is set to `None` only in `__init__` and
never reset, so the `is not None` check and the write cannot disagree.

The real, accepted limitation is one line above. `self._clients.add(connection)`
happens BEFORE these writes, so a concurrent `send(B)` can reach this socket
between the read of `last = A` and its write, leaving the client on the older
frame until the next send. This is knowingly not closed: the one-shot consumer
this task exists for sends exactly once, so the race needs a second send and
cannot occur there, and a 44 Hz streaming consumer overwrites the stale frame
within ~22 ms. Closing it properly needs per-connection ordered writes, which is
more machinery than this fix is worth today. Record it, do not build it.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /Users/chris/projects/luxaeterna && .venv/bin/python -m pytest tests/backends/ -v
```

Expected: all three new tests PASS, and every pre-existing websim test still
passes, in particular `test_client_receives_capability_then_frame` (a client
that connects first and receives a live frame is unaffected).

- [ ] **Step 5: Run the whole suite**

```bash
cd /Users/chris/projects/luxaeterna && .venv/bin/python -m pytest tests -q
```

Expected: `223 passed` (220 baseline plus 3).

- [ ] **Step 6: Commit**

```bash
cd /Users/chris/projects/luxaeterna
git add luxaeterna/backends/websim.py tests/backends/test_websim_serve.py
git commit -m "fix(websim): replay the last frame to a client that connects later

A consumer that paints once and then waits was invisible: send() wrote only
to already-attached clients and nothing held the frame currently on display,
so a browser opened after that send saw a permanently black canvas.

The backend now keeps _last_frame and writes it to each new connection right
after the capability blob, preserving the handshake order the page depends on
(it ignores binary frames until cap is set)."
```

---

### Task 2: A behavioral test harness for the page, pinning the Shroom layout

**Files:**
- Create: `tests/js/websim_layout.test.js`
- Create: `tests/backends/test_websim_layout.py`

**Interfaces:**
- Consumes: `PAGE_HTML` from `luxaeterna.backends.websim` (already exported).
- Produces: the node runner contract. `tests/js/websim_layout.test.js` is
  invoked as `node <runner> <path-to-extracted-script.js>` and exits 0 on
  success, 1 on any failed assertion, printing one `ok`/`FAIL` line per test.
  Task 3 adds tests to the same file and relies on that contract unchanged.

This task adds no production code. Its tests describe behavior that already
holds, which is the point: they are the regression guard that makes Task 3's
layout change safe. They must pass on first run.

- [ ] **Step 1: Write the node runner**

Create `tests/js/websim_layout.test.js`:

```javascript
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

// --- runner --------------------------------------------------------------

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log(`ok   ${name}`); }
  catch (e) { failed++; console.error(`FAIL ${name}\n     ${e.message}`); }
}
process.exit(failed ? 1 : 0);
```

- [ ] **Step 2: Write the pytest wrapper**

Create `tests/backends/test_websim_layout.py`:

```python
"""The served page's layout, tested as behavior rather than as text.

PAGE_HTML's only previous coverage was test_page_is_self_contained_canvas, a
substring grep, which cannot see that 852 of an 864-pixel surface were being
drawn off-canvas. This runs the page's real script under Node's vm against a
canvas stub. Mirrors the pattern mm-terrarium adopted (tests/js/ driven from a
pytest wrapper) after its Room panel shipped a rebuild defect past 843 passing
tests: a grep over source text is not a test of behavior.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from luxaeterna.backends.websim import PAGE_HTML

RUNNER = Path(__file__).resolve().parents[1] / "js" / "websim_layout.test.js"


def _page_script() -> str:
    """The page's <script> body, so the served page is the single source of
    truth and the tests cannot drift from what browsers actually receive."""
    match = re.search(r"<script>(.*)</script>", PAGE_HTML, re.S)
    assert match, "PAGE_HTML no longer contains a single <script> block"
    return match.group(1)


def test_page_script_is_extractable():
    """Guards the wrapper itself: if PAGE_HTML is restructured so the regex
    stops matching, fail here with a clear reason rather than silently
    handing node an empty file that passes every assertion vacuously."""
    assert "function pos(" in _page_script()


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_page_layout_behaviour():
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as handle:
        handle.write(_page_script())
        script_path = handle.name
    try:
        proc = subprocess.run(
            ["node", str(RUNNER), script_path],
            capture_output=True, text=True, timeout=60,
        )
    finally:
        Path(script_path).unlink(missing_ok=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
```

- [ ] **Step 3: Run the new tests and verify they PASS against current code**

```bash
cd /Users/chris/projects/luxaeterna && .venv/bin/python -m pytest tests/backends/test_websim_layout.py -v
```

Expected: both PASS. These are characterization tests, not TDD red steps. If
`test_page_layout_behaviour` fails here, the harness itself is wrong (the stub,
the extraction, or the expected coordinates), not the page. Debug the harness
before continuing, because Task 3 depends on it being trustworthy.

- [ ] **Step 4: Verify the node runner reports failures properly**

Temporarily change one expected coordinate in the runner (e.g. `[160, 60]` to
`[160, 61]`), re-run Step 3, and confirm the test FAILS with the node output
visible in the pytest assertion message. Then change it back and re-run to
confirm it passes again.

This step exists because a harness that silently passes is worse than no
harness. A `vm` script that throws before reaching its assertions, or an
extraction that yields an empty string, would otherwise look identical to
success.

- [ ] **Step 5: Run the whole suite**

```bash
cd /Users/chris/projects/luxaeterna && .venv/bin/python -m pytest tests -q
```

Expected: `225 passed` (223 from Task 1 plus 2).

- [ ] **Step 6: Commit**

```bash
cd /Users/chris/projects/luxaeterna
git add tests/js/websim_layout.test.js tests/backends/test_websim_layout.py
git commit -m "test(websim): behavioral tests for the served page's layout

The page had one test, a substring grep over PAGE_HTML, which passes just as
happily when 852 of 864 pixels are drawn off-canvas. This runs the real page
script under Node's vm against a canvas stub, driven through its own
websocket entry point rather than by poking internals.

These pin the current 12-LED Shroom ring and stem positions to literal
coordinates, so the linear-layout change that follows cannot regress the one
layout in production use. Skips cleanly where node is absent."
```

---

### Task 3: Fitted single-row layout for linear surfaces

**Files:**
- Modify: `luxaeterna/backends/websim.py` (`PAGE_HTML`, style block and script block)
- Test: `tests/js/websim_layout.test.js`

**Interfaces:**
- Consumes: the node runner contract from Task 2 (`node <runner> <script.js>`,
  exit 0 or 1), and its `run()`, `marks()`, `linearCap()`, `shroomCap()`,
  `test()`, `round4` helpers, all already defined in that file.
- Produces: no Python API change. `PAGE_HTML` keeps its name, its single
  `<script>` block, and its `<title>` line, so `_labeled_page_html()`'s
  title replacement and `test_label_appends_to_title` keep working untouched.

- [ ] **Step 1: Write the failing tests**

Insert into `tests/js/websim_layout.test.js`, after the Task 2 block and before
the `// --- runner ---` section:

```javascript
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /Users/chris/projects/luxaeterna && .venv/bin/python -m pytest tests/backends/test_websim_layout.py -v
```

Expected: FAIL. The node output in the assertion message should show the three
Task 2 tests still `ok`, and the new ones failing: bounds fails because pixel
positions run to x=20752 on a 320px canvas, the rect test fails because the
current code always draws gradients, and the resize test fails because the
current page registers no resize listener.

- [ ] **Step 3: Replace the page's style and script**

In `luxaeterna/backends/websim.py`, add one line to the `<style>` block so a
wide canvas can never force a horizontal scrollbar. The `canvas` rule becomes:

```css
 canvas{background:#0b0b0f;max-width:100%}
```

Then replace the entire `<script>` block with:

```javascript
<script>
const cv=document.getElementById('c'),cx=cv.getContext('2d'),st=document.getElementById('s');
const MARGIN=20;
let cap=null,linear=false,pitch=24,held=null;
const ws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws');
ws.binaryType='arraybuffer';
ws.onopen=()=>st.textContent='connected';
ws.onclose=()=>st.textContent='disconnected';
ws.onmessage=(e)=>{
  if(typeof e.data==='string'){
    cap=JSON.parse(e.data);
    linear=!cap.zones.some(z=>z.name==='ring'||z.name==='stem');
    st.textContent=cap.surface_id+' · '+cap.pixel_count+'px '+cap.color_order;
    layout();return;
  }
  if(!cap)return; held=new Uint8Array(e.data); draw(held);
};
function layout(){
  if(!cap)return;
  if(linear){
    cv.width=Math.max(320,window.innerWidth-40);
    cv.height=Math.max(120,Math.min(420,window.innerHeight-80));
    pitch=(cv.width-2*MARGIN)/Math.max(1,cap.pixel_count);
  }else{cv.width=320;cv.height=420;pitch=24;}
  if(held)draw(held);
}
window.addEventListener('resize',layout);
function pos(i){
  if(linear)return [MARGIN+(i+0.5)*pitch,cv.height/2];
  const ring=cap.zones.find(z=>z.name==='ring'),stem=cap.zones.find(z=>z.name==='stem');
  if(ring&&i>=ring.start&&i<ring.start+ring.count){
    const k=i-ring.start,a=-Math.PI/2+k*2*Math.PI/ring.count;
    return [160+90*Math.cos(a),150+90*Math.sin(a)];
  }
  if(stem&&i>=stem.start&&i<stem.start+stem.count){
    const k=i-stem.start;return [160,270+k*38];
  }
  return [40+i*24,380];
}
function rgb(f,i){
  const o=cap.color_order,b=[f[i*3],f[i*3+1],f[i*3+2]],m={};
  for(let j=0;j<3;j++)m[o[j]]=b[j];
  return 'rgb('+(m.R||0)+','+(m.G||0)+','+(m.B||0)+')';
}
function draw(f){
  cx.clearRect(0,0,cv.width,cv.height);
  const glow=Math.min(20,pitch*1.5),dot=Math.max(0.5,Math.min(7,pitch*0.4)),
        dense=pitch<3,w=Math.ceil(pitch),h=Math.max(24,Math.min(80,cv.height/4));
  for(let i=0;i<cap.pixel_count;i++){
    const [x,y]=pos(i),c=rgb(f,i);
    if(dense){cx.fillStyle=c;cx.fillRect(x-pitch/2,y-h/2,w,h);continue;}
    const g=cx.createRadialGradient(x,y,1,x,y,glow);
    g.addColorStop(0,c);g.addColorStop(1,'rgba(0,0,0,0)');
    cx.fillStyle=g;cx.beginPath();cx.arc(x,y,glow,0,2*Math.PI);cx.fill();
    cx.fillStyle=c;cx.beginPath();cx.arc(x,y,dot,0,2*Math.PI);cx.fill();
  }
}
</script>
```

What changed and why, for the reviewer:

- `linear` is computed once, when the capability arrives, from the absence of
  both a `ring` and a `stem` zone. It selects both the layout branch in `pos()`
  and the canvas sizing in `layout()`, so those two can never disagree.
- `layout()` sizes the canvas to the viewport only when `linear`. A Shroom keeps
  its declared 320x420, because the ring and stem branches are hardcoded to
  absolute coordinates (centre 160,150, radius 90) that assume it.
- At the non-linear `pitch` of 24, `glow` evaluates to `min(20,36)=20` and `dot`
  to `max(0.5,min(7,9.6))=7`, the previous constants exactly. The Shroom's
  rendering is unchanged by construction, not by coincidence.
- `held` keeps the last frame so a resize can repaint rather than blank the
  canvas until the next tick, which matters for a one-shot consumer.
- `Math.max(1,cap.pixel_count)` is the divide-by-zero guard for an empty
  surface; `draw()`'s loop then does not execute.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /Users/chris/projects/luxaeterna && .venv/bin/python -m pytest tests/backends/test_websim_layout.py -v
```

Expected: PASS, with all nine node tests reporting `ok`. Critically, the three
Task 2 tests must still pass: the Shroom's ring and stem coordinates are
unchanged and its canvas is still 320x420.

- [ ] **Step 5: Run the whole suite**

```bash
cd /Users/chris/projects/luxaeterna && .venv/bin/python -m pytest tests -q
```

Expected: `225 passed`. No new test count, because Task 3 adds JS tests inside
the single wrapped pytest test. Every pre-existing test must still pass,
including `test_page_is_self_contained_canvas`, `test_label_appends_to_title`
and `test_label_is_html_escaped`, which read `PAGE_HTML` directly.

- [ ] **Step 6: Commit**

```bash
cd /Users/chris/projects/luxaeterna
git add luxaeterna/backends/websim.py tests/js/websim_layout.test.js
git commit -m "fix(websim): fit a linear surface to the canvas instead of truncating at 12px

pos()'s no-ring/no-stem fallback used a fixed 24px pitch on a fixed 320px
canvas, so pixel 12 landed at x=328 and every pixel after it was drawn
off-canvas. Measured against mm-terrarium's 864px DEMO Room profile: 12
pixels on-canvas, 852 off, the last drawn at x=20752.

A linear surface now sizes the canvas to the viewport and fits every pixel
in one row, with glow and dot radii derived from the pitch rather than fixed
(a 20px glow at sub-pixel pitch overlaps ~40 neighbours and smears the strip
into one wash, hiding the very boundaries an operator is checking). Below a
3px pitch each pixel draws as a rect, which is both the legible rendering at
that density and the cheap one.

Ring and stem are untouched: at their 24px pitch the new expressions
evaluate to the previous constants, and the canvas resize is gated on the
same condition that selects the layout."
```

---

### Task 4: Verify against the real DEMO and TEST simulators

**Files:** none. This task changes no code. It is the acceptance gate that the
fix works against a real consumer rather than only against stubs.

**Interfaces:**
- Consumes: the finished `luxaeterna/backends/websim.py` from Tasks 1 and 3.
- Produces: nothing consumed by later tasks. The three full live-verify
  checklists in the spec's section 10 are a separate pass and need a running
  Arco; this task deliberately needs none.

mm-terrarium's venv installs luxaeterna editable from
`/Users/chris/projects/luxaeterna`, so it picks up this branch with no
reinstall. Confirm that first, since every assertion below depends on it.

- [ ] **Step 1: Confirm the editable install resolves to this branch**

```bash
.venv/bin/python -c "import luxaeterna, os; print(os.path.realpath(luxaeterna.__file__))"
```

Expected: a path under `/Users/chris/projects/luxaeterna/`. If it prints a
path inside `site-packages` instead, the install is not editable and the rest
of this task will silently test the old code. Stop and reinstall with
`.venv/bin/python -m pip install -e /Users/chris/projects/luxaeterna` before
continuing.

- [ ] **Step 2: Start the DEMO identify-blocks simulator**

```bash
cd /Users/chris/projects/mm-terrarium/.claude/worktrees/sweet-swirles-296e20 && .venv/bin/python -m harness.room_simulator --dev sim-demo --fixture array --room-type DEMO --server 'ws://127.0.0.1:1/' --identify-blocks --sim-port 8801
```

This needs no Arco and no Control: `--identify-blocks` skips the websocket
connect entirely. The dummy `--server` value satisfies a required argument that
this mode never uses. Leave it running.

- [ ] **Step 3: Open the canvas and confirm six bands**

Open `http://127.0.0.1:8801/` in a browser, **after** the process has printed
its URL. That ordering is the whole point: before Task 1 this showed a black
canvas, because the frame had already been sent to nobody.

Confirm by eye:
- The header reads `room_demo_array · 864px GRB`.
- Six distinct solid colour bands are visible: red, orange, yellow, green,
  blue, violet, left to right in that order.
- Each band is the same width as the others, since all six blocks are 144 px.

- [ ] **Step 4: Confirm the pixel arithmetic in the page**

In the browser console, or via a scripted evaluation:

```javascript
(() => {
  const cv = document.getElementById('c');
  return { canvasWidth: cv.width, canvasHeight: cv.height,
           header: document.getElementById('s').textContent };
})()
```

Expected: `canvasWidth` is the viewport width minus 40, not 320, and the header
reports 864px. Before this change the same probe reported a 320px canvas with
852 of 864 pixels off it.

- [ ] **Step 5: Confirm the TEST fixture still renders, and the Shroom too**

Stop the DEMO simulator, then run the TEST `main` fixture:

```bash
cd /Users/chris/projects/mm-terrarium/.claude/worktrees/sweet-swirles-296e20 && .venv/bin/python -m harness.room_simulator --dev sim-test --fixture main --room-type TEST --server 'ws://127.0.0.1:1/' --identify-blocks --sim-port 8803
```

Expected at `http://127.0.0.1:8803/`: header reads `room_test_main · 60px GRB`,
and a single red band spans the strip (TEST `main` declares one block covering
all 60 px, so one colour is correct here, not six).

Then confirm the Shroom path is untouched by running luxaeterna's own demo:

```bash
cd /Users/chris/projects/luxaeterna && .venv/bin/python -m luxaeterna.websim_demo
```

Expected: the familiar 8-LED ring with a 4-LED stem below it, centred, exactly
as before this change.

- [ ] **Step 6: Stop the simulators**

```bash
pkill -f 'harness.room_simulator'; pkill -f 'luxaeterna.websim_demo'
```

- [ ] **Step 7: Confirm mm-terrarium's suite is unaffected**

```bash
cd /Users/chris/projects/mm-terrarium/.claude/worktrees/sweet-swirles-296e20 && .venv/bin/python -m pytest tests -q 2>&1 | tail -3
```

Expected: `1057 passed, 1 skipped`, unchanged. No mm-terrarium code changed, so
any difference here is a real regression introduced through the shared
luxaeterna dependency and must be investigated before this branch merges.

---

## After the plan

This branch is a prerequisite, not the deliverable. Once it merges, the three
live-verify checklists in the spec's section 10 become performable for the
first time, and that verification pass is the actual goal:

- **A.** Triggers: fire `play_aurora` from the Console with no device joined.
- **B.** N-fixture Room: one rainbow across both TEST simulator tabs, no seam.
- **C.** DEMO: rainbow across all 864 px with no seam at six block boundaries.

All three need a running Arco via `harness/run_stack.py`. C's device-join half
is gated behind the separate upstream headless clock-sync defect and has to be
run from an interactive terminal.

A deep-dive sync for mm-terrarium (`docs/MM_TERRARIUM.md`) is also outstanding:
the *Terrarium Visualization Simulator* and *DEMO room* sections both describe
the Room canvas as a working visual check, which it was not.
