"""Abstraction identifiers -- Definition 4.1.

Definition 4.1 (Abstraction identifiers).  The set ``K`` of abstraction
identifiers is the smallest set such that

* ``epsilon in K``,
* ``a in K`` for every activity ``a``,
* ``seq(K_1, ..., K_n) in K`` for ``n >= 2`` (order sensitive),
* ``xor(S) in K`` for a set ``S`` of identifiers with ``|S| >= 2``,
* ``and(S) in K`` for a set ``S`` of identifiers with ``|S| >= 2``.

``xor`` and ``and`` take *sets*, hence are order insensitive; ``seq`` is order
sensitive.  Every identifier has a canonical string (set members sorted by their
own canonical string) so that identifier equality reduces to string equality --
this string is the key that groups traces into process views (Definition 4.11).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Tuple

from pm4py.objects.process_tree.obj import Operator, ProcessTree


class Identifier:
    """Base class for abstraction identifiers."""

    def canonical_str(self) -> str:  # pragma: no cover - overridden
        raise NotImplementedError

    def to_process_tree(self, parent: ProcessTree | None = None) -> ProcessTree:  # pragma: no cover
        raise NotImplementedError

    # identifier equality == canonical-string equality (Definition 4.1 / 3.5)
    def __eq__(self, other: object) -> bool:
        return isinstance(other, Identifier) and self.canonical_str() == other.canonical_str()

    def __hash__(self) -> int:
        return hash(self.canonical_str())

    def __repr__(self) -> str:
        return self.canonical_str()


@dataclass(frozen=True, eq=False)
class Empty(Identifier):
    """``epsilon`` -- abstraction of the empty trace."""

    def canonical_str(self) -> str:
        return "epsilon"

    def to_process_tree(self, parent: ProcessTree | None = None) -> ProcessTree:
        return ProcessTree(parent=parent)  # a leaf with label None == tau


@dataclass(frozen=True, eq=False)
class Act(Identifier):
    """A single activity ``a``."""

    name: str

    def canonical_str(self) -> str:
        return self.name

    def to_process_tree(self, parent: ProcessTree | None = None) -> ProcessTree:
        return ProcessTree(label=self.name, parent=parent)


@dataclass(frozen=True, eq=False)
class Seq(Identifier):
    """``seq(K_1, ..., K_n)`` -- order-sensitive sequential composition."""

    children: Tuple[Identifier, ...]

    def __post_init__(self) -> None:
        flat: list[Identifier] = []
        for child in self.children:
            if isinstance(child, Seq):  # seq inside seq collapses
                flat.extend(child.children)
            else:
                flat.append(child)
        object.__setattr__(self, "children", tuple(flat))

    def canonical_str(self) -> str:
        return "seq(" + ", ".join(c.canonical_str() for c in self.children) + ")"

    def to_process_tree(self, parent: ProcessTree | None = None) -> ProcessTree:
        node = ProcessTree(operator=Operator.SEQUENCE, parent=parent)
        node.children = [c.to_process_tree(node) for c in self.children]
        return node


@dataclass(frozen=True, eq=False)
class _SetOp(Identifier):
    members: Tuple[Identifier, ...]

    _keyword: ClassVar[str] = ""
    _operator: ClassVar[Operator | None] = None

    def __post_init__(self) -> None:
        # order-insensitive: dedupe by canonical string, then sort
        uniq: dict[str, Identifier] = {}
        for m in self.members:
            uniq.setdefault(m.canonical_str(), m)
        ordered = tuple(uniq[k] for k in sorted(uniq))
        object.__setattr__(self, "members", ordered)

    def canonical_str(self) -> str:
        return (
            f"{self._keyword}("
            + ", ".join(m.canonical_str() for m in self.members)
            + ")"
        )

    def to_process_tree(self, parent: ProcessTree | None = None) -> ProcessTree:
        if len(self.members) == 1:  # degenerate set -> the member itself
            return self.members[0].to_process_tree(parent)
        node = ProcessTree(operator=self._operator, parent=parent)
        node.children = [m.to_process_tree(node) for m in self.members]
        return node


@dataclass(frozen=True, eq=False)
class Xor(_SetOp):
    """``xor(S)`` -- order-insensitive exclusive choice block."""

    _keyword: ClassVar[str] = "xor"
    _operator: ClassVar[Operator | None] = Operator.XOR


@dataclass(frozen=True, eq=False)
class And(_SetOp):
    """``and(S)`` -- order-insensitive parallel block."""

    _keyword: ClassVar[str] = "and"
    _operator: ClassVar[Operator | None] = Operator.PARALLEL


# -- convenience constructors ------------------------------------------------
def seq(*children: Identifier) -> Identifier:
    """Build ``seq(...)``; a single child degrades to that child (Definition 4.1)."""
    flat: list[Identifier] = []
    for c in children:
        flat.extend(c.children if isinstance(c, Seq) else [c])
    if len(flat) == 1:
        return flat[0]
    return Seq(tuple(flat))


def xor(*members: Identifier) -> Identifier:
    """Build ``xor({...})``; a singleton set degrades to the member (Definition 4.1)."""
    uniq = {m.canonical_str(): m for m in members}
    if len(uniq) == 1:
        return next(iter(uniq.values()))
    return Xor(tuple(uniq.values()))


def and_(*members: Identifier) -> Identifier:
    """Build ``and({...})``; a singleton set degrades to the member (Definition 4.1)."""
    uniq = {m.canonical_str(): m for m in members}
    if len(uniq) == 1:
        return next(iter(uniq.values()))
    return And(tuple(uniq.values()))


def act(name: str) -> Act:
    return Act(name)
