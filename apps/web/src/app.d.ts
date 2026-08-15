declare global {
  namespace App {
    interface PageData {
      market?: import("$lib/server/market-artifact-repository").MarketArtifactBundle;
      marketError?: string;
    }
  }
}

export {};
