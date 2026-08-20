"""Lux Aeterna — WebSimBackend: a DMX backend that records frames and (when
serving) streams them to a self-contained browser canvas — an on-screen LED
simulator for the canonical Shroom. websockets is imported lazily so record-only
mode and this import work without the optional 'websim' extra installed."""

from __future__ import annotations

import html
import json
import threading

from .base import DMXBackend
from ..synth.capability import SurfaceCapability, shroom_capability


PAGE_HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>Lux Aeterna — Shroom LED Simulator</title>
<style>
 body{background:#0b0b0f;margin:0;display:flex;height:100vh;
      align-items:center;justify-content:center}
 canvas{background:#0b0b0f}
 #s{position:fixed;top:8px;left:8px;color:#556;font:12px monospace}
</style></head><body>
<div id="s">connecting…</div><canvas id="c" width="320" height="420"></canvas>
<script>
const cv=document.getElementById('c'),cx=cv.getContext('2d'),st=document.getElementById('s');
let cap=null;
const ws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws');
ws.binaryType='arraybuffer';
ws.onopen=()=>st.textContent='connected';
ws.onclose=()=>st.textContent='disconnected';
ws.onmessage=(e)=>{
  if(typeof e.data==='string'){cap=JSON.parse(e.data);st.textContent=cap.surface_id+' · '+cap.pixel_count+'px '+cap.color_order;return;}
  if(!cap)return; draw(new Uint8Array(e.data));
};
function pos(i){
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
  for(let i=0;i<cap.pixel_count;i++){
    const [x,y]=pos(i),c=rgb(f,i);
    const g=cx.createRadialGradient(x,y,1,x,y,20);
    g.addColorStop(0,c);g.addColorStop(1,'rgba(0,0,0,0)');
    cx.fillStyle=g;cx.beginPath();cx.arc(x,y,20,0,2*Math.PI);cx.fill();
    cx.fillStyle=c;cx.beginPath();cx.arc(x,y,7,0,2*Math.PI);cx.fill();
  }
}
</script></body></html>"""


def _labeled_page_html(label: str) -> str:
    """Return PAGE_HTML with an identifying label appended to its <title>."""
    labeled_title = (f"<title>Lux Aeterna — Shroom LED Simulator — "
                      f"{html.escape(label)}</title>")
    return PAGE_HTML.replace(
        "<title>Lux Aeterna — Shroom LED Simulator</title>", labeled_title, 1)


def capability_message(cap: SurfaceCapability) -> dict:
    """The connect-time handshake: enough geometry for a browser to lay out and
    color the pixels from raw DMX frames."""
    return {
        "type": "capability",
        "surface_id": cap.surface_id,
        "pixel_count": cap.pixel_count,
        "color_order": cap.color_order,
        "zones": [{"name": z.name, "start": z.start, "count": z.count}
                  for z in cap.zones],
    }


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
        self._last_frame: bytes | None = None
        self._open = False
        self._server = None
        self._thread = None
        self._lock = threading.Lock()
        self._clients: set = set()

    # --- DMXBackend ---------------------------------------------------------
    def open(self) -> None:
        if self._open:
            return
        if self._serve:
            from websockets.sync.server import serve
            self._server = serve(self._handle, self._host, self._port,
                                 process_request=self._process_request)
            self._port = self._server.socket.getsockname()[1]
            self._thread = threading.Thread(target=self._server.serve_forever,
                                            daemon=True)
            self._thread.start()
        self._open = True

    def close(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._open = False

    def send(self, frame, universe_id: int = 0) -> None:
        payload = bytes(frame[:self._n])             # copy; never mutate frame
        self.frames.append(payload)
        self._last_frame = payload
        if not self._serve:
            return
        with self._lock:
            clients = list(self._clients)
        for c in clients:
            try:
                c.send(payload)
            except Exception:
                with self._lock:
                    self._clients.discard(c)

    @property
    def is_open(self) -> bool:
        return self._open

    @property
    def port(self) -> int:
        return self._port

    # --- server internals ---------------------------------------------------
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

    def _handle(self, connection) -> None:
        with self._lock:
            self._clients.add(connection)
        try:
            connection.send(json.dumps(capability_message(self._cap)))
            # Reading once guards nothing (_last_frame is set once, in
            # __init__, and never reset to None). Real, accepted gap: this
            # connection is already in self._clients, so a concurrent send()
            # can land a fresher frame ahead of this replay, leaving the
            # client stale until the next send. See design doc section 6.
            last = self._last_frame
            if last is not None:
                connection.send(last)
            for _ in connection:                     # hold open until close
                pass
        except Exception:
            pass
        finally:
            with self._lock:
                self._clients.discard(connection)
