type SymbolRow = {
  symbol: string;
};

export type DashboardSelection<Row extends SymbolRow> = {
  selectedSymbol: string | null;
  row: Row | null;
  missing: boolean;
};

export type DraftSymbolValidation =
  | { ok: true; symbol: string }
  | {
      ok: false;
      reason: "selection-unconfirmed" | "symbol-mismatch" | "symbol-missing";
    };

export function resolveDashboardSelection<Row extends SymbolRow>(
  selectedSymbol: string | null,
  rows: Row[]
): DashboardSelection<Row> {
  if (selectedSymbol === null) {
    const first = rows[0] ?? null;
    return {
      selectedSymbol: first?.symbol ?? null,
      row: first,
      missing: false
    };
  }

  const row = rows.find((candidate) => candidate.symbol === selectedSymbol) ?? null;
  return { selectedSymbol, row, missing: row === null };
}

export function validateDraftSymbol({
  draftSymbol,
  displayedSymbol,
  availableSymbols
}: {
  draftSymbol: string | null;
  displayedSymbol: string | null;
  availableSymbols: string[];
}): DraftSymbolValidation {
  if (!draftSymbol || !displayedSymbol) {
    return { ok: false, reason: "selection-unconfirmed" };
  }
  if (draftSymbol !== displayedSymbol) {
    return { ok: false, reason: "symbol-mismatch" };
  }
  if (!availableSymbols.includes(draftSymbol)) {
    return { ok: false, reason: "symbol-missing" };
  }
  return { ok: true, symbol: draftSymbol };
}
