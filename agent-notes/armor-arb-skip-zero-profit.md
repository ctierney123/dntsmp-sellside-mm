# Armor arb — skip buy when sell == buy

**Date:** 2026-07-09  
**Symptom:** Live summary like  
`BUY /ah netherite sword: slot 0 $7.6M (-200,000) → sell 7.6m`  
— bought an in-band undercut, then relisted at the same coins (zero edge).

**Root cause:** Buy gate only checked median discount (199k–1.5m). Sell price is `competitive_ref - 100k`. A 7.6m listing with next real book price 7.7m qualifies as a buy (200k under median) but sells at 7.6m.

**Fix:** Before clicking buy, `SellPriceCalculator.would_profit` / `SellOrderManager.would_profit_after_buy` requires `planned_sell > buy_coins`. Equal or lower → skip (`buy_equals_sell` / `sell_not_above_buy` / `no_sell_price`). Planned decision is reused for the actual `/ah sell` so the gate and list price cannot disagree.
