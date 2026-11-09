"""
Plan which armor-arb queries to run on each overnight pass.

Casual: shuffle the list, and sometimes only poke a few items.
"""

from __future__ import annotations

import random
from typing import Sequence

from ah_price.config import (
    ARMOR_ARB_LOOP_SUBSET_CHANCE,
    ARMOR_ARB_LOOP_SUBSET_MAX_ITEMS,
    ARMOR_ARB_LOOP_SUBSET_MIN_ITEMS,
    ARMOR_ARB_SEARCH_QUERIES,
)


class ArmorArbPassPlanner:
    """
    Build a shuffled (sometimes partial) query list for one overnight pass.

    Casual: mix up the order, and every so often skip some items.
    Full single-shot ``--armor-arb`` still walks the whole catalog in config
    order; only the overnight loop uses this planner so daytime runs stay
    predictable.
    """

    def __init__(
        self,
        catalog: Sequence[str] | None = None,
        *,
        subset_chance: float = ARMOR_ARB_LOOP_SUBSET_CHANCE,
        subset_min_items: int = ARMOR_ARB_LOOP_SUBSET_MIN_ITEMS,
        subset_max_items: int | None = ARMOR_ARB_LOOP_SUBSET_MAX_ITEMS,
        rng: random.Random | None = None,
    ) -> None:
        raw = tuple(catalog) if catalog is not None else ARMOR_ARB_SEARCH_QUERIES
        if not raw:
            raise ValueError("pass planner needs at least one catalog query")
        if not 0.0 <= subset_chance <= 1.0:
            raise ValueError("subset_chance must be in [0, 1]")
        if subset_min_items < 1:
            raise ValueError("subset_min_items must be >= 1")

        self._catalog = tuple(str(q).strip() for q in raw if str(q).strip())
        if not self._catalog:
            raise ValueError("pass planner catalog is empty after stripping")

        catalog_len = len(self._catalog)
        # Cap "partial" so a subset pass is actually smaller than the full set
        # when the catalog has more than one item.
        default_max = max(1, catalog_len - 1) if catalog_len > 1 else 1
        resolved_max = (
            default_max if subset_max_items is None else int(subset_max_items)
        )
        resolved_max = max(1, min(resolved_max, catalog_len))
        resolved_min = min(int(subset_min_items), resolved_max)

        self._subset_chance = float(subset_chance)
        self._subset_min = resolved_min
        self._subset_max = resolved_max
        self._rng = rng or random.Random()

    @property
    def catalog(self) -> tuple[str, ...]:
        """Full item list the overnight loop draws from."""
        return self._catalog

    @property
    def subset_chance(self) -> float:
        """Probability that a planned pass uses a partial item list."""
        return self._subset_chance

    @property
    def subset_min_items(self) -> int:
        """Smallest allowed subset size on a partial pass."""
        return self._subset_min

    @property
    def subset_max_items(self) -> int:
        """Largest allowed subset size on a partial pass."""
        return self._subset_max

    def plan(self) -> tuple[str, ...]:
        """
        Shuffle the catalog; sometimes return only a random subset.

        Casual: scramble order, and maybe only check a couple pieces.
        Always returns at least one query. Subset size is uniform in
        ``[subset_min, subset_max]`` when the subset coin-flip hits; otherwise
        the full catalog is shuffled and returned.
        """
        pool = list(self._catalog)
        self._rng.shuffle(pool)

        # Most passes still cover everything — just in a different order.
        if len(pool) == 1 or self._rng.random() >= self._subset_chance:
            return tuple(pool)

        count = self._rng.randint(self._subset_min, self._subset_max)
        # shuffle already randomized order; take the first `count` entries.
        return tuple(pool[:count])
