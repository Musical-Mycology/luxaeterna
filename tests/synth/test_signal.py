import numpy as np
from luxaeterna.synth.signal import LightUgen, RenderContext, as_ugen


def _ctx(frame=0, n=4, channels=3, time=0.0, dt=1 / 44):
    return RenderContext(time=time, frame=frame, dt=dt,
                         positions=np.linspace(0, 1, n), n=n, channels=channels)


def test_render_is_memoized_per_frame():
    calls = []

    class Counter(LightUgen):
        rate = "control"
        def _compute(self, ctx):
            calls.append(ctx.frame)
            return np.asarray(1.0)

    u = Counter()
    ctx = _ctx(frame=5)
    u.render(ctx)
    u.render(ctx)                      # same frame → cached
    u.render(_ctx(frame=6))            # new frame → recompute
    assert calls == [5, 6]


def test_as_ugen_wraps_scalar():
    u = as_ugen(0.5)
    assert isinstance(u, LightUgen)
    assert float(u.render(_ctx())) == 0.5
    same = as_ugen(u)
    assert same is u
