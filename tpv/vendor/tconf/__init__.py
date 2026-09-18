"""Translucent conformance checking -- vendored.

Source: ``translucent_IMf_heuristics`` (Beyel et al., "Manipulating Translucent
Directly-Follows Graphs for Cut Detection"), directories ``translucent_fitness/``,
``translucent_precision/`` and ``utils/``.

Local adaptations only:
* package-relative imports (``from .trg_rx import ...``);
* removed unused ``matplotlib`` imports (they guarded commented-out plotting).

Algorithms are unchanged.  ``tpv.quality.translucent`` wraps the two entry
points (:func:`tfitness.calculate_log_fitness`,
:func:`precision.translucent_precision_score`) for use on a
:class:`tpv.log.types.TranslucentLog`.
"""
