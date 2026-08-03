declare global {
  namespace App {
    interface PageData {
      snapshot?: import("$lib/generated/scanner-snapshot").PrepWatchdeckScannerSnapshot;
      error?: string;
    }
  }
}

export {};
