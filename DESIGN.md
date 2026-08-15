# Prep Watchdeck Design Constitution

- 作成: `2026-06-27T11:11:19+09:00`
- 更新: `2026-08-14T22:07:54+09:00`
- 検証: `2026-08-14T22:07:54+09:00`
- 状態: `現行`

---

```yaml
version: alpha
name: Prep Watchdeck
description: "Dark-first market-monitoring-terminal visual identity with an optional low-glare light scheme."
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

## Product Boundary

Prep Watchdeck is a local crypto perpetual-market Universe Explorer. It is not a trading bot.

The identity is a **Dark-first Market Monitoring Terminal** with an optional low-glare light scheme: dense, flat,
rectangular, data-first, and restrained.
The interface helps the user:

1. scan Bitget, Hyperliquid Core, and Aster instruments without giving one Venue priority;
2. narrow instruments by identity, Venue, coverage, and data quality;
3. inspect source-specific price, funding, OI, volume, freshness, depth, and trades;
4. retain only short-lived instrument notes needed for later observation.

Highlighted rows, reference medians, movement colors, and book-walk estimates must never look like automatic
buy / sell recommendations or executable-price claims. Past Note is a 60-day `venueInstrumentId` annotation,
not a trade record.

Desktop is the primary analysis surface. Mobile supports quick review, monitoring-target checking, and
current-symbol context; it remains usable without reproducing Desktop density.

## Color Semantics

- `bg` / `bgAlt`: flat page surfaces without decorative texture.
- `surface` / `panel` / `panelStrong`: workspace surfaces. `panel` is the opaque base; runtime `--panel`
  may use the same color at 94% alpha and is not a new state color.
- `text` / `muted` / `subtle`: primary text, labels, captions, timestamps, secondary explanation.
- `focus` / `primary`: selected timeframe, selected symbol, current attention, primary action only.
- `up` / `down`: market movement only.
- `warning` / `warningBorder`: operational attention, uncertainty, risk review, conflict, degradation.
- `qualityGood`: verified data quality or completed check.
- `qualityRisk`: missing, partial, stale, low-confidence, unreadable, invalid, failed data or validation.
- `chipLine` / `chipNeutral`: neutral badge semantics.
- `chartSurface` / `chartGrid`: chart-only surface and grid.

market movement、operational warning、data quality、system state を text と border の両方で区別する。
`up` / `down` を一般 system state や form validity に使わない。stale、missing、partial、
low-quality を隠さない。新しい色はこの文書へ semantic role とともに追加してから使う。

`apps/web/src/lib/styles/watchdeck-theme.css` が runtime の color、type、spacing、control、focus、
chart token の単一 source であり、全 route が `+layout.svelte` から読む。production component に
raw hexadecimal / `rgb()` / `rgba()` を置かず、semantic token または token 由来の
`color-mix()` を使う。

## Selectable Color Schemes

YAMLの`colors`は既定の`watchdeck`（画面表示は`標準`）を固定する。利用者は同じsemantic roleを
保ったまま、3つのDark themeと4つのLight themeへ切り替えられる。配色変更で
movement、warning、quality、focusの意味、typography、shape、spacing、densityを変更しない。
selectorは閉じた状態でも現在の種別を`DARK` / `LIGHT`の文字で示し、展開時は
「ダークテーマ」「ライトテーマ」のnative groupへ4件ずつ分ける。色だけで種別を伝えない。

### Dark themes

| runtime token | Carbon Aurora | Forest Amber | Plum Signal |
| --- | --- | --- | --- |
| `bg` | `#0B0D10` | `#1E2326` | `#141421` |
| `bgAlt` | `#101216` | `#232A2E` | `#191927` |
| `surface` | `#151922` | `#272E33` | `#1E1E2E` |
| `panel` | `rgba(24, 29, 39, 0.94)` | `rgba(45, 53, 59, 0.94)` | `rgba(36, 36, 58, 0.94)` |
| `panelSolid` | `#181D27` | `#2D353B` | `#24243A` |
| `panelStrong` | `#202735` | `#343F44` | `#2B2B46` |
| `panelSelected` | `#1D3040` | `#3A4947` | `#332A4F` |
| `text` | `#F4F7FA` | `#D3C6AA` | `#F8F8F2` |
| `muted` | `#9BA7B4` | `#9DA9A0` | `#9399B2` |
| `subtle` | `#B8C2CC` | `#B3B9AD` | `#BAC2DE` |
| `line` | `#2B3440` | `#384B55` | `#35354F` |
| `lineStrong` | `#3C4A59` | `#4F5F60` | `#494A68` |
| `focus` / `primary` | `#33B1FF` | `#DBBC7F` | `#AB9DF2` |
| `focusOn` | `#071018` | `#1E2326` | `#151421` |
| `up` | `#42BE65` | `#A7C080` | `#A6E3A1` |
| `down` | `#F78166` | `#E67E80` | `#FF6188` |
| `warning` | `#FFE97B` | `#DFA000` | `#F9E2AF` |
| `warningBorder` | `#E3B341` | `#D8A657` | `#FC9867` |
| `qualityGood` | `#3DDBD9` | `#7FBBB3` | `#89B4FA` |
| `qualityRisk` | `#EE5396` | `#D699B6` | `#E558A9` |
| `chipLine` | `#4A5A6A` | `#52605D` | `#585B70` |
| `chipNeutral` / `chartText` | `#C8D1DA` | `#C7C4B5` | `#CDD6F4` |
| `chartSurface` | `#11151C` | `#20272B` | `#191927` |
| `chartGrid` | `#252D38` | `#344048` | `#313146` |

### Light themes

| runtime token | Paper Ledger | Arctic Terminal | Sage Field | Lilac Current |
| --- | --- | --- | --- | --- |
| `bg` | `#F3EAD3` | `#F3F5F7` | `#EEF1E8` | `#F4F1F8` |
| `bgAlt` | `#EAE4CA` | `#E8EAED` | `#E4E9DC` | `#EAE5F1` |
| `surface` | `#FBF7E9` | `#FFFFFF` | `#FAFBF6` | `#FCFAFD` |
| `panel` | `rgba(247, 241, 221, 0.94)` | `rgba(248, 250, 252, 0.94)` | `rgba(244, 246, 238, 0.94)` | `rgba(247, 243, 250, 0.94)` |
| `panelSolid` | `#F7F1DD` | `#F8FAFC` | `#F4F6EE` | `#F7F3FA` |
| `panelStrong` | `#E5DFC5` | `#E9EEF4` | `#DEE5D5` | `#E5DDED` |
| `panelSelected` | `#E1E7DD` | `#E4EEFC` | `#DDEAE2` | `#E8E0F4` |
| `text` | `#26313A` | `#202124` | `#24333A` | `#2D2933` |
| `muted` | `#667069` | `#5F6368` | `#5C6A72` | `#6A6372` |
| `subtle` | `#4F5D65` | `#4E5968` | `#48605F` | `#514A5B` |
| `line` | `#D0C6AA` | `#D7DCE2` | `#CBD3C4` | `#D6CEDD` |
| `lineStrong` | `#9A927C` | `#9BA5B1` | `#89988A` | `#9A90A4` |
| `focus` / `primary` | `#1E6FCC` | `#1967D2` | `#2B6E9E` | `#6D46B8` |
| `focusOn` | `#FFFFFF` | `#FFFFFF` | `#FFFFFF` | `#FFFFFF` |
| `up` | `#216609` | `#188038` | `#4E7300` | `#26734D` |
| `down` | `#B33120` | `#D93025` | `#B53C3C` | `#B53D56` |
| `warning` | `#8A5A00` | `#8A5A00` | `#8A6200` | `#8A5A00` |
| `warningBorder` | `#A06D00` | `#A86200` | `#A16A00` | `#A76400` |
| `qualityGood` | `#14746F` | `#087F8C` | `#14796C` | `#216A8A` |
| `qualityRisk` | `#8B3F7A` | `#7E3FB2` | `#9A3E6B` | `#9A3D80` |
| `chipLine` | `#9A927C` | `#9BA5B1` | `#89988A` | `#9A90A4` |
| `chipNeutral` / `chartText` | `#46545A` | `#4E5968` | `#42585B` | `#514A5B` |
| `chartSurface` | `#F7F1DD` | `#F8FAFC` | `#F5F7F0` | `#F8F5FA` |
| `chartGrid` | `#D8D0BC` | `#DCE2E8` | `#D8DED2` | `#DDD5E3` |

`chartBorder`は`lineStrong`、`chartUp` / `chartDown` / `chartFocus`はそれぞれ
`up` / `down` / `focus`と同じ値を使う。chart volumeは対応するmovement色をalpha `0.45`で使う。
Plum Signalの`qualityRisk`は参照案の色相を保ち、小さい品質labelが`panelSolid`上で4.5:1以上に
なる最小の明度補正を含む。
Light themeは本文と状態labelを`panelSolid`上で4.5:1以上、focus ringを`bgAlt`上で3:1以上に保ち、
各IDへ`color-scheme: light`を適用する。Paper Ledgerは低輝度の温色、Arctic Terminalは明快な無彩色、
Sage Fieldは低刺激なセージ、Lilac Currentは選択状態を識別しやすい紫灰色を基調とする。

## Typography

`Watchdeck Sans` は local-first で解決する。source order は `IBM Plex Sans`、`Nimbus Sans Narrow`、
`Arial Narrow`、`Yu Gothic UI`、`Hiragino Sans`、Linux fallback の `DejaVu Sans`、
`Liberation Sans`、`FreeSans`、`Noto Sans`、日本語 glyph fallback の `IPAPGothic` /
`IPA Pゴシック`、generic family とする。browser が実際に `Watchdeck Sans` を解決できることを
確認し、存在しない preferred family の列挙だけで済ませない。

instrument identity は大きく bold にできる。number は可能な限り tabular numeric とし、mark、
funding、OI、volume、bps、timestamp を走査しやすく揃える。

- `title-xl`: selected instrument identity
- `title-lg`: top-level page heading
- `heading-md`: panel / section heading
- `body-md`: normal explanation
- `body-sm`: compact note / caption / helper
- `label-caps`: metadata label
- `data-lg` / `data-md`: market data and numeric values

decorative font、consumer-app の丸い書体、過剰な letter spacing、viewport-scaled body text、italics、
反復 all-caps eyebrow を避ける。named size、weight、alignment、divider で monitoring instrument
としての階層を作る。

### Selectable font schemes

YAMLのfont familyは既定の`watchdeck`を固定する。利用者は全画面共通fontを次の2つから選べる。
追加fontのdownloadや外部配信は行わず、先頭候補がない環境では同じ分類のlocal font、最後に
generic familyへfallbackする。font変更でsize、weight、line-height、spacing、row高を変更しない。

| ID | 表示名 | local-first stackの先頭 | 用途 |
| --- | --- | --- | --- |
| `watchdeck` | 標準（コンパクト） | `Watchdeck Sans` | 既定。Desktopの高密度走査 |
| `terminal` | 等幅（ターミナル） | `Cascadia Mono` / `IBM Plex Mono` | 数値、timestamp、短いcodeの桁を揃える |

Universe Explorerのheaderにnative selectを置く。選択は本文、control、data、chart axisへ
同時に適用し、chart instance、series、request、observerを作り直さない。

## Shape and Depth

基本形状は rectangular で `0px` radius とする。input affordance に必要な場合だけ小さな radius を
使い、pill button と sharp table を混在させない。

soft shadow、glassmorphism、backdrop blur、neumorphism を使わない。depth は background contrast、
border、sticky header、selected-row inset、active-timeframe fill、section grouping、divider で示す。
primary、context、secondary surface の階層に新色、gradient、glow、反復 card shadow を使わない。

badge は Venue、coverage、data quality、Past Note、warning、verified monitoring state の
semantic family に限定する。

## Surface Hierarchy

Universe Explorerはheader/filter、instrument Universe、selected detailの順に理解できる構造とする。
Universeをprimary surface、selected detailをcontext surface、provenanceとdisclaimerをsupporting surfaceとする。
DesktopではUniverseとdetailを並置できるが、DOM、読み上げ、keyboard順は
[`docs/current/ui-workflow.md`](docs/current/ui-workflow.md)を正本とする。

page shellはflat theme backgroundとし、装飾gridやpage-level color washを使わない。normal service stateを
過剰に強調せず、error、stale、partial、unavailableを見落としにくくする。

## Universe Visual Contract

filterは一つのcompact toolbarにまとめ、native search/selectと常時表示labelを使う。UniverseはDesktopで
dense table、狭い幅でcompact rows/cardsへ変換できる。通常row高はtable `42px`、Mobile `82px`を基準にし、
selection、focus、stale、noteの有無だけで不規則に変えない。

selected rowだけにfocus color、left inset、subtle selected backgroundを使える。movement色は市場値の方向、
quality色はmissing/stale/partial、focus色は選択だけに使う。reference medianはVenue値より強く見せず、
参加Venue数、freshness、parity仮定を同じsurfaceで確認できるようにする。

group coverageとqualityを同じbadgeへ押し込まない。単独instrumentはneutral、unavailableはquality riskで示す。
mark、funding、OI、volumeのnullを`0`、dashだけ、前回値へ変換せず、理由またはaccessible labelを付ける。

## Selected Detail Visual Contract

selected identity、Chart、Venue別depth、trades、book walk、Past Noteを一つのcontinuous workspaceにする。
Chartを中心となる単一frameとして、二重borderやnested chart cardを作らない。5 timeframe controlは
active fillとtextで選択を示し、`derived_final`と`confirmed`を同一視しない。

depthはbid/askを色だけで区別せずlabelを持つ。book walkは$100/$500/$1,000を同じ尺度で並べ、
fee、将来impact、注文可否を含まないdisclaimerを数値から離さない。staleまたは板不足では空欄を
埋めず、unavailable reasonを表示する。

Past Noteはreason、observation time、concise noteを持つ60日間のinstrument annotationとして見せ、
trade recordやexecution historyにしない。Chart request、selection heartbeat、cleanup、mutation、
draft競合の挙動は[`docs/current/ui-workflow.md`](docs/current/ui-workflow.md)を正本とする。

## Responsive, Accessibility, and Motion

- `560px`以下のTopbarはsource、service、runtime boundaryを可読なstackにする。
- `960px`以下ではUniverseとselected detailを縦方向へ並べ、全itemへの到達性を維持する。
- Mobileでinstrument row、filter、Chart、depthをviewport外へ横溢れさせない。
- `360px`以下のfive-item timeframe controlは3-columnを基本とする。
- Desktopの高密度controlは`34px`を使用できる。compact widthまたはcoarse pointerでは`44px`以上、
  primary Mobile actionは`48px`を使用できる。

keyboard focusはopaqueな`focus` color、`2px` ring、`2px` offsetで、隣接surfaceに対して3:1以上の
non-text contrastを保つ。colorだけをstateの伝達手段にせず、selected、busy、error、save resultは
対応するtextとARIA stateを持つ。selection、IME、focus、scrollの挙動詳細は
[`docs/current/ui-workflow.md`](docs/current/ui-workflow.md)を正本とする。

continuous / decorative motionは禁止する。motionをstateの唯一の伝達手段にせず、reduced-motionを
尊重する。必要なtransitionは150〜200ms程度のcolor/opacity/transformへ限定し、layout-propertyを
animationしない。

## Validation

```bash
cd apps/web
bun run check
bun test
bun run build
cd ../..
npx -p @google/design.md designmd lint DESIGN.md
```

layout、interaction、responsive behaviorを変えた場合は関連Playwright E2Eと1440px / 390pxのvisual
確認も実行する。現行の挙動と検証根拠は
[`docs/current/ui-workflow.md`](docs/current/ui-workflow.md)に従う。
