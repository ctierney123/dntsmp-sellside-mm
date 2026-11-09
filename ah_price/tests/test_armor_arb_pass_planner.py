"""
Unit tests for overnight pass shuffle / subset planning.

Casual: prove we scramble order and sometimes drop items.
"""

from __future__ import annotations

import random
import unittest
from unittest.mock import MagicMock, call, patch

from ah_price.armor_arb.loop_coordinator import ArmorArbLoopCoordinator
from ah_price.armor_arb.pass_planner import ArmorArbPassPlanner


class ArmorArbPassPlannerTests(unittest.TestCase):
    """Planner should shuffle and optionally subset the catalog."""

    def test_full_pass_is_shuffled_permutation(self) -> None:
        catalog = ("a", "b", "c", "d")
        # Force the non-subset branch; seed still shuffles.
        planner = ArmorArbPassPlanner(
            catalog,
            subset_chance=0.0,
            rng=random.Random(7),
        )
        planned = planner.plan()
        self.assertEqual(sorted(planned), sorted(catalog))
        self.assertEqual(len(planned), len(catalog))
        # With this seed the shuffle is not identity.
        self.assertNotEqual(planned, catalog)

    def test_subset_pass_returns_partial_unique_items(self) -> None:
        catalog = ("a", "b", "c", "d", "e", "f")
        planner = ArmorArbPassPlanner(
            catalog,
            subset_chance=1.0,
            subset_min_items=2,
            subset_max_items=3,
            rng=random.Random(3),
        )
        planned = planner.plan()
        self.assertTrue(2 <= len(planned) <= 3)
        self.assertEqual(len(planned), len(set(planned)))
        self.assertTrue(set(planned).issubset(set(catalog)))

    def test_subset_max_defaults_below_full_catalog(self) -> None:
        planner = ArmorArbPassPlanner(
            ("a", "b", "c", "d"),
            subset_chance=1.0,
            subset_min_items=1,
            subset_max_items=None,
            rng=random.Random(1),
        )
        self.assertEqual(planner.subset_max_items, 3)
        planned = planner.plan()
        self.assertLess(len(planned), 4)


class ArmorArbLoopRecheckTests(unittest.TestCase):
    """Coordinator should re-scan purchased queries before sleeping."""

    def test_bought_queries_preserves_order_and_uniques(self) -> None:
        summary = {
            "items": [
                {"query": "/ah a", "purchased": True},
                {"query": "/ah b", "purchased": False},
                {"query": "/ah a", "purchased": True},
                {"query": "/ah c", "purchased": True},
            ]
        }
        bought = ArmorArbLoopCoordinator._bought_queries(summary)
        self.assertEqual(bought, ("/ah a", "/ah c"))

    def test_recheck_runs_only_bought_queries_without_balance(self) -> None:
        arb = MagicMock()
        arb.run_pass.return_value = {
            "items": [],
            "purchase_count": 0,
            "sell_count": 0,
            "queries": ["/ah a"],
        }
        coordinator = ArmorArbLoopCoordinator(
            arb_manager=arb,
            balance_guard=MagicMock(),
            pass_planner=ArmorArbPassPlanner(
                ("a", "b"),
                subset_chance=0.0,
                rng=random.Random(0),
            ),
            recheck_bought=True,
            rng=random.Random(0),
        )
        parent_summary = {
            "items": [
                {"query": "/ah a", "purchased": True},
                {"query": "/ah b", "purchased": False},
            ],
            "purchase_count": 1,
        }
        result = coordinator._maybe_recheck_bought(arb, parent_summary)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["kind"], "recheck_bought")
        arb.run_pass.assert_called_once_with(
            probe_escape=True,
            queries=("/ah a",),
            check_balance=False,
            label="recheck after pass 0",
        )

    def test_recheck_skipped_when_no_buys(self) -> None:
        arb = MagicMock()
        coordinator = ArmorArbLoopCoordinator(
            arb_manager=arb,
            balance_guard=MagicMock(),
            recheck_bought=True,
            rng=random.Random(0),
        )
        result = coordinator._maybe_recheck_bought(
            arb,
            {"items": [{"query": "/ah a", "purchased": False}]},
        )
        self.assertIsNone(result)
        arb.run_pass.assert_not_called()

    def test_pass_had_no_purchases_uses_purchase_count(self) -> None:
        self.assertTrue(
            ArmorArbLoopCoordinator._pass_had_no_purchases(
                {"purchase_count": 0, "items": [{"purchased": True}]}
            )
        )
        self.assertFalse(
            ArmorArbLoopCoordinator._pass_had_no_purchases(
                {"purchase_count": 2, "items": []}
            )
        )

    def test_long_pause_skipped_after_purchases(self) -> None:
        """Buys must not roll the 2–5 min coffee break — only dry passes."""
        coordinator = ArmorArbLoopCoordinator(
            arb_manager=MagicMock(),
            balance_guard=MagicMock(),
            # Force the long-pause coin flip to always "win" if it runs.
            long_pause_chance=1.0,
            long_pause_min_seconds=120.0,
            long_pause_max_seconds=120.0,
            sleep_min_seconds=0.0,
            sleep_max_seconds=0.0,
            rng=random.Random(0),
        )
        with patch(
            "ah_price.armor_arb.loop_coordinator.time.sleep"
        ) as sleep_mock:
            coordinator._inter_pass_sleep(allow_long_pause=False)
        # Base sleep only (0s) — no second long-pause sleep call.
        sleep_mock.assert_called_once_with(0.0)

    def test_long_pause_may_run_after_full_skips(self) -> None:
        coordinator = ArmorArbLoopCoordinator(
            arb_manager=MagicMock(),
            balance_guard=MagicMock(),
            long_pause_chance=1.0,
            long_pause_min_seconds=120.0,
            long_pause_max_seconds=120.0,
            sleep_min_seconds=0.0,
            sleep_max_seconds=0.0,
            rng=random.Random(0),
        )
        with patch(
            "ah_price.armor_arb.loop_coordinator.time.sleep"
        ) as sleep_mock:
            coordinator._inter_pass_sleep(allow_long_pause=True)
        self.assertEqual(
            sleep_mock.call_args_list,
            [call(0.0), call(120.0)],
        )

    def test_no_sleep_skips_base_and_long_pause(self) -> None:
        """--no-sleep must not call time.sleep at all between passes."""
        coordinator = ArmorArbLoopCoordinator(
            arb_manager=MagicMock(),
            balance_guard=MagicMock(),
            # Even with a guaranteed long-pause roll, no_sleep wins.
            long_pause_chance=1.0,
            long_pause_min_seconds=120.0,
            long_pause_max_seconds=120.0,
            sleep_min_seconds=5.0,
            sleep_max_seconds=60.0,
            no_sleep=True,
            rng=random.Random(0),
        )
        with patch(
            "ah_price.armor_arb.loop_coordinator.time.sleep"
        ) as sleep_mock:
            coordinator._inter_pass_sleep(allow_long_pause=True)
        sleep_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
