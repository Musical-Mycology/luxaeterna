# Lux Aeterna

Fast, lightweight DMX512 control for audio-reactive lighting. Part of the
Musical Mycology toolset.

## Where it runs

Lux Aeterna is a library, and it runs in one place: **inside** the Terrarium's
Control+GameServer process, driven by direct Python calls (`O2Bridge` is not
involved). It renders every light in the room there and ships the finished
frames to pixel sinks. A Tuneshroom gets raw bytes on `/<dev>/leds` over
o2lite, and the venue's WLED ESP32 controllers will get Art-Net. No device runs
Lux Aeterna, so embedded hardware needs a sink, not a port. See
**[docs/deployment.md](docs/deployment.md)** for the matrix, the hop counts
behind it, the embedded-devices section, and the dev-environment caveat
(Art-Net is UDP — a NAT'd VM or WSL2 host cannot reach WLED controllers; use
`WebSimBackend`).

## Web LED Simulator (WebSimBackend)

`WebSimBackend` is a `DMXBackend` that records DMX frames and streams them to a
self-contained browser canvas — an on-screen simulator of the 12-LED Shroom
(8-ring + 4-stem, GRB). No hardware required.

Install the extra and run the demo:

    pip install luxaeterna[websim]
    python -m luxaeterna.websim_demo
    # open the printed http://127.0.0.1:8770/ and watch it bloom + sweep hue

To drive your own render, point an `OutputLoop` at it:

    backend = WebSimBackend(capability=shroom_capability())
    OutputLoop(universe, backend, on_frame=session.render_into, always_send=True).start()

In tests, construct with `serve=False` for a headless frame recorder (`.frames`).
