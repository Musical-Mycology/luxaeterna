# Lux Aeterna

Fast, lightweight DMX512 control for audio-reactive lighting. Part of the
Musical Mycology toolset.

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
