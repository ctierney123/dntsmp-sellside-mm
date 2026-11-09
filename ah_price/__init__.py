"""Public ah_price package exports for tests and future bot modules."""

from __future__ import annotations

__all__ = [
    "AhPriceTestOrchestrator",
    "ArmorArbLoopCoordinator",
    "ArmorArbManager",
    "BalanceGuardManager",
    "BuyConfirmDetector",
    "PriceCompareManager",
    "SellOrderManager",
    "SellPriceCalculator",
    "SlotGridManager",
    "TooltipPriceReader",
    "UndercutDetector",
]


def __getattr__(name: str):
    """
    Lazy-load heavy modules so `import ah_price` stays light.

    Casual: only pull OCR / input code when you actually ask for it.
    """
    if name == "AhPriceTestOrchestrator":
        from ah_price.cli.orchestrator import AhPriceTestOrchestrator

        return AhPriceTestOrchestrator
    if name == "ArmorArbLoopCoordinator":
        from ah_price.armor_arb.loop_coordinator import ArmorArbLoopCoordinator

        return ArmorArbLoopCoordinator
    if name == "ArmorArbManager":
        from ah_price.armor_arb.manager import ArmorArbManager

        return ArmorArbManager
    if name == "BalanceGuardManager":
        from ah_price.guards.balance_guard_manager import BalanceGuardManager

        return BalanceGuardManager
    if name == "BuyConfirmDetector":
        from ah_price.automation.buy_confirm_detector import BuyConfirmDetector

        return BuyConfirmDetector
    if name == "PriceCompareManager":
        from ah_price.scan.price_compare_manager import PriceCompareManager

        return PriceCompareManager
    if name == "SellOrderManager":
        from ah_price.automation.sell_order_manager import SellOrderManager

        return SellOrderManager
    if name == "SellPriceCalculator":
        from ah_price.pricing.sell_price_calculator import SellPriceCalculator

        return SellPriceCalculator
    if name == "SlotGridManager":
        from ah_price.scan.slot_grid_manager import SlotGridManager

        return SlotGridManager
    if name == "TooltipPriceReader":
        from ah_price.tooltip.tooltip_price_reader import TooltipPriceReader

        return TooltipPriceReader
    if name == "UndercutDetector":
        from ah_price.pricing.undercut_detector import UndercutDetector

        return UndercutDetector
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
