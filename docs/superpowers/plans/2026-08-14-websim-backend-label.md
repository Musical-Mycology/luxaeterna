# WebSimBackend Label Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `WebSimBackend` callers optionally stamp an identifying `label` into the served page's `<title>`, so two simultaneously-open browser-canvas tabs are visually distinguishable.

**Architecture:** Add a `label: str | None = None` constructor parameter to `WebSimBackend`, stored verbatim as a public `self.label` attribute. When set, `__init__` computes `self._page_html` once by appending an HTML-escaped label to the existing `PAGE_HTML` constant's `<title>` line via a small module-level helper (`_labeled_page_html`); when `None`, `self._page_html` is the untouched module constant. `_process_request` serves `self._page_html` instead of the module-level `PAGE_HTML`. Purely additive — no other behavior changes.

**Tech Stack:** Python 3.10+, stdlib `html` module for escaping, pytest.

## Global Constraints

- `WebSimBackend(...)` with no `label` argument must serve **byte-identical** HTML to today's — every existing caller (`websim_demo.py`, both existing test files) needs zero edits.
- `label` is appended after the existing title text, not a replacement: `Lux Aeterna — Shroom LED Simulator — {label}`.
- The label must be HTML-escaped (`html.escape`) before insertion — never interpolated raw.
- `self.label` is a stored public attribute (matches the `SACN.source_name` precedent at `luxaeterna/backends/sacn.py:41,46`), so it's directly assertable in tests without inspecting HTML.
- Run tests with `.venv/bin/python -m pytest <path> -v` from the repo root — this worktree's `.venv` is already created and has `luxaeterna` installed editable with the `dev` extra (includes `websockets`, `pytest`, `numpy`). Baseline: `.venv/bin/python -m pytest tests -q` currently passes 199/199.

---

### Task 1: `WebSimBackend` gains `label`

**Files:**
- Modify: `luxaeterna/backends/websim.py`
- Test: `tests/backends/test_websim.py`
- Test: `tests/backends/test_websim_serve.py`

**Interfaces:**
- Produces: `WebSimBackend(capability=None, host="127.0.0.1", port=0, serve=True, label: str | None = None)` — new keyword-only-by-position `label` param, appended after `serve`. `WebSimBackend.label: str | None` — stored verbatim. `WebSimBackend._page_html: str` — the HTML actually served (module `PAGE_HTML` when `label is None`, else the labeled variant). Module-level `_labeled_page_html(label: str) -> str` helper.

- [ ] **Step 1: Write the failing tests**

In `tests/backends/test_websim.py`, change the import line to also pull in `PAGE_HTML`:

```python
from luxaeterna.backends.websim import WebSimBackend, capability_message, PAGE_HTML
```

Then append these two test functions to the end of the file:

```python
def test_label_defaults_to_none_and_page_html_is_unchanged():
    b = WebSimBackend(capability=shroom_capability(), serve=False)
    assert b.label is None
    assert b._page_html == PAGE_HTML


def test_label_is_stored_verbatim():
    b = WebSimBackend(capability=shroom_capability(), serve=False, label="sim-room")
    assert b.label == "sim-room"
```

In `tests/backends/test_websim_serve.py`, append these two test functions to the end of the file (no new imports needed — `WebSimBackend` is already imported):

```python
def test_label_appends_to_title():
    b = WebSimBackend(capability=shroom_capability(), label="sim-room")
    assert ("<title>Lux Aeterna — Shroom LED Simulator — sim-room</title>"
            in b._page_html)


def test_label_is_html_escaped():
    b = WebSimBackend(capability=shroom_capability(), label="<script>alert(1)</script>")
    assert "<script>alert(1)</script>" not in b._page_html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in b._page_html
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/backends/test_websim.py tests/backends/test_websim_serve.py -v`

Expected: `test_label_defaults_to_none_and_page_html_is_unchanged` and
`test_label_is_stored_verbatim` FAIL with `TypeError: WebSimBackend.__init__() got an
unexpected keyword argument 'label'` (or, for the first one, potentially an
`AttributeError` if reached — `label` isn't a valid kwarg yet either way). Same for
the two new tests in `test_websim_serve.py`. Existing tests in both files must still
PASS.

- [ ] **Step 3: Implement**

In `luxaeterna/backends/websim.py`, add `html` to the stdlib imports (after `import json`, alphabetically before it — full import block becomes):

```python
import html
import json
import threading
```

Directly below the `PAGE_HTML = """..."""` constant (after its closing `"""`), add the module-level helper:

```python
def _labeled_page_html(label: str) -> str:
    """Return PAGE_HTML with an identifying label appended to its <title>."""
    labeled_title = (f"<title>Lux Aeterna — Shroom LED Simulator — "
                      f"{html.escape(label)}</title>")
    return PAGE_HTML.replace(
        "<title>Lux Aeterna — Shroom LED Simulator</title>", labeled_title, 1)
```

Add a class docstring to `WebSimBackend` (it currently has none) and update `__init__`'s
signature and body:

```python
class WebSimBackend(DMXBackend):
    """Record DMX frames and, when serving, stream them to a self-contained
    browser canvas — an on-screen LED simulator for the canonical Shroom.

    Parameters
    ----------
    capability : SurfaceCapability or None
        Pixel geometry/zones sent in the connect-time handshake. Defaults to
        ``shroom_capability()``.
    host : str
        Address to bind the websocket/HTTP server to.
    port : int
        Port to bind to (0 = OS-assigned, read back via ``.port``).
    serve : bool
        If False, frames are recorded only — no server, no port, headless.
    label : str or None
        Optional identifying text appended to the served page's ``<title>``,
        e.g. ``"sim-room"`` or a device id — lets an operator tell two open
        browser tabs apart. ``None`` (default) leaves the title unchanged.
        Stored verbatim on ``self.label`` for introspection.
    """

    def __init__(self, capability: SurfaceCapability | None = None,
                 host: str = "127.0.0.1", port: int = 0,
                 serve: bool = True, label: str | None = None) -> None:
        self._cap = capability or shroom_capability()
        self._n = self._cap.pixel_count * 3          # bytes we care about
        self._host = host
        self._port = port
        self._serve = serve
        self.label = label
        self._page_html = PAGE_HTML if label is None else _labeled_page_html(label)
        self.frames: list[bytes] = []
        self._open = False
        self._server = None
        self._thread = None
        self._lock = threading.Lock()
        self._clients: set = set()
```

Finally, in `_process_request`, change the one line that reads the module constant to
read the instance attribute instead:

```python
    def _process_request(self, connection, request):
        if request.path == "/ws":
            return None                              # proceed to WS handshake
        from websockets.datastructures import Headers
        from websockets.http11 import Response
        body = self._page_html.encode("utf-8")
        headers = Headers()
        headers["Content-Type"] = "text/html; charset=utf-8"
        headers["Content-Length"] = str(len(body))
        return Response(200, "OK", headers, body)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/backends/test_websim.py tests/backends/test_websim_serve.py -v`

Expected: all tests PASS, including the four new ones and every pre-existing one in
both files (`test_capability_message_describes_the_shroom`,
`test_record_only_backend_records_pixel_slice_without_serving`,
`test_send_does_not_mutate_frame`, `test_page_is_self_contained_canvas`,
`test_client_receives_capability_then_frame`).

Then run the full suite to confirm nothing else broke:

Run: `.venv/bin/python -m pytest tests -q`
Expected: `203 passed` (199 baseline + 4 new).

- [ ] **Step 5: Commit**

```bash
git add luxaeterna/backends/websim.py tests/backends/test_websim.py tests/backends/test_websim_serve.py
git commit -m "feat(websim): add optional label appended to the served page title"
```
