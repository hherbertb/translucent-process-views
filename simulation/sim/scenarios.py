"""Registry of scenarios: name -> Scenario object and Case class."""
from __future__ import annotations

from . import p2p, p2p_shared

_MODULES = [p2p, p2p_shared]
try:  # noqa: SIM105
    from . import o2c
    _MODULES.append(o2c)
except ImportError:
    pass
try:  # noqa: SIM105
    from . import tickets
    _MODULES.append(tickets)
except ImportError:
    pass

SCENARIOS = {m.SCENARIO.name: m.SCENARIO for m in _MODULES}
CASES = {m.SCENARIO.name: m.Case for m in _MODULES}
