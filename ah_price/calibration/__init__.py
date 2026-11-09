"""
Interactive calibrators for hover points, slots, and buy-confirm Yes.

Casual: one-time setup wizards that write coords into config.
"""

from __future__ import annotations

from ah_price.calibration.buy_confirm_calibrator import BuyConfirmCalibrator
from ah_price.calibration.setup_calibrator import SetupCalibrator
from ah_price.calibration.slot_spacing_calibrator import SlotSpacingCalibrator

__all__ = [
    "BuyConfirmCalibrator",
    "SetupCalibrator",
    "SlotSpacingCalibrator",
]
