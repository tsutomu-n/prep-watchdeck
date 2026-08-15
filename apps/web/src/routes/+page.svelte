<script lang="ts">
  import { onMount, untrack } from "svelte";
  import type { PageProps } from "./$types";
  import FontSelector from "$lib/components/FontSelector.svelte";
  import ThemeSelector from "$lib/components/ThemeSelector.svelte";
  import MarketPastNotesPanel from "$lib/components/universe/MarketPastNotesPanel.svelte";
  import UniverseChart from "$lib/components/universe/UniverseChart.svelte";
  import type { SelectedInstrumentArtifact } from "$lib/generated/selected-market";
  import type { UniverseInstrumentArtifact } from "$lib/generated/universe-snapshot";
  import type { MarketArtifactBundle } from "$lib/server/market-artifact-repository";
  import {
    filterAndSortUniverse,
    formatCompact,
    formatFinite,
    formatRate,
    formatTimestamp,
    type CoverageFilter,
    type QualityFilter,
    type VenueFilter
  } from "$lib/market/universe-view";

  const artifactPollMs = 5_000;
  const selectionDebounceMs = 500;
  const heartbeatMs = 5 * 60 * 1_000;

  let { data }: PageProps = $props();
  const initialMarket = untrack(() =>
    "market" in data ? (data.market as MarketArtifactBundle) : null
  );
  const initialError = untrack(() =>
    "marketError" in data ? String(data.marketError) : null
  );
  let market = $state<MarketArtifactBundle | null>(initialMarket);
  let marketError = $state<string | null>(initialError);
  let refreshError = $state<string | null>(null);
  let refreshing = false;
  let search = $state("");
  let venue = $state<VenueFilter>("all");
  let coverage = $state<CoverageFilter>("all");
  let quality = $state<QualityFilter>("all");
  let selectedVenueInstrumentId = $state<string | null>(initialSelection(initialMarket));
  let selectionMessage = $state<string | null>(null);
  let selectionError = $state<string | null>(null);

  let items = $derived(market?.universe.items ?? []);
  let visibleItems = $derived(
    filterAndSortUniverse(items, { search, venue, coverage, quality })
  );
  let selectedInstrument = $derived(
    items.find((item) => item.venueInstrumentId === selectedVenueInstrumentId) ?? null
  );
  let selectedGroupId = $derived(selectedInstrument?.groupId ?? null);
  let selectedPayload = $derived(
    market?.selected.selection?.groupId === selectedGroupId &&
      market.selected.selection.primaryVenueInstrumentId === selectedVenueInstrumentId
      ? market.selected.selection
      : null
  );
  let chartMatchesSelection = $derived(
    market?.chart.venueInstrumentId === selectedVenueInstrumentId
  );
  let groupVenueCount = $derived(
    selectedGroupId
      ? new Set(items.filter((item) => item.groupId === selectedGroupId).map((item) => item.venue)).size
      : 1
  );

  onMount(() => {
    const timer = window.setInterval(() => void refreshArtifacts(), artifactPollMs);
    return () => window.clearInterval(timer);
  });

  $effect(() => {
    if (selectedVenueInstrumentId && selectedInstrument) return;
    selectedVenueInstrumentId = visibleItems[0]?.venueInstrumentId ?? items[0]?.venueInstrumentId ?? null;
  });

  $effect(() => {
    const groupId = selectedGroupId;
    const venueInstrumentId = selectedVenueInstrumentId;
    selectionMessage = null;
    selectionError = null;
    if (!groupId || !venueInstrumentId) return;

    const debounce = window.setTimeout(
      () => void postSelection(groupId, venueInstrumentId, false),
      selectionDebounceMs
    );
    const heartbeat = window.setInterval(
      () => void postSelection(groupId, venueInstrumentId, true),
      heartbeatMs
    );
    return () => {
      window.clearTimeout(debounce);
      window.clearInterval(heartbeat);
    };
  });

  async function refreshArtifacts() {
    if (refreshing || document.visibilityState === "hidden") return;
    refreshing = true;
    try {
      const response = await fetch("/api/market-data", { cache: "no-store" });
      if (!response.ok) throw new Error(await response.text());
      market = (await response.json()) as MarketArtifactBundle;
      marketError = null;
      refreshError = null;
    } catch (cause) {
      refreshError = cause instanceof Error ? cause.message : "最新データを取得できません";
    } finally {
      refreshing = false;
    }
  }

  async function postSelection(groupId: string, venueInstrumentId: string, heartbeat: boolean) {
    try {
      const response = await fetch("/api/selection", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ groupId, venueInstrumentId })
      });
      if (!response.ok) throw new Error(await response.text());
      if (selectedVenueInstrumentId === venueInstrumentId) {
        selectionError = null;
        selectionMessage = heartbeat ? "選択監視を継続しました" : "詳細データを要求しました";
      }
    } catch (cause) {
      if (selectedVenueInstrumentId === venueInstrumentId) {
        selectionError = cause instanceof Error ? cause.message : "選択を反映できません";
      }
    }
  }

  function selectInstrument(instrument: UniverseInstrumentArtifact) {
    selectedVenueInstrumentId = instrument.venueInstrumentId;
  }

  function depthRows(instrument: SelectedInstrumentArtifact) {
    return Array.from(
      { length: Math.max(instrument.bids.length, instrument.asks.length) },
      (_, index) => ({ bid: instrument.bids[index], ask: instrument.asks[index] })
    );
  }

  function qualityLabel(value: string) {
    return {
      ready: "正常",
      partial: "一部取得",
      unavailable: "取得不能",
      stale: "期限切れ"
    }[value] ?? value;
  }

  function selectionQualityReasons(instrument: SelectedInstrumentArtifact) {
    return instrument.qualityReasons.length > 0 ? instrument.qualityReasons.join(" / ") : "なし";
  }

  function initialSelection(bundle: MarketArtifactBundle | null) {
    if (!bundle) return null;
    const active = new Set(bundle.universe.items.filter((item) => item.active).map((item) => item.venueInstrumentId));
    const current = bundle.selected.selection?.primaryVenueInstrumentId;
    if (current && active.has(current)) return current;
    return filterAndSortUniverse(bundle.universe.items, {
      search: "",
      venue: "all",
      coverage: "all",
      quality: "all"
    })[0]?.venueInstrumentId ?? null;
  }
</script>

<svelte:head>
  <title>Perp Universe Explorer | Prep Watchdeck</title>
  <meta
    name="description"
    content="Bitget、Hyperliquid、Asterの暗号資産Perpを会場別に確認するローカル監視画面"
  />
</svelte:head>

<main class="universe-page">
  <header class="topbar">
    <div class="identity">
      <p>PREP WATCHDECK</p>
      <h1>Perp Universe Explorer</h1>
      <span>Bitget / Hyperliquid / Aster の公開データ監視。売買推奨ではありません。</span>
    </div>
    <div class="preferences" aria-label="表示設定">
      <ThemeSelector />
      <FontSelector />
    </div>
  </header>

  {#if marketError && !market}
    <section class="fatal-state" aria-labelledby="fatal-title">
      <h2 id="fatal-title">市場artifactを表示できません</h2>
      <p role="alert">{marketError}</p>
      <button type="button" onclick={() => window.location.reload()}>再読込</button>
    </section>
  {:else if market}
    <section class="status-strip" aria-label="データ状態">
      <div>
        <span>全体</span>
        <strong class:quality-risk={market.service.status !== "ready"}>
          {qualityLabel(market.service.status)}
        </strong>
      </div>
      <div>
        <span>Catalog</span>
        <strong class:quality-risk={market.service.catalog.status !== "ready"}>
          {qualityLabel(market.service.catalog.status)} / {formatFinite(market.service.catalog.ageSeconds, 0)}秒
        </strong>
      </div>
      <div>
        <span>L1</span>
        <strong class:quality-risk={market.service.l1.status !== "ready"}>
          {qualityLabel(market.service.l1.status)} / {formatFinite(market.service.l1.ageSeconds, 0)}秒
        </strong>
      </div>
      <div>
        <span>Universe</span>
        <strong>{items.length} instruments</strong>
      </div>
      <div>
        <span>生成</span>
        <strong>{formatTimestamp(market.universe.generatedAt)}</strong>
      </div>
    </section>

    {#if market.service.qualityReasons.length > 0 || market.universe.qualityReasons.length > 0}
      <p class="quality-banner" role="status">
        品質理由: {[...market.service.qualityReasons, ...market.universe.qualityReasons].join(" / ")}
      </p>
    {/if}
    {#if refreshError}
      <p class="quality-banner" role="alert">更新失敗。直前の検証済み表示を維持: {refreshError}</p>
    {/if}

    <div class="workspace">
      <section class="universe" aria-labelledby="universe-title">
        <div class="section-title">
          <div>
            <h2 id="universe-title">Instrument Universe</h2>
            <p>既定順: base asset → Venue。順位や売買方向を示しません。</p>
          </div>
          <strong>{visibleItems.length} / {items.length}</strong>
        </div>

        <div class="filters" aria-label="Universe絞り込み">
          <label class="search-control">
            <span>検索</span>
            <input bind:value={search} type="search" placeholder="BTC / BTCUSDT / venue id" />
          </label>
          <label>
            <span>Venue</span>
            <select bind:value={venue}>
              <option value="all">すべて</option>
              <option value="aster">Aster</option>
              <option value="bitget">Bitget</option>
              <option value="hyperliquid">Hyperliquid</option>
            </select>
          </label>
          <label>
            <span>Coverage</span>
            <select bind:value={coverage}>
              <option value="all">すべて</option>
              <option value="multi">2 Venue以上</option>
              <option value="single">単独instrument</option>
            </select>
          </label>
          <label>
            <span>品質</span>
            <select bind:value={quality}>
              <option value="all">すべて</option>
              <option value="ready">正常</option>
              <option value="partial">一部取得</option>
              <option value="stale">期限切れ</option>
              <option value="unavailable">取得不能</option>
            </select>
          </label>
        </div>

        <div class="table-scroll">
          <table>
            <caption class="sr-only">Perp instrument一覧</caption>
            <thead>
              <tr>
                <th scope="col">Instrument</th>
                <th scope="col">Mark</th>
                <th scope="col">Bid / Ask</th>
                <th scope="col">Funding / h</th>
                <th scope="col" class="optional-column">OI notional</th>
                <th scope="col" class="optional-column">24h volume</th>
                <th scope="col">品質 / age</th>
              </tr>
            </thead>
            <tbody>
              {#each visibleItems as item (item.venueInstrumentId)}
                <tr class:selected={item.venueInstrumentId === selectedVenueInstrumentId}>
                  <td>
                    <button
                      type="button"
                      class="instrument-select"
                      aria-current={item.venueInstrumentId === selectedVenueInstrumentId ? "true" : undefined}
                      aria-label={`${item.baseAsset} ${item.venue}を詳細表示`}
                      onclick={() => selectInstrument(item)}
                    >
                      <strong>{item.baseAsset}</strong>
                      <span>{item.venue} · {item.sourceSymbol}</span>
                    </button>
                  </td>
                  <td class="numeric">{formatFinite(item.markPrice)}</td>
                  <td class="numeric">
                    {formatFinite(item.bestBid)}<br />{formatFinite(item.bestAsk)}
                  </td>
                  <td class="numeric">{formatRate(item.fundingRatePerHour)}</td>
                  <td class="numeric optional-column">{formatCompact(item.openInterestNotional)}</td>
                  <td class="numeric optional-column">
                    {formatCompact(item.volume24hRaw)} {item.volume24hUnit ?? ""}
                  </td>
                  <td>
                    <span class:quality-risk={item.quality !== "ready"}>{qualityLabel(item.quality)}</span>
                    <small>{formatFinite(item.ageSeconds, 0)}秒</small>
                  </td>
                </tr>
              {:else}
                <tr>
                  <td colspan="7" class="empty-row">条件に一致するinstrumentはありません</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      </section>

      <aside class="inspector" aria-labelledby="inspector-title">
        {#if selectedInstrument}
          <div class="instrument-heading">
            <div>
              <p>{selectedInstrument.venue}</p>
              <h2 id="inspector-title">{selectedInstrument.baseAsset} PERP</h2>
              <code>{selectedInstrument.venueInstrumentId}</code>
            </div>
            <span class:quality-risk={selectedInstrument.quality !== "ready"}>
              {qualityLabel(selectedInstrument.quality)}
            </span>
          </div>

          <section class="reference-block" aria-labelledby="median-title">
            <h3 id="median-title">参考mark中央値</h3>
            <strong>{formatFinite(selectedInstrument.referenceMarkMedian.value)}</strong>
            <p>Parity仮定・reference only。{selectedInstrument.referenceMarkMedian.venueCount} Venue。</p>
            <p>{market.universe.parityAssumption.statement}</p>
            {#if selectedInstrument.referenceMarkMedian.status !== "ready"}
              <p class="quality-risk">
                算出不能: {selectedInstrument.referenceMarkMedian.unavailableReason ?? "理由なし"}
              </p>
            {/if}
          </section>

          <section class="l1-block" aria-labelledby="l1-title">
            <div class="subheading">
              <h3 id="l1-title">Venue L1</h3>
              <span>{selectedInstrument.sourceSymbol}</span>
            </div>
            <dl class="metric-grid">
              <div><dt>Mark</dt><dd>{formatFinite(selectedInstrument.markPrice)}</dd></div>
              <div><dt>Reference</dt><dd>{formatFinite(selectedInstrument.referencePrice)} ({selectedInstrument.referencePriceKind})</dd></div>
              <div><dt>Bid</dt><dd>{formatFinite(selectedInstrument.bestBid)}</dd></div>
              <div><dt>Ask</dt><dd>{formatFinite(selectedInstrument.bestAsk)}</dd></div>
              <div><dt>Funding raw</dt><dd>{formatRate(selectedInstrument.fundingRateRaw)}</dd></div>
              <div><dt>Funding / h</dt><dd>{formatRate(selectedInstrument.fundingRatePerHour)}</dd></div>
              <div><dt>OI raw</dt><dd>{formatCompact(selectedInstrument.openInterestRaw)} {selectedInstrument.openInterestRawUnit ?? ""}</dd></div>
              <div><dt>OI notional</dt><dd>{formatCompact(selectedInstrument.openInterestNotional)}</dd></div>
              <div><dt>24h volume</dt><dd>{formatCompact(selectedInstrument.volume24hRaw)} {selectedInstrument.volume24hUnit ?? ""}</dd></div>
              <div><dt>Quote</dt><dd>{selectedInstrument.quoteAsset}</dd></div>
              <div><dt>Settle</dt><dd>{selectedInstrument.settleAsset}</dd></div>
              <div><dt>Collateral</dt><dd>{selectedInstrument.collateralAsset ?? "判定不能"}</dd></div>
            </dl>
            <dl class="provenance">
              <div><dt>observedAt</dt><dd>{formatTimestamp(selectedInstrument.observedAt)}</dd></div>
              <div><dt>sourceAt</dt><dd>{formatTimestamp(selectedInstrument.sourceAt)}</dd></div>
              <div><dt>catalog source</dt><dd>{selectedInstrument.catalog.sourceKind}</dd></div>
              <div><dt>endpoint</dt><dd><code>{selectedInstrument.catalog.endpoint}</code></dd></div>
              <div><dt>payload hash</dt><dd><code>{selectedInstrument.sourcePayloadHash ?? "—"}</code></dd></div>
            </dl>
            {#if selectedInstrument.qualityReasons.length > 0 || selectedInstrument.errorCode}
              <p class="quality-reasons">
                品質理由: {[...selectedInstrument.qualityReasons, selectedInstrument.errorCode].filter(Boolean).join(" / ")}
              </p>
            {/if}
          </section>

          <section class="selection-state" aria-live="polite">
            <h3>選択group</h3>
            {#if selectedGroupId}
              <p>{selectedGroupId} / {groupVenueCount} Venue</p>
              <p>行選択は500ms後に反映し、5分ごとに監視leaseを更新します。</p>
              {#if selectionMessage}<p class="quality-good">{selectionMessage}</p>{/if}
              {#if selectionError}<p class="quality-risk" role="alert">{selectionError}</p>{/if}
            {:else}
              <p class="quality-risk">安全に同一groupへ対応できない単独instrumentです。板・約定購読は行いません。</p>
            {/if}
          </section>

          {#if chartMatchesSelection && market.chart}
            <UniverseChart payload={market.chart} venueInstrumentId={selectedInstrument.venueInstrumentId} />
          {:else}
            <section class="waiting-panel">
              <h3>価格・出来高</h3>
              <p>{selectedGroupId ? "選択反映後のchart artifactを待っています" : "group未確定のためchartを要求しません"}</p>
            </section>
          {/if}

          <section class="selected-market" aria-labelledby="selected-market-title">
            <div class="subheading">
              <div>
                <h3 id="selected-market-title">選択groupの板・約定</h3>
                <p>最大20段 / 直近100件</p>
              </div>
              <span class:quality-risk={market.selected.status !== "ready"}>
                {qualityLabel(market.selected.status)}
              </span>
            </div>
            <p class="disclaimer">{market.selected.disclaimers.statement}</p>
            <p class="disclaimer">
              手数料を含まず、将来impactを予測せず、表示価格での注文成立を保証しません。
            </p>
            {#if market.selected.qualityReasons.length > 0}
              <p class="quality-reasons">
                Selected品質理由: {market.selected.qualityReasons.join(" / ")}
              </p>
            {/if}

            {#if selectedPayload}
              {#each selectedPayload.instruments as instrument (instrument.venueInstrumentId)}
                <article class="venue-depth">
                  <div class="venue-depth-title">
                    <h4>{instrument.venue} · {instrument.sourceSymbol}</h4>
                    <span class:quality-risk={instrument.quality !== "ready"}>
                      {qualityLabel(instrument.quality)} / {formatFinite(instrument.depthAgeSeconds, 1)}秒
                    </span>
                  </div>
                  {#if instrument.qualityReasons.length > 0}
                    <p class="quality-reasons">品質理由: {selectionQualityReasons(instrument)}</p>
                  {/if}

                  <div class="book-walk-scroll">
                    <table class="book-walk-table">
                      <thead>
                        <tr><th scope="col">板上概算</th><th scope="col">買い側</th><th scope="col">売り側</th></tr>
                      </thead>
                      <tbody>
                        {#each instrument.bookWalks as estimate (estimate.notionalQuote)}
                          <tr>
                            <th scope="row">${formatFinite(estimate.notionalQuote, 0)}</th>
                            <td>
                              {#if estimate.buy}
                                avg {formatFinite(estimate.buy.averagePrice)} / {formatFinite(estimate.buy.topPriceImpactBps, 2)} bps
                              {:else}
                                算出不能: {estimate.buyUnavailableReason ?? "理由なし"}
                              {/if}
                            </td>
                            <td>
                              {#if estimate.sell}
                                avg {formatFinite(estimate.sell.averagePrice)} / {formatFinite(estimate.sell.topPriceImpactBps, 2)} bps
                              {:else}
                                算出不能: {estimate.sellUnavailableReason ?? "理由なし"}
                              {/if}
                            </td>
                          </tr>
                        {/each}
                      </tbody>
                    </table>
                  </div>

                  <details>
                    <summary>板 {instrument.bids.length} bid / {instrument.asks.length} ask</summary>
                    <div class="depth-scroll">
                      <table class="depth-table">
                        <thead><tr><th scope="col">Bid size</th><th scope="col">Bid</th><th scope="col">Ask</th><th scope="col">Ask size</th></tr></thead>
                        <tbody>
                          {#each depthRows(instrument) as level, index (index)}
                            <tr>
                              <td>{formatFinite(level.bid?.sizeBase)}</td>
                              <td>{formatFinite(level.bid?.price)}</td>
                              <td>{formatFinite(level.ask?.price)}</td>
                              <td>{formatFinite(level.ask?.sizeBase)}</td>
                            </tr>
                          {/each}
                        </tbody>
                      </table>
                    </div>
                  </details>
                </article>
              {/each}

              <details class="trades">
                <summary>直近約定 {selectedPayload.trades.length}件</summary>
                <div class="trade-scroll">
                  <table>
                    <thead><tr><th scope="col">時刻</th><th scope="col">Venue</th><th scope="col">side</th><th scope="col">price</th><th scope="col">size</th></tr></thead>
                    <tbody>
                      {#each selectedPayload.trades as trade (`${trade.venueInstrumentId}:${trade.tradeId}`)}
                        <tr>
                          <td>{formatTimestamp(trade.sourceAt ?? trade.receivedAt)}</td>
                          <td>{trade.venue}</td>
                          <td>{trade.side}</td>
                          <td>{formatFinite(trade.price)}</td>
                          <td>{formatFinite(trade.sizeBase)}</td>
                        </tr>
                      {/each}
                    </tbody>
                  </table>
                </div>
              </details>
            {:else}
              <p class="waiting-copy">
                {selectedGroupId
                  ? `選択groupのartifactを待っています: ${market.selected.qualityReasons.join(" / ") || "未生成"}`
                  : "group未確定のため詳細購読はありません"}
              </p>
            {/if}
          </section>

          <MarketPastNotesPanel venueInstrumentId={selectedInstrument.venueInstrumentId} />
        {:else}
          <div class="waiting-panel">
            <h2 id="inspector-title">Instrument未選択</h2>
            <p>Universeから1行選択してください。</p>
          </div>
        {/if}
      </aside>
    </div>
  {/if}
</main>

<style>
  :global(*) {
    box-sizing: border-box;
  }

  .universe-page {
    min-height: 100vh;
    padding: var(--space-page);
    background: var(--bg);
    color: var(--text);
  }

  .topbar {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: var(--space-lg);
    padding: var(--space-sm) 0 var(--space-md);
    border-bottom: 1px solid var(--line-strong);
  }

  .identity p,
  .identity h1,
  .identity span,
  .section-title h2,
  .section-title p,
  .instrument-heading p,
  .instrument-heading h2,
  .reference-block h3,
  .reference-block p,
  .selection-state h3,
  .selection-state p,
  .waiting-panel h2,
  .waiting-panel h3,
  .waiting-panel p,
  .subheading h3,
  .subheading p,
  .venue-depth h4,
  .quality-banner,
  .quality-reasons,
  .disclaimer,
  .waiting-copy {
    margin: 0;
  }

  .identity p {
    color: var(--focus);
    font-size: var(--type-label-caps-size);
    font-weight: 800;
  }

  .identity h1 {
    margin-top: var(--space-xs);
    font-size: var(--type-title-lg-size);
    line-height: var(--type-title-lg-leading);
  }

  .identity span,
  .section-title p,
  .subheading p {
    display: block;
    margin-top: var(--space-xs);
    color: var(--muted);
    font-size: var(--type-body-sm-size);
  }

  .preferences {
    display: flex;
    align-items: end;
    gap: var(--space-md);
  }

  .status-strip {
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    border-bottom: 1px solid var(--line-strong);
    background: var(--surface);
  }

  .status-strip div {
    min-width: 0;
    padding: var(--space-sm) var(--space-md);
    border-right: 1px solid var(--line);
  }

  .status-strip span,
  .status-strip strong {
    display: block;
  }

  .status-strip span {
    color: var(--muted);
    font-size: var(--type-label-caps-size);
  }

  .status-strip strong {
    margin-top: var(--space-xxs);
    overflow-wrap: anywhere;
    font-size: var(--type-data-md-size);
  }

  .quality-banner {
    padding: var(--space-sm) var(--space-md);
    border-bottom: 1px solid var(--warning-border);
    background: var(--surface);
    color: var(--warning);
    font-size: var(--type-body-sm-size);
  }

  .workspace {
    display: grid;
    grid-template-columns: minmax(0, 1.55fr) minmax(28rem, 1fr);
    gap: var(--space-grid);
    margin-top: var(--space-grid);
    align-items: start;
  }

  .universe,
  .inspector {
    min-width: 0;
    border: 1px solid var(--line-strong);
    background: var(--panel-solid);
  }

  .inspector {
    position: sticky;
    top: var(--space-page);
    max-height: calc(100vh - (2 * var(--space-page)));
    overflow: auto;
  }

  .section-title,
  .instrument-heading,
  .subheading,
  .venue-depth-title {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: var(--space-sm);
  }

  .section-title {
    padding: var(--space-md);
    border-bottom: 1px solid var(--line);
  }

  .section-title h2,
  .instrument-heading h2 {
    font-size: var(--type-heading-md-size);
  }

  .section-title > strong {
    color: var(--subtle);
    font-size: var(--type-data-md-size);
  }

  .filters {
    display: grid;
    grid-template-columns: minmax(12rem, 1fr) repeat(3, minmax(8rem, auto));
    gap: var(--space-sm);
    padding: var(--space-sm) var(--space-md);
    border-bottom: 1px solid var(--line);
    background: var(--surface);
  }

  .filters label {
    display: grid;
    gap: var(--space-xs);
    color: var(--muted);
    font-size: var(--type-label-caps-size);
  }

  input,
  select,
  .fatal-state button {
    min-height: var(--control-height-dense);
    border: 1px solid var(--line-strong);
    border-radius: var(--radius-none);
    background: var(--panel-strong);
    color: var(--text);
    padding: 0 var(--space-sm);
    font: inherit;
  }

  .table-scroll,
  .book-walk-scroll,
  .depth-scroll,
  .trade-scroll {
    overflow: auto;
  }

  table {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--type-body-sm-size);
  }

  th,
  td {
    padding: var(--space-sm);
    border-bottom: 1px solid var(--line);
    text-align: left;
    vertical-align: middle;
  }

  thead th {
    position: sticky;
    top: 0;
    z-index: 1;
    background: var(--panel-strong);
    color: var(--muted);
    font-size: var(--type-label-caps-size);
  }

  tbody tr.selected {
    background: var(--panel-selected);
    box-shadow: inset 3px 0 var(--focus);
  }

  .instrument-select {
    display: grid;
    gap: var(--space-xxs);
    width: 100%;
    min-height: var(--control-height-dense);
    border: 0;
    background: transparent;
    color: var(--text);
    padding: 0;
    font: inherit;
    text-align: left;
    cursor: pointer;
  }

  .instrument-select strong {
    font-size: var(--type-data-md-size);
  }

  .instrument-select span,
  td small {
    display: block;
    color: var(--muted);
    font-size: var(--type-label-caps-size);
  }

  .numeric,
  dd,
  code {
    font-variant-numeric: tabular-nums;
  }

  .empty-row {
    padding: var(--space-xl);
    color: var(--muted);
    text-align: center;
  }

  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  }

  .instrument-heading {
    padding: var(--space-md);
    border-bottom: 1px solid var(--line-strong);
    background: var(--panel-selected);
  }

  .instrument-heading p {
    color: var(--focus);
    font-size: var(--type-label-caps-size);
    font-weight: 800;
  }

  .instrument-heading h2 {
    margin-top: var(--space-xs);
    font-size: var(--type-title-lg-size);
  }

  .instrument-heading code {
    display: block;
    margin-top: var(--space-xs);
    color: var(--subtle);
    font: inherit;
    font-size: var(--type-body-sm-size);
  }

  .reference-block,
  .l1-block,
  .selection-state,
  .selected-market,
  .waiting-panel {
    padding: var(--space-md);
    border-bottom: 1px solid var(--line);
  }

  .reference-block strong {
    display: block;
    margin-top: var(--space-sm);
    font-size: var(--type-data-lg-size);
  }

  .reference-block p,
  .selection-state p,
  .waiting-panel p,
  .disclaimer,
  .waiting-copy {
    margin-top: var(--space-xs);
    color: var(--muted);
    font-size: var(--type-body-sm-size);
    line-height: var(--type-body-sm-leading);
  }

  .metric-grid,
  .provenance {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    margin: var(--space-sm) 0 0;
  }

  .metric-grid div,
  .provenance div {
    min-width: 0;
    padding: var(--space-sm);
    border-top: 1px solid var(--line);
  }

  dt {
    color: var(--muted);
    font-size: var(--type-label-caps-size);
  }

  dd {
    margin: var(--space-xxs) 0 0;
    overflow-wrap: anywhere;
    font-size: var(--type-data-md-size);
  }

  .provenance dd {
    font-size: var(--type-body-sm-size);
  }

  .provenance code {
    font: inherit;
  }

  .quality-reasons {
    margin-top: var(--space-sm);
    padding: var(--space-sm);
    border-left: 2px solid var(--quality-risk);
    color: var(--quality-risk);
    font-size: var(--type-body-sm-size);
    overflow-wrap: anywhere;
  }

  .quality-risk {
    color: var(--quality-risk) !important;
  }

  .quality-good {
    color: var(--quality-good) !important;
  }

  .selected-market {
    padding: 0;
  }

  .selected-market > .subheading,
  .selected-market > .disclaimer,
  .selected-market > .quality-reasons,
  .selected-market > .waiting-copy {
    padding-right: var(--space-md);
    padding-left: var(--space-md);
  }

  .selected-market > .subheading {
    padding-top: var(--space-md);
  }

  .disclaimer {
    color: var(--warning);
  }

  .venue-depth {
    padding: var(--space-md);
    border-top: 1px solid var(--line-strong);
  }

  .venue-depth h4 {
    font-size: var(--type-heading-md-size);
  }

  .venue-depth-title span,
  .subheading > span {
    color: var(--subtle);
    font-size: var(--type-body-sm-size);
  }

  .book-walk-table,
  .depth-table {
    min-width: 34rem;
    margin-top: var(--space-sm);
  }

  details {
    margin-top: var(--space-sm);
    border-top: 1px solid var(--line);
  }

  summary {
    min-height: var(--control-height-dense);
    padding: var(--space-sm) 0;
    color: var(--subtle);
    cursor: pointer;
    font-size: var(--type-body-sm-size);
  }

  .trades {
    margin: 0;
    padding: 0 var(--space-md) var(--space-md);
  }

  .trade-scroll table {
    min-width: 34rem;
  }

  .fatal-state {
    max-width: 48rem;
    margin: 12vh auto;
    padding: var(--space-xl);
    border: 1px solid var(--quality-risk);
    background: var(--panel-solid);
  }

  .fatal-state p {
    color: var(--quality-risk);
  }

  .fatal-state button {
    margin-top: var(--space-md);
    cursor: pointer;
  }

  @media (max-width: 80rem) {
    .workspace {
      grid-template-columns: 1fr;
    }

    .inspector {
      position: static;
      max-height: none;
      overflow: visible;
    }
  }

  @media (max-width: 60rem) {
    .filters {
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }

    .search-control {
      grid-column: 1 / -1;
    }

    .table-scroll {
      max-height: 55vh;
    }
  }

  @media (max-width: 48rem) {
    .universe-page {
      padding: var(--space-sm);
    }

    .topbar,
    .preferences {
      align-items: stretch;
      flex-direction: column;
    }

    .preferences {
      display: grid;
      grid-template-columns: 1fr;
    }

    .status-strip {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .status-strip div:nth-child(5) {
      grid-column: 1 / -1;
    }

    .filters {
      grid-template-columns: 1fr;
    }

    .search-control {
      grid-column: auto;
    }

    input,
    select,
    .instrument-select,
    summary,
    .fatal-state button {
      min-height: var(--control-height-touch);
    }

    .optional-column {
      display: none;
    }

    th,
    td {
      padding: var(--space-sm) var(--space-xs);
    }

    .instrument-select span {
      max-width: 9rem;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .metric-grid,
    .provenance {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .section-title,
    .instrument-heading,
    .subheading,
    .venue-depth-title {
      align-items: flex-start;
    }
  }
</style>
