"""Lux Aeterna — fast, lightweight DMX512 control for audio-reactive lighting.

Part of the Musical Mycology toolset.

Quick start::

    from luxaeterna import Universe, OutputLoop, Fixture
    from luxaeterna.backends import ArtNet
    from luxaeterna.fixture import DIMMED_RGB, Attribute

    universe = Universe()
    backend = ArtNet(host="192.168.1.100")
    loop = OutputLoop(universe, backend)

    par = Fixture("par1", DIMMED_RGB, base_channel=0, universe=universe)
    loop.start()

    par.set_rgb(255, 0, 80)
    par.set(Attribute.INTENSITY, 200)

    # ... your application runs ...
    loop.stop()
"""

from .universe import Universe
from .output import OutputLoop
from .fixture import Fixture, Profile, ChannelDef, Attribute
from .exceptions import LuxAeternaError, BackendError, ChannelError, FixtureError

__version__ = "0.1.0"

__all__ = [
    # Core
    "Universe",
    "OutputLoop",
    # Fixtures
    "Fixture",
    "Profile",
    "ChannelDef",
    "Attribute",
    # Exceptions
    "LuxAeternaError",
    "BackendError",
    "ChannelError",
    "FixtureError",
]
