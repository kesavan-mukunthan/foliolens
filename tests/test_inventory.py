"""The capability inventory can neither drift nor go silently incomplete.

`scripts/gen_inventory.py` regenerates the ``## Capability inventory`` section
of ``ARCHITECTURE.md`` between markers. CI runs the generator and asserts
``git diff --exit-code ARCHITECTURE.md``; this test is the same gate run
locally, plus the two properties the generator promises:

* **determinism** — rendering the body twice yields byte-identical output, so
  the drift check can never fail for a spurious ordering reason;
* **completeness** — every module under ``src/foliolens/`` appears exactly once,
  so a new module cannot exist without announcing itself (the anti-commentary
  mechanism).

A docstring-less module is *not* an error here — it lands as a loud
``(no module docstring)`` line the drift check refuses to accept, which is the
intended failure mode.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_generator():
    """Import ``scripts/gen_inventory.py`` by path (``scripts`` is not a package)."""
    path = ROOT / "scripts" / "gen_inventory.py"
    spec = importlib.util.spec_from_file_location("gen_inventory", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GEN = _load_generator()


def test_inventory_is_deterministic() -> None:
    """Two independent renders are byte-identical."""
    first = GEN.render_body(GEN.collect_modules())
    second = GEN.render_body(GEN.collect_modules())
    assert first == second


def test_inventory_covers_every_module() -> None:
    """Every ``src/foliolens/`` module appears exactly once in the inventory."""
    on_disk = {p.name for p in GEN.SRC.rglob("*.py")}
    listed = [filename for _package, filename, _sentence in GEN.collect_modules()]
    # Every module is present…
    assert on_disk <= set(listed)
    # …and none is listed twice (identical file names in different packages are
    # fine; the (package, filename) pairs are what must be unique).
    pairs = [(pkg, name) for pkg, name, _ in GEN.collect_modules()]
    assert len(pairs) == len(set(pairs))


def test_architecture_inventory_is_in_sync() -> None:
    """The committed ARCHITECTURE.md matches a fresh generation (no drift)."""
    existing = GEN.ARCHITECTURE.read_text(encoding="utf-8")
    regenerated = GEN.splice(existing, GEN.render_body(GEN.collect_modules()))
    assert existing == regenerated, (
        "ARCHITECTURE.md capability inventory is stale — "
        "run `uv run python scripts/gen_inventory.py`"
    )
