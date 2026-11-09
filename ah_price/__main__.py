#!/usr/bin/env python3
"""
AH tooltip price reader — test CLI.

Modes:
  --setup          calibrate hover point + tooltip region (interactive)
  --setup-hover    calibrate ITEM_HOVER_XY only
  --setup-region   calibrate TOOLTIP_REGION only
  --setup-slots        calibrate first-row slot spacing (slot 0 + slot 1)
  --setup-buy-confirm  calibrate Yes click + Yes template for buy popup
  --vision-only        OCR the tooltip under the mouse (no typing)
  --compare            scan first N slots and check if slot 0 is cheapest
  --compare-only       same as --compare but skip /ah search (AH already open)
  --armor-arb          search netherite armor set, compare, buy+sell undercuts
  --armor-arb-loop     overnight loop: shuffled/partial passes + recheck + floor
  --no-sleep           with --armor-arb-loop: skip inter-pass delays (testing)
  --spread-check       market making: /ah + /order slot-0 bid/ask spread
  --test-balance       OCR the scoreboard balance (no AH / no input)
  (default)            T → type /ah query → hover → OCR → print price
"""

from __future__ import annotations

import argparse
import logging
import sys

from ah_price.armor_arb.loop_coordinator import ArmorArbLoopCoordinator
from ah_price.armor_arb.manager import ArmorArbManager
from ah_price.guards.balance_guard_manager import BalanceFloorHalt
from ah_price.guards.parse_failure_guard_manager import ParseFailureHalt
from ah_price.calibration.buy_confirm_calibrator import BuyConfirmCalibrator
from ah_price.config import (
    AH_SEARCH_QUERY,
    ARMOR_ARB_SEARCH_QUERIES,
    FOCUS_COUNTDOWN_SECONDS,
    MARKET_MAKING_DEFAULT_ITEM,
    SLOT_COUNT,
)
from ah_price.scan.price_compare_manager import PriceCompareManager
from ah_price.calibration.setup_calibrator import SetupCalibrator
from ah_price.calibration.slot_spacing_calibrator import SlotSpacingCalibrator
from ah_price.cli.orchestrator import AhPriceTestOrchestrator


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def main() -> int:
    """
    CLI entry for setup + AH price test runs.

    Casual: calibrate coords, or press go and print an item price.
    """
    parser = argparse.ArgumentParser(
        description="AH item price test (chat + tooltip OCR)."
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Calibrate ITEM_HOVER_XY and TOOLTIP_REGION interactively.",
    )
    parser.add_argument(
        "--setup-hover",
        action="store_true",
        help="Calibrate ITEM_HOVER_XY only.",
    )
    parser.add_argument(
        "--setup-region",
        action="store_true",
        help="Calibrate TOOLTIP_REGION only (two corners).",
    )
    parser.add_argument(
        "--setup-slots",
        action="store_true",
        help="Calibrate first-row slot spacing (lock slot 0, then slot 1).",
    )
    parser.add_argument(
        "--setup-buy-confirm",
        action="store_true",
        help=(
            "Calibrate high-price buy confirm: Yes click point, Yes text "
            "region, and templates/buy_confirm_yes.png."
        ),
    )
    parser.add_argument(
        "--vision-only",
        action="store_true",
        help="Skip T/typing; just OCR the currently hovered tooltip.",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Search + scan first-row slots; report if leftmost is cheapest.",
    )
    parser.add_argument(
        "--compare-only",
        action="store_true",
        help="Scan first-row slots only (AH already open; no chat/search).",
    )
    parser.add_argument(
        "--armor-arb",
        action="store_true",
        help=(
            "Search netherite chestplate/leggings/helm/boots/sword/ingot, "
            "compare each first row, buy undercuts (199k-2.5m below median), "
            "then immediately /ah sell at competitive_ref - 100k."
        ),
    )
    parser.add_argument(
        "--armor-arb-loop",
        action="store_true",
        help=(
            "Overnight loop: shuffled/partial armor passes, immediate "
            "recheck after buys, 5-60s sleeps, ~10%% chance of 2-5min "
            "pauses, a 30m balance floor (wait 5m / halt after 3 "
            "failed checks), and halt on repeated tooltip parse fails "
            "(one one-off miss allowed)."
        ),
    )
    parser.add_argument(
        "--no-sleep",
        action="store_true",
        help=(
            "With --armor-arb-loop: skip inter-pass 5-60s sleeps and the "
            "random 2-5min long pauses (back-to-back passes for testing). "
            "Default keeps normal human-ish delays."
        ),
    )
    parser.add_argument(
        "--spread-check",
        action="store_true",
        help=(
            "Market-making spread check: paste /ah <item> (ask) + /order "
            "<item> (bid), OCR slot 0 on each book, print ask-bid spread. "
            "Uses --query as the item name (default: enchanted golden apple)."
        ),
    )
    parser.add_argument(
        "--test-balance",
        action="store_true",
        help=(
            "Smoke-test HUD balance OCR (CAPTURE_REGION). No chat/mouse. "
            "Leave AH closed so the scoreboard is visible. Writes "
            "ah_balance_read_debug.png."
        ),
    )
    parser.add_argument(
        "--balance-repeats",
        type=int,
        default=1,
        help="With --test-balance, how many reads to attempt (default: 1).",
    )
    parser.add_argument(
        "--slots",
        type=int,
        default=SLOT_COUNT,
        help=f"How many first-row slots to scan (default: {SLOT_COUNT}).",
    )
    parser.add_argument(
        "--query",
        default=None,
        help=(
            f"Chat command / item name (default without --spread-check: "
            f"{AH_SEARCH_QUERY!r}; with --spread-check: "
            f"{MARKET_MAKING_DEFAULT_ITEM!r}). "
            "A leading / is added if missing; bare item names get /ah "
            "prepended (except --spread-check, which builds /ah + /order)."
        ),
    )
    parser.add_argument(
        "--countdown",
        type=float,
        default=FOCUS_COUNTDOWN_SECONDS,
        help="Seconds to click into Minecraft before input starts.",
    )
    parser.add_argument(
        "--no-debug",
        action="store_true",
        help="Do not write ah_tooltip_debug.png / ah_price_strip_debug.png.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Debug logging.",
    )
    args = parser.parse_args()
    _configure_logging(args.verbose)

    # Default --query depends on mode: spread-check wants a bare item name.
    if args.query is None:
        args.query = (
            MARKET_MAKING_DEFAULT_ITEM if args.spread_check else AH_SEARCH_QUERY
        )

    # Setup modes (no Minecraft input injection beyond reading mouse).
    if args.setup:
        SetupCalibrator().run_full_setup()
        return 0
    if args.setup_hover:
        SetupCalibrator().run_hover_setup()
        return 0
    if args.setup_region:
        SetupCalibrator().run_region_setup()
        return 0
    if args.setup_slots:
        SlotSpacingCalibrator(slot_count=args.slots).run()
        return 0
    if args.setup_buy_confirm:
        BuyConfirmCalibrator(countdown_seconds=args.countdown).run()
        return 0

    # Market-making: /ah ask + /order bid → slot-0 spread.
    if args.spread_check:
        from ah_price.market_making.spread_check_manager import SpreadCheckManager

        checker = SpreadCheckManager(
            countdown_seconds=args.countdown,
            save_debug=not args.no_debug,
        )
        try:
            checker.run(item_name=args.query)
            return 0
        except KeyboardInterrupt:
            print("\nStopped.")
            return 0
        except Exception as exc:
            logging.getLogger(__name__).error("%s", exc)
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        finally:
            checker.close()

    # Multi-slot price compare (fast hover loop).
    if args.compare or args.compare_only:
        compare = PriceCompareManager(
            slot_count=args.slots,
            countdown_seconds=args.countdown,
            save_debug=not args.no_debug,
            query=args.query,
        )
        try:
            if args.compare_only:
                compare.run_compare_only()
            else:
                compare.run_full(query=args.query)
            return 0
        except KeyboardInterrupt:
            print("\nStopped.")
            return 0
        except Exception as exc:
            logging.getLogger(__name__).error("%s", exc)
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        finally:
            compare.close()

    # Passive scoreboard balance smoke test (no AH input).
    if args.test_balance:
        from ah_price.cli.balance_read_test_manager import BalanceReadTestManager

        tester = BalanceReadTestManager(
            countdown_seconds=args.countdown,
            repeats=max(1, args.balance_repeats),
            save_debug=not args.no_debug,
        )
        try:
            results = tester.run()
            return 0 if all(row.get("ok") for row in results) else 1
        except KeyboardInterrupt:
            print("\nStopped.")
            return 0
        except Exception as exc:
            logging.getLogger(__name__).error("%s", exc)
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        finally:
            tester.close()

    # Overnight: repeat armor-arb with balance floor + random sleeps.
    if args.armor_arb_loop:
        loop = ArmorArbLoopCoordinator(
            countdown_seconds=args.countdown,
            no_sleep=args.no_sleep,
        )
        try:
            result = loop.run()
            if result.get("halted_reason"):
                print(f"Halted: {result['halted_reason']}", file=sys.stderr)
                return 2
            return 0
        except KeyboardInterrupt:
            print("\nStopped.")
            return 0
        except BalanceFloorHalt as exc:
            logging.getLogger(__name__).error("%s", exc)
            print(f"HALT: {exc}", file=sys.stderr)
            return 2
        except ParseFailureHalt as exc:
            logging.getLogger(__name__).error("%s", exc)
            print(f"HALT: {exc}", file=sys.stderr)
            return 2
        except Exception as exc:
            logging.getLogger(__name__).error("%s", exc)
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    # Netherite armor set: search → compare → buy → immediate sell.
    if args.armor_arb:
        from ah_price.guards.balance_guard_manager import BalanceGuardManager

        arb = ArmorArbManager(
            queries=ARMOR_ARB_SEARCH_QUERIES,
            slot_count=args.slots,
            countdown_seconds=args.countdown,
            save_debug=not args.no_debug,
            balance_guard=BalanceGuardManager(),
        )
        try:
            arb.run()
            return 0
        except KeyboardInterrupt:
            print("\nStopped.")
            return 0
        except BalanceFloorHalt as exc:
            logging.getLogger(__name__).error("%s", exc)
            print(f"HALT: {exc}", file=sys.stderr)
            return 2
        except Exception as exc:
            logging.getLogger(__name__).error("%s", exc)
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        finally:
            arb.close()

    orch = AhPriceTestOrchestrator(
        query=args.query,
        countdown_seconds=args.countdown,
        save_debug=not args.no_debug,
    )
    try:
        if args.vision_only:
            orch.run_vision_only()
        else:
            orch.run_full()
        return 0
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0
    except Exception as exc:
        logging.getLogger(__name__).error("%s", exc)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        orch.close()


if __name__ == "__main__":
    sys.exit(main())
