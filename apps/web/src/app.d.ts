declare global {
  namespace App {
    interface PageState {
      referenceDetail?: boolean;
      nativeDetail?: boolean;
    }
    interface PageData {
      market?: import("$lib/server/market-artifact-repository").MarketArtifactBundle;
      marketError?: string;
    }
  }
}

export {};
