# Prep Watchdeck DESIGN.md

- 作成: `2026-06-27T11:11:19+09:00`
- 更新: `2026-08-10T23:10:43+09:00`
- 検証: `2026-08-10T23:10:43+09:00`
- 文書更新作業時刻: `2026-08-10_23:10`
- 状態: `現行`

---

```yaml
version: alpha
name: Prep Watchdeck
description: "Dark market-monitoring-terminal visual identity for a local crypto watchdeck."
colors:
  bg: "#070908"
  bgAlt: "#090C0D"
  surface: "#0B1110"
  panel: "#0D1212"
  panelStrong: "#121A18"
  panelSelected: "#162216"
  text: "#F3F5ED"
  muted: "#8F9A91"
  subtle: "#A4AF98"
  line: "#2B3A35"
  lineStrong: "#394034"
  focus: "#D8FF38"
  primary: "#D8FF38"
  focusOn: "#090C0D"
  up: "#9BEAA7"
  down: "#FF9A8D"
  warning: "#FFD191"
  warningBorder: "#E7B94B"
  qualityGood: "#74D680"
  qualityRisk: "#D66A7A"
  chipLine: "#59614F"
  chipNeutral: "#CBD3C0"
  chartSurface: "#151813"
  chartGrid: "#252B22"
typography:
  title-xl:
    fontFamily: "Watchdeck Sans, IPAPGothic, IPA Pゴシック, IBM Plex Sans, Yu Gothic UI, Hiragino Sans, system-ui, sans-serif"
    fontSize: 44px
    fontWeight: 800
    lineHeight: 1
    letterSpacing: 0
  title-lg:
    fontFamily: "Watchdeck Sans, IPAPGothic, IPA Pゴシック, IBM Plex Sans, Yu Gothic UI, Hiragino Sans, system-ui, sans-serif"
    fontSize: 28px
    fontWeight: 800
    lineHeight: 1.05
    letterSpacing: 0
  heading-md:
    fontFamily: "Watchdeck Sans, IPAPGothic, IPA Pゴシック, IBM Plex Sans, Yu Gothic UI, Hiragino Sans, system-ui, sans-serif"
    fontSize: 16px
    fontWeight: 800
    lineHeight: 1.2
    letterSpacing: 0
  body-md:
    fontFamily: "Watchdeck Sans, IPAPGothic, IPA Pゴシック, IBM Plex Sans, Yu Gothic UI, Hiragino Sans, system-ui, sans-serif"
    fontSize: 14px
    fontWeight: 500
    lineHeight: 1.45
    letterSpacing: 0
  body-sm:
    fontFamily: "Watchdeck Sans, IPAPGothic, IPA Pゴシック, IBM Plex Sans, Yu Gothic UI, Hiragino Sans, system-ui, sans-serif"
    fontSize: 12px
    fontWeight: 500
    lineHeight: 1.35
    letterSpacing: 0
  label-caps:
    fontFamily: "Watchdeck Sans, IPAPGothic, IPA Pゴシック, IBM Plex Sans, Yu Gothic UI, Hiragino Sans, system-ui, sans-serif"
    fontSize: 11px
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: 0
  data-lg:
    fontFamily: "Watchdeck Sans, IPAPGothic, IPA Pゴシック, IBM Plex Sans, Yu Gothic UI, Hiragino Sans, system-ui, sans-serif"
    fontSize: 20px
    fontWeight: 800
    lineHeight: 1.1
    fontFeature: "\"tnum\" 1"
  data-md:
    fontFamily: "Watchdeck Sans, IPAPGothic, IPA Pゴシック, IBM Plex Sans, Yu Gothic UI, Hiragino Sans, system-ui, sans-serif"
    fontSize: 13px
    fontWeight: 750
    lineHeight: 1.2
    fontFeature: "\"tnum\" 1"
rounded:
  none: 0px
  xs: 2px
  sm: 4px
  md: 6px
spacing:
  xxs: 2px
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 24px
  page: 12px
  grid: 8px
  rowDesktop: 42px
  rowMobile: 82px
  controlDense: 34px
  controlTouch: 44px
  controlPrimaryTouch: 48px
  focusRingWidth: 2px
  focusRingOffset: 2px
components:
  page-shell:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.text}"
    padding: "{spacing.page}"
  page-shell-alt:
    backgroundColor: "{colors.bgAlt}"
    textColor: "{colors.text}"
    padding: "{spacing.page}"
  panel:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text}"
    rounded: "{rounded.none}"
    padding: "{spacing.md}"
  panel-selected:
    backgroundColor: "{colors.panelSelected}"
    textColor: "{colors.text}"
    rounded: "{rounded.none}"
    padding: "{spacing.md}"
  panel-strong:
    backgroundColor: "{colors.panelStrong}"
    textColor: "{colors.text}"
    rounded: "{rounded.none}"
    padding: "{spacing.md}"
  divider:
    backgroundColor: "{colors.line}"
    textColor: "{colors.text}"
    height: 1px
  divider-strong:
    backgroundColor: "{colors.lineStrong}"
    textColor: "{colors.text}"
    height: 1px
  muted-label:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.muted}"
    rounded: "{rounded.none}"
    padding: "{spacing.xs}"
  subtle-label:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.subtle}"
    rounded: "{rounded.none}"
    padding: "{spacing.xs}"
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.focusOn}"
    rounded: "{rounded.none}"
    padding: "{spacing.sm}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.none}"
    padding: "{spacing.sm}"
  market-row:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text}"
    rounded: "{rounded.none}"
    height: "{spacing.rowDesktop}"
  market-row-mobile:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text}"
    rounded: "{rounded.none}"
    height: "{spacing.rowMobile}"
  market-row-selected:
    backgroundColor: "{colors.panelSelected}"
    textColor: "{colors.text}"
    rounded: "{rounded.none}"
    height: "{spacing.rowDesktop}"
  status-warning:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.warning}"
    rounded: "{rounded.none}"
    padding: "{spacing.sm}"
  status-warning-border:
    backgroundColor: "{colors.warningBorder}"
    textColor: "{colors.focusOn}"
    rounded: "{rounded.none}"
    padding: "{spacing.xs}"
  status-ok:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.qualityGood}"
    rounded: "{rounded.none}"
    padding: "{spacing.sm}"
  timeframe-active:
    backgroundColor: "{colors.focus}"
    textColor: "{colors.focusOn}"
    rounded: "{rounded.none}"
    padding: "{spacing.sm}"
  movement-up:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.up}"
    rounded: "{rounded.none}"
    padding: "{spacing.xs}"
  movement-down:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.down}"
    rounded: "{rounded.none}"
    padding: "{spacing.xs}"
  quality-risk:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.qualityRisk}"
    rounded: "{rounded.none}"
    padding: "{spacing.xs}"
  badge-warning:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.warning}"
    rounded: "{rounded.none}"
    padding: "{spacing.xs}"
  badge-neutral:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.chipNeutral}"
    rounded: "{rounded.none}"
    padding: "{spacing.xs}"
  badge-neutral-line:
    backgroundColor: "{colors.chipLine}"
    textColor: "{colors.text}"
    height: 1px
  chart:
    backgroundColor: "{colors.chartSurface}"
    textColor: "{colors.chipNeutral}"
    rounded: "{rounded.none}"
  chart-grid-line:
    backgroundColor: "{colors.chartGrid}"
    textColor: "{colors.chipNeutral}"
    height: 1px
```

## Overview

Prep Watchdeck is a local crypto market monitoring watchdeck.

The visual identity is a **Dark Market Monitoring Terminal**: dense, flat, rectangular, data-first, and restrained. The interface should help the user notice abnormal movement, narrow the watch target, verify market context and data quality, and retain short-lived symbol annotations.

Priority order:

1. Find fast-moving symbols.
2. Narrow candidates for focused symbol analysis.
3. Keep risk, ranking context, and data quality visible.
4. Preserve only monitoring context needed for later observation.

The UI must not look like an automated buy/sell signal generator. It must never visually imply that a symbol should be acted on only because a row is highlighted, a score is high, or a percentage is green.

Desktop is the primary analysis surface. Mobile is for quick review, candidate checking, and reading the current symbol context. Mobile must remain usable, but it does not need to expose the same density as desktop.

## Colors

The palette uses a near-black green background, muted green-gray borders, off-white text, and one high-energy focus color.

- **Background (`bg`, `bgAlt`)**: Full-page flat monitoring-terminal surfaces. They do not add decorative page texture.
- **Panels (`surface`, `panel`, `panelStrong`)**: Watchlists, charts, monitoring rails, annotation forms, and snapshot areas. `panel` is the DesignMD-compatible opaque base. Layered workspace surfaces use the same color at `94%` opacity through the runtime `--panel` token; this opacity treatment is not a separate status color.
- **Text (`text`, `muted`, `subtle`)**: Main text, labels, captions, timestamps, and secondary explanations.
- **Focus (`focus`, `primary`)**: Selected item, active timeframe, current attention target, or primary UI action only. `primary` is an alias of `focus`; do not use either as a generic success color.
- **Up (`up`)**: Market upside movement, positive percentage movement, or upward sparkline semantics only.
- **Down (`down`)**: Market downside movement, negative percentage movement, or downward sparkline semantics only.
- **Warning (`warning`, `warningBorder`)**: Operational attention, uncertainty, risk review, draft conflicts, short-term movement warnings, and service degradation.
- **Quality good (`qualityGood`)**: Verified data quality and completed checks.
- **Quality risk (`qualityRisk`)**: Actual data or validation problems: missing, partial, stale, low-confidence, unreadable, invalid, or failed fields. It must not be visually identical to market-down red and must not be used for ordinary operational caution.
- **Chip (`chipLine`, `chipNeutral`)**: Neutral badge borders and readable neutral badge text. These colors must not imply market direction, data quality, or an action recommendation.
- **Chart (`chartSurface`, `chartGrid`)**: Chart-only surface and low-contrast grid. Chart text, borders, movement, and current focus reuse `chipNeutral`, `lineStrong`, `up`, `down`, and `focus` rather than introducing parallel semantics.

Do not use green and red for general system states if doing so can be confused with price movement. `up` and `down` are market-movement-only tokens. System state uses the visually distinct `qualityGood`, `warning`, and `qualityRisk` families according to verified, degraded, and failed state. Market movement, operational warning, data/validation quality, and system state must remain distinguishable in both text and borders.

`apps/web/src/lib/styles/watchdeck-theme.css` is the single runtime source for shared color, type, spacing, control, focus, and chart tokens, and `+layout.svelte` loads it for every route. Production route and component styles contain zero raw hexadecimal or `rgb()`/`rgba()` color literals; they consume semantic tokens or `color-mix()` from those tokens. Raw color values belong only in the shared theme and color-adapter tests.

## Typography

The UI uses the local-first `Watchdeck Sans` face. Its `@font-face` source order is
`IBM Plex Sans`, `Nimbus Sans Narrow`, `Arial Narrow`, `Yu Gothic UI`, then
`Hiragino Sans`, followed by the Linux-safe local fallbacks `DejaVu Sans`,
`Liberation Sans`, `FreeSans`, and `Noto Sans`. Japanese glyph fallback is `IPAPGothic` /
`IPA Pゴシック` before generic `system-ui` and `sans-serif`. The browser must resolve
`Watchdeck Sans`; merely listing an unavailable preferred family is not sufficient.

Large symbols such as `VELVETUSDT` may be very large and bold. This helps the user maintain symbol context when switching between the watchlist and the symbol page.

Numbers should use tabular numeric rendering where possible. Percentage values, score, turnover, ranking values, and timestamps must align cleanly and remain scannable.

Typography hierarchy:

- `title-xl`: symbol page title and dominant symbol identity.
- `title-lg`: top-level page heading.
- `heading-md`: panel titles and section headers.
- `body-md`: normal explanatory text.
- `body-sm`: compact notes, captions, helper text.
- `label-caps`: metadata labels such as `SCORE`, `QUALITY`, `15M`, `SOURCE`.
- `data-lg` and `data-md`: market data, score, turnover, and percentage values.

Avoid decorative fonts, rounded consumer-app fonts, excessive letter spacing, and viewport-scaled body text. Decorative English eyebrows are not a hierarchy mechanism; use a semantic heading or a concrete operation name. Do not use italics or repeated all-caps labels to simulate structure. Keep the intended information density and create hierarchy with named sizes, weight, alignment, and dividers. The interface should feel like a monitoring instrument, not a marketing site.

## Layout

The layout should prioritize short eye travel and fast symbol triage.

Dashboard source and focus order is fixed: Candidate Radar, Watchlist, selected-symbol detail, then corrected ranking (`補正順位`). Header and service state stay compact, while the Watchlist remains the main working area. At `85rem` and wider the selected detail may be placed in the right rail; that visual placement must not change source or keyboard order.

VPI-Lite+ is an experimental Cold snapshot aid, not a trading signal. Its primary user-facing name is `市場活動`; keep `VPI-Lite+` as a small technical label. When the optional payload is valid, place a compact discovery lane next to Candidate and classify existing Target items into activity increase or caution. Show explicit Target/Watchlist coverage and the distinct empty states `VPI判定対象なし`, `活動急増なし`, and `VPIデータ不足`, without score. The numeric score, reasons, risks, funding state, and open-interest state belong only in the selected-symbol detail. Do not add VPI to Watchlist rows, ranking, sort, Candidate ordering, or Hot ticker updates. The experimental notice must remain visible, and VPI uses existing state and quality colors rather than introducing a new palette.

At `560px` and narrower, the Dashboard source, service, and runtime boundary states form one compact three-cell strip. Each cell remains readable, source and service retain polite live status semantics, and system state colors remain separate from market direction.

Watchlist row representation follows the Watchlist container, not the viewport. A container at or above `62.125rem` uses the dense table representation; a narrower container uses the compact card representation. Both representations retain the same rows and market facts.

The symbol page order is symbol identity and key metrics, chart with timeframe selector, Monitoring Rail, six-timeframe board, then market context, Past Note, and snapshot. The chart is the primary visual analysis area. Supporting information forms a continuous workspace rather than an equal-card catalog.

On mobile, Candidate Radar and Watchlist keep every item in bounded internal scroll regions. Do not reduce them to a top-N subset, pagination, or hidden default. The outer document height must not grow in proportion to the row count. Dense table rows become compact cards without changing selection, navigation, quality, stale, note, or signal meaning.

Candidate Radar uses one continuous four-column surface at `561px` and wider. At `560px` and narrower it uses four automatic-activation tabs while retaining all ranking links in one bounded vertical scroller. Desktop and mobile representations are selected by CSS, not an SSR-sensitive viewport branch. A long formatted symbol wraps without ellipsis or horizontal overflow. Change ranking headings say `上昇順` and `下落順` because they describe sort order; every displayed change value uses `up`, `down`, or neutral styling from its actual numeric sign, independent of the panel in which it appears.

On the mobile symbol page, the Monitoring Rail summary remains two columns and the six-timeframe board remains two columns by three rows. Chart, monitoring evidence, and timeframe context appear before the Past Note form. Mobile is acceptable for checking and annotating, not full high-density scanning.

At `360px` and narrower, both six-item timeframe control groups form three columns by two rows with `44px` targets. At `720px` and narrower, the Symbol page exposes a sticky, horizontally scrollable local navigation for chart, monitoring evidence, timeframe, market context, and Past Note, plus a `分析上部へ戻る` target after the support workspace. Fragment navigation moves keyboard focus to the destination rather than changing scroll position alone.

## Elevation & Depth

Use flat panels, borders, and selected-state insets rather than soft shadows. Dashboard surfaces do not use outer drop shadows. A selected row or selected-detail rail may use a left inset only to communicate current context.

Depth should be communicated through:

- background contrast,
- panel borders,
- sticky headers,
- selected row inset,
- active timeframe fill,
- section grouping and dividers.

Primary surfaces are Watchlist and chart. Context surfaces are selected detail and Monitoring Rail. Corrected ranking and supporting information are secondary. Express these levels through border strength, surface difference, and divider rhythm—not new colors, gradients, glow, larger radius, or repeated card shadows. Avoid glassmorphism, backdrop blur, neumorphism, and decorative depth effects that reduce data clarity.

Quiet Market Instrument keeps market evidence readable without turning density into decoration. Use continuous surfaces, compact inline semantic text, neutral range tracks with a current-value marker, and explicit missing/stale states. `15分量倍率` means the current rolling 15-minute USDT turnover divided by the configured rolling 15-minute median baseline; show a validated baseline span such as `直近約24h中央値比` and do not infer it when metadata is missing or malformed. `1時間量倍率` and `4時間量倍率` extend that same ratio definition for context only. The display-only activity phase is derived from the three ratios and must never use market-direction colors or read as a buy/sell recommendation. Normal data quality stays visually quiet; abnormal quality remains explicit Japanese text.

## Shapes

The shape language is rectangular and instrument-like.

- Default radius is `0px`.
- Small radius may be used only where it improves input affordance.
- Do not mix pill-shaped buttons with sharp data tables.
- Badges, timeframe tabs, rows, cards, and forms should remain squared or nearly squared.

This UI should feel precise, not soft.

## Interaction states

Desktop analysis controls may use the `controlDense` height of `34px` where pointer accuracy and information density are primary. Compact-width controls and controls on a coarse-pointer device must provide at least the `controlTouch` target of `44px`. A primary mobile action may use `controlPrimaryTouch` at `48px`.

Keyboard focus uses the opaque `focus` color with a `focusRingWidth` of `2px` and a visible `focusRingOffset` of `2px`. The ring must retain at least 3:1 non-text contrast against adjacent surfaces. Focus, hover, active, disabled, and loading states must not change border width, padding, or control height. A selected control remains legible while pressed; an active-state background change must include a matching text-color change. Hover-only styling is limited to devices that report both hover support and a fine pointer.

Checkboxes and radio buttons keep their native control size; their associated labels provide the touch target. Action labels stay on one line, while their parent control groups may wrap or stack. Disabled controls expose a reason, loading controls expose busy state, errors use an alert and a visible `qualityRisk` field state, and successful saves use a polite status. Do not use `up` or `down` for form validity. State text and ARIA state update immediately; motion must never be the only carrier of state. Continuous and decorative motion are forbidden. The sole current-code exception is the labelled freshness/progress meter in `ServiceStatusBadge.svelte`, which smooths its width change with `transition: width 180ms linear`. It has no `prefers-reduced-motion` override yet; that is an explicit P2 residual, not permission to reuse layout-property animation elsewhere.

Past Note mutation is single-flight and route-owned. It captures the origin symbol and submitted draft revision so a response cannot clear a newer draft or leak feedback into another symbol. A same-revision success may clear the submitted draft; a later revision keeps the newer fields and announces that only the submitted content was saved. Dashboard view-setting mutation is scoped to the originating view.

## Components

### Page shell

The page shell uses a flat dark background. It does not use a decorative grid, atmospheric radial bloom, or page-level color wash to simulate hierarchy. The application declares `color-scheme: dark` for native controls and scrollbars; all routes share that base.

### Service state cards

Service state cards must communicate hierarchy clearly.

- Normal live state should be visible but not overpower the market scan.
- Service errors, stale data, or incomplete backfill must be more important than decorative status.
- If normal live state and a degraded service state appear together, the degraded service state must not be visually hidden.

### Candidate radar

Candidate radar is the fast-movement discovery area.

It must show:

- selected timeframe,
- top upward movers,
- top downward movers,
- volume leaders.
- 15-minute volume-ratio leaders and the validated baseline description.

It should be compact on desktop and readable on mobile. It should not visually imply that top-ranked items are automatic trade entries.

At compact widths, rank and value columns must yield enough inline space for every formatted symbol identity. A candidate link may not collapse the symbol column or replace a symbol with ellipsis. Mobile tabs use automatic activation: arrows, Home, and End move focus and activate the corresponding panel at the same time.

Change panels are labeled by ordering (`上昇順`, `下落順`), not by an assumed sign. Mixed-sign fixtures are valid: a negative tail value in `上昇順` remains `down`, and a positive tail value in `下落順` remains `up`.

### Watchlist rows

Watchlist rows are the core desktop scanning unit.

Rows should:

- keep symbol name, sparkline, label, score, timeframe changes, selected timeframe turnover, quality, and note state scannable;
- use `focus` only for selected row or active context;
- use `up` and `down` only for market movement;
- show poor data quality without confusing it with price movement;
- preserve high density on desktop;
- treat row activation as Dashboard selection, not navigation;
- reserve explicit analysis links for navigation;
- use roving tabindex: Arrow Up/Down and Home/End move focus, Enter/Space selects;
- keep the canonical short label for every current movement signal visible rather than hiding signals behind `+N` or tooltip-only UI;
- expose full signal names, price/stale state, classification, label, timeframe change, turnover, quality, and note through visible text or an accessible name/description.
- show a non-normal activity phase next to the 15-minute ratio; omit `NORMAL` rather than adding normal-state noise.
- omit normal data quality and show abnormal quality as `一部データ不足`, `更新遅延`, or `判定不能`.

Rows are `42px` in dense table mode and `82px` in compact mode at normal text sizing. Selection, focus, stale state, note state, and signal count must not change that normal-height contract. At 200% text sizing, rows may expand to preserve content and must not clip signals. Compact rows retain `content-visibility: auto` so full item reachability does not require eager rendering. The selected row may use a left inset and subtle selected background. Avoid full-row bright fills except for active timeframe tabs.

### Timeframe tabs

Timeframe tabs are high-priority navigation controls.

- Active timeframe uses `focus` background with dark text.
- Inactive tabs use dark surface, border, and off-white text.
- Tabs use a `44px` target on compact/coarse-pointer surfaces and an opaque visible focus ring.
- Hover styling is fine-pointer only, and selected/active states do not change control dimensions or lose text contrast.

### Monitoring Rail

Monitoring Rail summarizes why the selected symbol is worth monitoring.

It should surface:

- category/classification,
- label and data quality,
- selected timeframe,
- ranking context,
- immediate signals,
- risk tags.

Its first summary is a stable two-column grid containing classification, label, data quality, and selected timeframe. It remains two columns on mobile. It must read as monitoring evidence, not as a trade trigger; ranking or green movement never becomes an entry verdict. Internal `NO_TRADE` is displayed as `監視除外候補` without changing the scanner contract.

### Chart

The chart should remain visually central on the symbol page.

- Candles use market-up and market-down colors.
- Volume bars follow candle direction but remain lower intensity.
- Grid lines should be visible but low contrast.
- The symbol page uses `chart-stage` as the single chart frame. The chart component does not add a second analysis border or background.
- The chart region exposes a concise data summary for assistive technology; the canvas must not be the only representation of the current period, bar count, and latest OHLCV.
- Zero embedded/API bars do not defer chart mount: the empty chart container and accessible empty summary exist immediately.
- A late API response updates series on the same instance. Symbol, timeframe, or snapshot-generation changes abort the superseded request, and an aborted response cannot overwrite the current series.
- Component destruction prevents a pending module load from creating a chart, aborts the active bars request, disconnects the resize observer, removes an existing chart instance, and suppresses late state updates.

Runtime chart token mapping is fixed as follows:

- `--chart-surface` uses `chartSurface` and `--chart-grid` uses `chartGrid`.
- `--chart-text` reuses `chipNeutral`; `--chart-border` reuses `lineStrong`.
- `--chart-up`, `--chart-down`, and `--chart-focus` reuse `up`, `down`, and `focus` respectively.
- `--chart-volume-up` and `--chart-volume-down` use the corresponding market movement color at `45%` alpha. The lower alpha communicates volume intensity without changing movement semantics.

The renderer reads these values through the semantic chart adapter. A missing or invalid chart color token fails closed with the token name; it must not silently fall back to library defaults. The chart container exists before asynchronous chart data arrives so a symbol without embedded bars can still initialize when the API response returns.

The shared runtime `--panel-solid` token maps directly to `panel`, while `--panel` applies the same panel color at `94%` alpha. Components must not treat the translucent overlay as a new semantic color.

### Past Note

Past Note is a short-lived symbol annotation, not a trade record.

- Show reason, observation time, and concise note without implying execution history.
- The storage contract expires annotations after 60 days and moves them to a monthly archive; the current UI does not expose that archive lifecycle as a separate control or status.
- Keep save status, validation failure, and pending state visible without using market-direction colors.
- Scope draft and feedback to the origin symbol; a late response cannot clear a newer draft.

### Badges

Badges must be compact and semantic.

Allowed badge families:

- movement signal,
- data quality,
- past note,
- rekindle / past rapid move,
- warning,
- verified monitoring state.

Avoid adding new badge colors unless they map to the color semantics in this file.

## Do's and Don'ts

- Do prioritize fast discovery of abnormal movement.
- Do make the selected symbol and selected timeframe unmistakable.
- Do keep market movement colors separate from system state colors.
- Do make data quality visible before the user trusts a row.
- Do preserve dense desktop scanning.
- Do keep mobile usable for quick checking.
- Do keep all mobile candidates and rows reachable inside bounded scroll regions.
- Do keep every mobile candidate symbol identity readable without ellipsis.
- Do separate Dashboard selection from symbol-page navigation.
- Do use flat dividers to distinguish primary, context, and secondary work areas.
- Do make Past Note read as a temporary monitoring annotation.
- Do use `focus` sparingly for current attention.
- Don't make the interface look like a buy/sell signal generator.
- Don't add large green buttons that imply entry approval.
- Don't use bright lime for every positive or normal state.
- Don't hide stale, missing, partial, or low-quality data.
- Don't use red for both price decline and generic validation error without distinction.
- Don't replace dense tables with spacious SaaS cards on desktop.
- Don't repeat decorative English eyebrows, equal nested cards, outer shadows, or nested chart frames.
- Don't leave compact/coarse-pointer targets at dense desktop height.
- Don't introduce pastel, playful, glossy, or consumer-fintech styling.
- Don't add animations that distract from market scanning.
