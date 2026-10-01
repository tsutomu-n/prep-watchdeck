<script lang="ts">
  import type { UniverseInstrumentArtifact } from "$lib/generated/universe-snapshot";
  import type { CandleRecoveryState } from "$lib/generated/candle-recovery-state";
  import type { AuditIndexEntry } from "$lib/generated/candle-audit-index";
  import type { AuditDetailPage, AuditFinding } from "$lib/generated/candle-audit-detail";
  import { auditStatusLabel, findingReasonLabel } from "$lib/market/candle-audit";
  import { formatAgeSeconds, reasonSummary, statusLabel } from "$lib/market/market-state-presentation";
  import { formatTimestamp } from "$lib/market/universe-view";

  let {
    instrument,
    open = $bindable(false),
    onOpenChange,
    recovery,
    recoveryStatus,
    qualityFetchedAt,
    auditEntry,
    auditIndexStatus,
    pinnedAuditRunId,
    auditDetail,
    auditIdentityValid,
    auditDetailError,
    auditDetailLoading,
    auditOffset,
    auditMarkersEnabled,
    auditJumpMessage,
    onSelectRun,
    onPage,
    onToggleMarkers,
    onFindingJump
  }: {
    instrument: UniverseInstrumentArtifact;
    open?: boolean;
    onOpenChange: (open: boolean) => void;
    recovery: CandleRecoveryState | null;
    recoveryStatus: "loading" | "available" | "not_run" | "unavailable";
    qualityFetchedAt: string | null;
    auditEntry: AuditIndexEntry | null;
    auditIndexStatus: "loading" | "available" | "not_run" | "unavailable";
    pinnedAuditRunId: string | null;
    auditDetail: AuditDetailPage | null;
    auditIdentityValid: boolean;
    auditDetailError: string | null;
    auditDetailLoading: boolean;
    auditOffset: number;
    auditMarkersEnabled: boolean;
    auditJumpMessage: string | null;
    onSelectRun: (runId: string) => void;
    onPage: (offset: number) => void;
    onToggleMarkers: (enabled: boolean) => void;
    onFindingJump: (bucketAt: string) => void;
  } = $props();

  let recoveryDetail = $derived(recovery?.details.find((detail) =>
    detail.target.venueInstrumentId === instrument.venueInstrumentId &&
    detail.target.venueInstrumentVersionId === instrument.venueInstrumentVersionId) ?? null);
  let report = $derived(auditDetail?.report ?? null);
  let summary = $derived(report?.summary ?? null);
  let newerRunAvailable = $derived(Boolean(auditEntry && pinnedAuditRunId &&
    auditEntry.runId !== pinnedAuditRunId));
  let markerAvailable = $derived(Boolean(auditIdentityValid && auditDetail &&
    auditDetail.markerBuckets.length > 0));

  function kindLabel(kind: AuditFinding["kind"]): string {
    return ({
      value_difference: "値の差",
      return_difference: "5分対数リターンの差",
      missing_bar: "欠測",
      invalid_row: "不正行",
      missing_value: "値不足",
      return_unavailable: "リターン算出不可"
    })[kind];
  }

  function comparisonLabel(kind: AuditIndexEntry["comparisonKind"]): string {
    return ({
      snapshot_revision: "保存取得時点の差分",
      acquisition_routes: "保存経路とOpenMarket経路の比較",
      repeatability: "同じ取得経路の再現性"
    })[kind];
  }
</script>

<details class="source-quality" bind:open ontoggle={() => onOpenChange(open)}>
  <summary id="source-quality-heading">取得元・品質 <span>{auditStatusLabel(auditEntry, auditIndexStatus)}</span></summary>
  <div class="source-quality-body">
    <section aria-labelledby="current-quality-title">
      <h4 id="current-quality-title">現在データ</h4>
      <dl class="facts">
        <div><dt>品質</dt><dd>{statusLabel(instrument.quality)}</dd></div>
        <div><dt>経過</dt><dd>{formatAgeSeconds(instrument.ageSeconds)}</dd></div>
        <div><dt>観測時刻</dt><dd>{formatTimestamp(instrument.observedAt)}</dd></div>
        <div><dt>配信時刻</dt><dd>{instrument.sourceAt ? formatTimestamp(instrument.sourceAt) : "配信時刻不明"}</dd></div>
        <div><dt>理由</dt><dd>{instrument.qualityReasons.length || instrument.errorCode
          ? reasonSummary(instrument.qualityReasons, instrument.errorCode) : "記録なし"}</dd></div>
      </dl>
    </section>

    <section aria-labelledby="source-contract-title">
      <h4 id="source-contract-title">契約・取得元</h4>
      <dl class="facts">
        <div><dt>契約</dt><dd><code>{instrument.venueInstrumentId}</code> · version {instrument.venueInstrumentVersionId}</dd></div>
        <div><dt>Venue / sourceSymbol</dt><dd>{instrument.venue} / <code>{instrument.sourceSymbol}</code></dd></div>
        <div><dt>価格種別</dt><dd>取引所の約定価格（保存足） / L1 Mark（現在値）</dd></div>
        <div><dt>Quote / Settle</dt><dd>{instrument.quoteAsset} / {instrument.settleAsset}</dd></div>
        <div><dt>Catalog取得元</dt><dd>{instrument.catalog.sourceKind} · <code>{instrument.catalog.endpoint}</code></dd></div>
      </dl>
    </section>

    <section aria-labelledby="recovery-title">
      <h4 id="recovery-title">保存足の回収</h4>
      {#if recoveryStatus === "loading"}<p>回収記録を読込中</p>
      {:else if recoveryStatus === "not_run"}<p>回収は未実行です。</p>
      {:else if recoveryStatus === "unavailable"}<p role="status">回収記録を取得できません。{recovery ? "前回記録を表示しています。" : ""}</p>{/if}
      {#if recovery}
        <p>実行 {recovery.execution} · {formatTimestamp(recovery.finishedAt)} · 対象期間 {formatTimestamp(recovery.window.start)} 〜 {formatTimestamp(recovery.window.end)}（終了時刻を含まない）</p>
        <p>全市場: 対象 {recovery.summary.scannedTargetCount}/{recovery.summary.targetCount}、欠損 {recovery.summary.missingBefore ?? "未確認"} → {recovery.summary.remaining ?? "未確認"}、挿入 {recovery.summary.inserted}、失敗 {recovery.summary.failedTargets}、未処理 {recovery.summary.deferredTargets}</p>
        {#if recoveryDetail}
          <p>この契約: 欠損 {recoveryDetail.missingBefore ?? "未確認"} → {recoveryDetail.remaining ?? "未確認"}、挿入 {recoveryDetail.inserted}{recoveryDetail.errorCode ? `、理由 ${recoveryDetail.errorCode}` : ""}</p>
        {:else}
          <p>この契約の回収結果は記録されていません。全市場の合計から個別の完了は判断できません。</p>
        {/if}
        {#if recovery.detailsTruncated}<p>契約別明細は上限で省略されています。</p>{/if}
      {/if}
    </section>

    <section aria-labelledby="audit-title">
      <h4 id="audit-title">保存足照合</h4>
      {#if auditIndexStatus === "loading"}<p>照合記録を読込中</p>
      {:else if auditIndexStatus === "not_run" || (auditIndexStatus === "available" && !auditEntry)}
        <p>この契約と版の照合は未実施です。</p>
      {:else if auditIndexStatus === "unavailable"}
        <p role="status">照合一覧を取得できません。{auditEntry ? "前回記録を表示しています。" : ""}</p>
      {/if}
      {#if qualityFetchedAt && (auditIndexStatus === "unavailable" || recoveryStatus === "unavailable")}
        <p>最終取得試行: {formatTimestamp(qualityFetchedAt)} · 更新停止</p>
      {/if}
      {#if newerRunAvailable && auditEntry}
        <p role="status">新しい照合記録があります。</p>
        <button type="button" onclick={() => onSelectRun(auditEntry!.runId)}>新しい照合記録を見る</button>
      {/if}
      {#if auditEntry && auditEntry.execution !== "completed" && auditEntry.lastCompletedRunId && pinnedAuditRunId !== auditEntry.lastCompletedRunId}
        <button type="button" onclick={() => onSelectRun(auditEntry!.lastCompletedRunId!)}>前回完了記録を見る</button>
      {/if}
      {#if auditDetailLoading}<p aria-live="polite">照合詳細を読込中</p>{/if}
      {#if auditDetailError}<p role="status">{auditDetailError}{auditDetail ? "。前回取得したページを表示しています。" : ""}</p>{/if}
      {#if auditDetail && !auditIdentityValid}
        <p role="alert">対象情報が一致しません。チャート注記は使えません。</p>
      {:else if report}
        <p class="audit-outcome">{auditStatusLabel(report, "available")}{report.evidenceKind === "synthetic" ? " · テストデータ" : ""}</p>
        <p>{comparisonLabel(report.comparisonKind)}。独立性は確認していません。保存足だけの照合です。</p>
        <dl class="facts">
          <div><dt>入力足 / 対象期間</dt><dd>1分 · {formatTimestamp(report.window.start)} 〜 {formatTimestamp(report.window.end)}（終了時刻を含まない）</dd></div>
          <div><dt>評価基準 / 実行</dt><dd>{formatTimestamp(report.window.dataAsOf)} / {formatTimestamp(report.checkedAt)}</dd></div>
          <div><dt>リターン</dt><dd>5分対数リターン</dd></div>
          <div><dt>左入力</dt><dd>{report.inputs.left.label} · {report.inputs.left.sourceId} · {report.inputs.left.snapshotCreatedAt ? formatTimestamp(report.inputs.left.snapshotCreatedAt) : "取得日時未記録"}</dd></div>
          <div><dt>右入力</dt><dd>{report.inputs.right.label} · {report.inputs.right.sourceId} · {report.inputs.right.snapshotCreatedAt ? formatTimestamp(report.inputs.right.snapshotCreatedAt) : "取得日時未記録"}</dd></div>
        </dl>
        {#if summary}
          <p>対象 {summary.expectedBars}本 · 両側有効 {summary.commonValidBars}本 · 比較OHLC {summary.comparedPriceValues}値</p>
          <p>価格差異 {summary.priceDifferenceBars}本 / {summary.priceDifferenceValues}値 · 出来高差異 {summary.volumeDifferenceValues}値 · リターン差異 {summary.returnDifferencePairs}対</p>
          <p>片側欠測 左{summary.leftMissingBars}本 / 右{summary.rightMissingBars}本 · 不正 左{summary.leftInvalidBars}本 / 右{summary.rightInvalidBars}本 · 値不足 {summary.missingValueCount}件</p>
          <p>出来高比較 {report.compareVolumeBase ? `${summary.comparedVolumeValues}値` : "未実施"} · リターン比較 {summary.returnPairs}/{summary.expectedReturnPairs}対</p>
          <p>最大許容超過差: 価格 {summary.maxFlaggedPriceDiffBps ?? "—"} bps（対称相対差） / リターン {summary.maxFlaggedReturnDiffBps ?? "—"} bps（対数差）</p>
        {/if}
        <p>閾値: 価格 abs {report.tolerances.priceAbsTol}, rel {report.tolerances.priceRelTol} · 出来高 abs {report.tolerances.volumeAbsTol}, rel {report.tolerances.volumeRelTol} · リターン {report.tolerances.returnTolBps} bps</p>
        <label class="marker-toggle"><input type="checkbox" checked={auditMarkersEnabled} disabled={!markerAvailable}
          onchange={(event) => onToggleMarkers(event.currentTarget.checked)} />保存データの照合箇所を表示</label>
        {#if auditMarkersEnabled}
          <p>保存データの照合記録。表示中の取引所足を検証したものではありません。</p>
        {/if}
        {#if auditJumpMessage}<p role="status">{auditJumpMessage}</p>{/if}
        <h5>照合箇所 {auditDetail?.totalFindings ?? 0}件</h5>
        {#if auditDetail?.findings.length}
          <div class="finding-scroll"><table>
            <thead><tr><th scope="col">JST時刻</th><th scope="col">種類・項目</th><th scope="col">左値</th><th scope="col">右値</th><th scope="col">差</th><th scope="col">理由</th><th scope="col">表示</th></tr></thead>
            <tbody>
              {#each auditDetail.findings as finding, index (finding.id)}
                <tr id={`audit-finding-${auditOffset + index}`} tabindex="-1">
                  <td>{finding.bucketAt ? formatTimestamp(finding.bucketAt) : "時刻不明"}</td>
                  <td>{kindLabel(finding.kind)}{finding.field ? ` · ${finding.field}` : ""}</td>
                  <td><code>{finding.left ?? "—"}</code></td><td><code>{finding.right ?? "—"}</code></td>
                  <td><code>{finding.absoluteDifference ?? "—"}</code>{finding.differenceBps ? ` / ${finding.differenceBps} bps` : ""}</td>
                  <td>{findingReasonLabel(finding)}</td>
                  <td>{#if finding.bucketAt}<button type="button" onclick={() => onFindingJump(finding.bucketAt!)}>同時刻を見る</button>{:else}—{/if}</td>
                </tr>
              {/each}
            </tbody>
          </table></div>
        {:else}<p>このページに照合箇所はありません。</p>{/if}
        <div class="page-actions">
          <button type="button" disabled={auditOffset === 0 || auditDetailLoading} onclick={() => onPage(Math.max(0, auditOffset - 200))}>前の200件</button>
          <span>{auditDetail?.totalFindings === 0 ? 0 : auditOffset + 1}〜{Math.min(auditOffset + (auditDetail?.findings.length ?? 0), auditDetail?.totalFindings ?? 0)} / {auditDetail?.totalFindings ?? 0}</span>
          <button type="button" disabled={!auditDetail?.hasMore || auditDetailLoading} onclick={() => onPage(auditOffset + 200)}>次の200件</button>
        </div>
        <details class="technical"><summary>技術情報</summary>
          <p>runId <code>{report.runId}</code> · audit版 {report.auditVersion}</p>
          <p>left SHA256 <code>{report.inputs.left.fileSha256 ?? "未記録"}</code></p>
          <p>right SHA256 <code>{report.inputs.right.fileSha256 ?? "未記録"}</code></p>
          <p>実装 SHA256 <code>{report.implementationSha256}</code> · errorCode <code>{report.errorCode ?? "なし"}</code></p>
        </details>
      {/if}
    </section>
  </div>
</details>

<style>
  .source-quality { min-width: 0; margin: 0; border-bottom: 1px solid var(--line); }
  .source-quality > summary { display: flex; flex-wrap: wrap; justify-content: space-between; gap: var(--space-sm); min-height: 44px; padding: var(--space-md); color: var(--text); font-size: var(--type-heading-md-size); font-weight: 700; cursor: pointer; }
  .source-quality > summary span { color: var(--subtle); font-size: var(--type-body-sm-size); font-weight: 400; }
  summary:focus-visible, button:focus-visible, input:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
  .source-quality-body { min-width: 0; }
  section { padding: var(--space-md); border-top: 1px solid var(--line); overflow-wrap: anywhere; }
  h4, h5, p { margin: 0; }
  h4 { font-size: var(--type-heading-md-size); }
  h5 { margin-top: var(--space-md); font-size: var(--type-body-sm-size); }
  p { margin-top: var(--space-sm); color: var(--muted); font-size: var(--type-body-sm-size); line-height: var(--type-body-sm-leading); }
  .audit-outcome { color: var(--text); font-weight: 700; }
  .facts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); margin: var(--space-sm) 0 0; }
  .facts div { min-width: 0; padding: var(--space-sm); border-top: 1px solid var(--line); }
  dt { color: var(--muted); font-size: var(--type-label-caps-size); }
  dd { margin: var(--space-xxs) 0 0; font-size: var(--type-body-sm-size); overflow-wrap: anywhere; }
  code { font: inherit; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
  button { min-height: 44px; margin-top: var(--space-sm); border: 1px solid var(--line-strong); border-radius: var(--radius-none); background: var(--panel-strong); color: var(--text); padding: var(--space-xs) var(--space-sm); font: inherit; cursor: pointer; }
  button:disabled { opacity: .55; cursor: default; }
  .marker-toggle { display: flex; align-items: center; gap: var(--space-sm); min-height: 44px; margin-top: var(--space-sm); color: var(--text); font-size: var(--type-body-sm-size); }
  .marker-toggle input { width: 20px; height: 20px; accent-color: var(--focus); }
  .finding-scroll { max-width: 100%; margin-top: var(--space-sm); overflow-x: auto; }
  table { min-width: 42rem; width: 100%; border-collapse: collapse; font-size: var(--type-body-sm-size); }
  th, td { padding: var(--space-sm); border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
  th { color: var(--muted); }
  tr:focus { outline: 2px solid var(--focus); outline-offset: -2px; }
  .page-actions { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-sm); margin-top: var(--space-sm); font-size: var(--type-body-sm-size); }
  .technical { margin-top: var(--space-sm); }
  .technical summary { cursor: pointer; }
  @media (max-width: 48rem) { .facts { grid-template-columns: 1fr; } }
</style>
