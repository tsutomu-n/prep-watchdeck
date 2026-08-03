from __future__ import annotations

import re

SAFE_PUBLIC_SYMBOL = re.compile(r"^[A-Z0-9_-]+$")


def is_safe_public_symbol(symbol: str) -> bool:
    return SAFE_PUBLIC_SYMBOL.fullmatch(symbol) is not None
