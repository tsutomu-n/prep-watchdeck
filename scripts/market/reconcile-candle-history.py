"""Compare saved v1/v2 candle ledgers locally; exit zero certifies comparison only."""

from prep_watchdeck_market.candle_gap_reconciliation import main

if __name__ == "__main__":
    raise SystemExit(main())
