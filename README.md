# dntsmp-sellside-mm

DonutSMP sell-side market maker (`donutsmp-sellside-marketmaker`).

A 96-hour run of this loop made about $500M in DonutSMP balance.

If you visualize the market as level 2 order data, this bot analyzes the asks and marks fair value as the median of the visible ladder, lifts the top level when it trades through that median, and supplies one-lot liquidity by posting 100k inside the next competitive ask.

It makes markets in netherite on the player auction house. It works six books: chestplate, leggings, helm, boots, sword, and ingot. In each book it reads the visible asks, marks a fair value from the prices behind the touch, and uses that mark to decide when to take inventory and where to offer it.

It market-makes by taking a dislocated ask and replacing it with its own. When the cheapest listing sits well under the rest of the row, it buys that one lot. It then lists the same item 100k under the next ask that still belongs with the market, stepping over other cheap outliers so the new offer joins the cluster. On a row like 7.0, 7.1, 7.7 it buys the 7.0 and rests 7.6. A buyer can lift that new ask. The stale offer is out of the book, and a tighter price is in its place.

That resting ask is the liquidity. The bot is the seller inside the touch, size one, until someone takes the quote. Inventory sits in hotbar slot 1, and the next quote waits until that ask is up.

Fair value is a median of the asks on screen, so the cheap lot it wants to buy does not pull the mark down. On a thick row, where one price repeats, it uses the whole ladder. On a thin staircase, where almost every price is unique, it uses only the cheapest few, which is the depth it can actually sell into.

Prices, cash, and the confirm dialog come from template matching on Minecraft's bitmap font. Orders go out as keystrokes through `pyautogui`. The edge has to be wide, because the click is slow.

## Table of Contents

- [Background](#background)
- [Install](#install)
- [Usage](#usage)
- [Pricing](#pricing)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)

## Background

The auction house has no API. `/ah <item>` is the ask book, cheapest first, and you can see nine listings. Several slots often print the same price, and that repeat count is the only size on the level. `/order <item>` is the bid book. The live loop trades asks only. If you want the quoted spread, `--spread-check` reads the best ask minus the best bid. The default name there is enchanted golden apple.

The trade is a slow take-and-join. A lot will sit hundreds of thousands under the cluster behind it, long enough to lift it and repost with the market. You mark that cluster with a median, so the cheap lots you want to buy do not pull fair value down with them. When the row is a thin staircase and no price repeats more than twice, the median of the whole ladder sits too far up the curve. You then mark only the cheapest four asks, which is the part of the book you can sell into.

A pass walks netherite chestplate, leggings, helm, boots, sword, and ingot. Bands, ceilings, and waits live in `ah_price/config.py`.

## Install

You need [Python](https://www.python.org/) 3.11 or newer. From the repo root:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Dependencies

Run this on Windows, with Minecraft in the foreground. Set GUI scale to a whole number (2, 3, or 4). A fractional scale blurs the font, and the templates stop matching. Capture boxes are absolute pixels, checked around 1920×1080. If you change resolution or GUI scale, calibrate again.

`requirements.txt` pulls in the screen capture and `pyautogui`. You do not install Tesseract. The optional OCR fallback is off.

## Usage

Click into Minecraft during the countdown, and leave that window in front.

This scans until you stop it, cash breaks the floor, or the price reads stop being trustworthy:

```powershell
python -m ah_price --armor-arb-loop
```

Each pass shuffles the six names. About 35% of passes draw a shorter subset, at least two names. If you lifted something, those names are scanned once more before the wait. The gap between passes is a random 5–60 seconds. After a pass with no takes, a 2–5 minute pause is added about 10% of the time. `--no-sleep` removes both waits. `python -m ah_price --armor-arb` runs the same pricing once, in catalog order.

After each pass you get session totals and a trailing 15-minute window: takes per pass, mean posted profit, and mean margin. Profit is the exit ask minus the purchase, marked when `/ah sell` is accepted. It assumes that ask later fills at the posted price. Margin is that profit divided by the purchase.

Every ladder, takes and skips, is appended to `logs/armor_arb_order_books/` as JSONL. Takes stay in memory until the session passes 10, then they are written under `logs/armor_arb_purchases/`. Those files stay on the machine that runs the loop.

Calibrate before the first session. The loop will click the wrong pixels otherwise.

### Calibrate

With the scoreboard on screen:

```powershell
python -m screen_reader --calibrate
```

That writes `calibration_full.png` and `calibration_crop.png`. Those screenshots stay on the machine. Paste the username and balance rectangle into `CAPTURE_REGION` in `screen_reader/config.py`. Keep that box off the tooltip.

Build the glyph templates from a live crop. Both strings have to match the HUD exactly, and the balance should contain a `0`:

```powershell
python -m screen_reader --build-atlas PlayerName "$ 52.1M"
```

Files land in `templates/`. Name glyphs stay on the machine. This repo keeps the balance digits, the money mark, and the confirm button. Startup stops if `$0123456789.` is incomplete. A missing `0.png` makes every zero read as another digit.

Then lock the book:

```powershell
python -m ah_price --setup
python -m ah_price --setup-slots
python -m ah_price --setup-buy-confirm
```

Paste the printed values into `ah_price/config.py`. `--setup` is the first listing and the tooltip box. `--setup-slots` is the pixel step from level 0 to level 1. `--setup-buy-confirm` is the Yes button on the expensive-purchase dialog, and it writes `templates/buy_confirm_yes.png`. The slot preview should sit on each icon across the first row.

### CLI

| Command | What you get |
| --- | --- |
| `python -m screen_reader` | Scoreboard cash, on a timer. No clicks. |
| `python -m ah_price --compare --query "netherite chestplate"` | The top nine asks. No order. |
| `python -m ah_price --compare-only` | The same snapshot when the book is already open. |
| `python -m ah_price` | One search, one tooltip, one price. |
| `python -m ah_price --vision-only` | The tooltip under the cursor. |
| `python -m ah_price --spread-check` | Best ask minus best bid. |
| `python -m ah_price --test-balance` | One cash read. |

## Pricing

You buy the cheapest ask when `fair − ask` is inside 299k–4.5m and the planned exit is strictly above the purchase. A planned sell that equals the buy is skipped. You take one lot per name. A tie goes to the leftmost slot.

299k is the minimum gross edge. You give 100k back to post inside the touch, and the remainder has to survive a slow click and a tick of OCR noise. 4.5m is the cap. A wider print is dropped as a bad read or the wrong item.

Fair value depends on the shape of the row:

- Thick book. Some price appears more than twice. You take the median of every priced level.
- Thin book. Nothing repeats more than twice, as in 5.1, 5.2, 5.3, 5.4. You take the median of the cheapest four asks.

You can act before the full ladder is in. After levels 0–2, level 0 is liftable when it is strictly through both neighbors, at least 299k under the next ask, and still inside the band versus the median of those two neighbors. The exit is then priced off that shorter book.

The exit quote is the first remaining ask that is not itself 299k or more through fair, minus 100k. On a book like `7.0, 7.1, 7.7…` you step over 7.1 and post 7.6.

A netherite ingot above 10.1m at level 0, or a netherite sword above 7.1m, skips the name. Those prints sit outside the region where the book usually clears.

### Limits

Cash is read at the start of each pass, with the auction UI closed. Under 30m you wait five minutes and read again. Three failures in a row stop the session. Cash is not re-read while a menu covers the scoreboard.

One failed parse on levels 0–4 is allowed for the session. The next counted failure stops it. Misses on level 5 and deeper do not count, because tall enchant tooltips clip those lines.

Your own asks are remembered for six hours, as price plus a tooltip fingerprint (normalized correlation at least 0.92). A match is left alone, so the click cannot open the collect screen. A match on level 0 drops the name. A match further down still allows the next in-band ask. A large take that raises "Are you sure?" confirms Yes when that template matches.

## Troubleshooting

- **Wrong digits.** Rebuild the atlas. Confirm an integer GUI scale, and confirm `0.png` is present.
- **"Expected 2 HUD text lines."** Grow `CAPTURE_REGION` until the name and the balance both fit.
- **Empty tooltips.** The tip was not on screen yet. Raise `COMPARE_AFTER_HOVER_DELAY_SECONDS` toward `0.07`–`0.08`. If the dollar sign is missed, try `AH_SCALE_FACTOR` of 3 or 4.
- **A truncated `/ah`.** The previous menu was still closing. Raise `AFTER_ESCAPE_DELAY_SECONDS`.
- **Cash read fails at the start of a pass.** The book was still covering the scoreboard. A skip ends with Escape so the next read can see the HUD.

## Contributing

Open an issue or a pull request.

Run the tests before you treat a pricing change as done:

```powershell
python -m unittest discover -s ah_price -p "test_*.py" -v
python -m unittest discover -s screen_reader -p "test_*.py" -v
```

## License

UNLICENSED

No license file is included. The repository owner reserves all rights.
