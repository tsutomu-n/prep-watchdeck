# Prep Watchdeck Attention Core Implementation Plan

timestamp="2026-10-08(木)_23:47 JST"
- 作成: `2026-10-08T23:47:49+09:00`
- 更新: `2026-10-08T23:47:49+09:00`
- 状態: `実装計画`


> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 既存Market CoreとRanking Coreをread-only inputとして、説明可能なAttention component、prospective evidence、candidate-family検証、shadow hot-setを提供する独立`attention-core`を実装する。

**Architecture:** `apps/attention-core`を新しいbounded contextとして追加する。Market artifactsとRanking loopback generationをexact identity/versionで結合し、current APIと専用SQLiteへ保存する。Market/Rankingのwriter、manual selection、Provider取得、automatic executionは変更しない。

**Tech Stack:** Python 3.13、uv workspace、Pydantic 2、aiohttp、stdlib SQLite、pytest、Ruff、Pyrefly、SvelteKit 2、Svelte 5、Bun、Vitest、Playwright。

**Spec:** `01_PrepWatchdeck_Attention_Core_Design_2026-10-08.md`

## Global Constraints

- 基準Repositoryは`tsutomu-n/prep-watchdeck`、調査時`main@4278d8a690141a5118cc150b7f39f9f4d13822fd`。
- 実装開始時に`git status --short`、`git branch --show-current`、`git rev-parse HEAD`を記録する。
- HEAD差異があれば対象fileの現状を再読し、既存意味を壊さない最小変更へ補正する。
- non-trivial architecture変更なので`docs/plans/active/attention-core/`を先に作り、`ai/attention-core-YYYYMMDD-HHMM` branchを使用する。
- Market Core、Ranking Core、Web、state root、test DBをproductionから隔離する。
- Attention Coreから外部Providerへ接続しない。
- Market Postgres、Ranking SQLite、Market artifactsへ書き込まない。
- `selection.json`を変更しない。
- 自動注文、資金移動、無人executionを追加しない。
- missing / stale / invalid / unsupportedを0や前回値へ変換しない。
- symbolだけでcross-surface identityをjoinしない。
- current read APIで再計算・外部取得を行わない。
- 新しいDB migrationをMarket Coreへ追加しない。
- `ReferenceMarkets.svelte`へAttention UIを追加しない。
- production systemd unitのinstall/enable/start/restartは本計画の実装範囲外。
- push/merge/deployはユーザーの別指示がある時だけ行う。

## Review Focus

- Market bundleがread途中で切り替わった場合、混合generationを発行せず1回だけ再試行する。
- Ranking mapのoriginal versionとUniverse versionが違う場合、別versionを推測補完せずassetをinvalidにする。
- `market-metrics.tradeChange`を売買代金変化として扱わず、native close returnとして保持する。
- candidateの一部featureが欠測でもscoreを0で補わず、component availabilityとconfluence eligibilityを分離する。
- outcome horizonが未完了またはbar欠損の場合、0-returnにせずpending/unscorableにする。

---

## File Structure

### Create

```text
apps/attention-core/pyproject.toml
apps/attention-core/src/prep_watchdeck_attention/__init__.py
apps/attention-core/src/prep_watchdeck_attention/models.py
apps/attention-core/src/prep_watchdeck_attention/config.py
apps/attention-core/src/prep_watchdeck_attention/stable_files.py
apps/attention-core/src/prep_watchdeck_attention/market_input.py
apps/attention-core/src/prep_watchdeck_attention/ranking_input.py
apps/attention-core/src/prep_watchdeck_attention/identity.py
apps/attention-core/src/prep_watchdeck_attention/features.py
apps/attention-core/src/prep_watchdeck_attention/percentiles.py
apps/attention-core/src/prep_watchdeck_attention/components.py
apps/attention-core/src/prep_watchdeck_attention/storage.py
apps/attention-core/src/prep_watchdeck_attention/outcomes.py
apps/attention-core/src/prep_watchdeck_attention/evaluation.py
apps/attention-core/src/prep_watchdeck_attention/allocation.py
apps/attention-core/src/prep_watchdeck_attention/service.py
apps/attention-core/src/prep_watchdeck_attention/cli.py

apps/attention-core/tests/conftest.py
apps/attention-core/tests/test_config.py
apps/attention-core/tests/test_models.py
apps/attention-core/tests/test_stable_files.py
apps/attention-core/tests/test_market_input.py
apps/attention-core/tests/test_ranking_input.py
apps/attention-core/tests/test_identity.py
apps/attention-core/tests/test_features.py
apps/attention-core/tests/test_percentiles.py
apps/attention-core/tests/test_components.py
apps/attention-core/tests/test_storage.py
apps/attention-core/tests/test_outcomes.py
apps/attention-core/tests/test_evaluation.py
apps/attention-core/tests/test_allocation.py
apps/attention-core/tests/test_service.py
apps/attention-core/tests/test_schema_generation.py
apps/attention-core/tests/test_isolated_runner.py

scripts/attention/generate-schema.py
scripts/attention/run-isolated.py
schemas/attention-response.schema.json
schemas/attention-evaluation.schema.json
schemas/attention-shadow-allocation.schema.json

apps/web/src/lib/generated/attention-response.d.ts
apps/web/src/lib/server/attention.ts
apps/web/src/lib/server/attention.test.ts
apps/web/src/lib/attention/attention.ts
apps/web/src/lib/attention/attention.test.ts
apps/web/src/lib/components/attention/AttentionWorkspace.svelte
apps/web/src/routes/api/attention/+server.ts
apps/web/src/routes/attention/+page.server.ts
apps/web/src/routes/attention/+page.svelte
apps/web/tests/e2e/attention.e2e.ts

docs/plans/active/attention-core/GOAL.md
docs/plans/active/attention-core/RESUME.md
docs/plans/active/attention-core/acceptance.json
docs/decisions/0015-attention-core.md
```

### Modify

```text
pyproject.toml
uv.lock
.github/workflows/verify.yml
scripts/verify-local.sh
apps/web/package.json
apps/web/src/routes/+layout.svelte
docs/README.md
docs/current/architecture.md
docs/current/data-contracts.md
docs/current/ui-workflow.md
docs/current/validation.md
README.md
AGENTS.md
```

### Explicitly do not modify in F0–F7

```text
apps/market-core/migrations/*
apps/market-core/src/prep_watchdeck_market/selection.py
apps/market-core/src/prep_watchdeck_market/selection_runtime.py
apps/market-core/src/prep_watchdeck_market/selected_store.py
config/systemd/*
deploy/*
```

---

### Task 1: Create the active plan and architecture decision

**Files:**
- Create: `docs/plans/active/attention-core/GOAL.md`
- Create: `docs/plans/active/attention-core/RESUME.md`
- Create: `docs/plans/active/attention-core/acceptance.json`
- Create: `docs/decisions/0015-attention-core.md`
- Modify: `docs/README.md`

**Interfaces:**
- Consumes: Repository `AGENTS.md`、current product boundary、Decision 0012/0013。
- Produces: 実装scope、checkpoint、rollback、acceptance IDの正本。

- [ ] **Step 1: Write `GOAL.md` with fixed checkpoints F0–F8**

必須内容:

```text
Goal
non-goals
base commit
branch
input sources
state isolation
checkpoints F0–F8
completion conditions
rollback
production actions excluded
```

- [ ] **Step 2: Write `acceptance.json` with stable IDs**

最低限:

```text
ATT-001 package isolation
ATT-002 stable market read
ATT-003 canonical ranking read
ATT-004 exact identity/version join
ATT-005 no-imputation components
ATT-006 deterministic generation
ATT-007 SQLite immutability
ATT-008 outcome no-leakage
ATT-009 family validation
ATT-010 shadow allocation
ATT-011 web schema/API
ATT-012 no external provider calls
ATT-013 no Market/Ranking writes
ATT-014 no selection mutation
ATT-015 rollback
```

全項目の初期statusは`not_run`。

- [ ] **Step 3: Write Decision 0015**

決定:

```text
Attentionは独立app
Market/Rankingはread-only
manual selectionは維持
actual captureは別Decision
```

- [ ] **Step 4: Run docs checks**

Run:

```bash
bun scripts/maintenance/check-document-metadata.mjs \
  docs/plans/active/attention-core/GOAL.md \
  docs/plans/active/attention-core/RESUME.md \
  docs/decisions/0015-attention-core.md
bun scripts/maintenance/check-document-links.mjs
git diff --check
```

Expected: exit 0。

- [ ] **Step 5: Commit**

```bash
git add docs/plans/active/attention-core docs/decisions/0015-attention-core.md docs/README.md
git commit -m "docs: define attention core implementation boundary"
```

---

### Task 2: Add the Attention Core workspace package

**Files:**
- Create: `apps/attention-core/pyproject.toml`
- Create: `apps/attention-core/src/prep_watchdeck_attention/__init__.py`
- Create: `apps/attention-core/src/prep_watchdeck_attention/config.py`
- Create: `apps/attention-core/tests/test_config.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`

**Interfaces:**
- Consumes: uv workspace、Python 3.13。
- Produces: `AttentionSettings`、`isolated_attention_state()`、CLI package identity。

- [ ] **Step 1: Write failing configuration tests**

Tests:

```python
def test_state_cannot_equal_or_contain_market_or_ranking_state(): ...
def test_state_cannot_be_home_or_filesystem_root(): ...
def test_default_port_is_8770(): ...
def test_reserved_ports_are_rejected(): ...
```

- [ ] **Step 2: Run the tests and verify package is not available**

Run:

```bash
uv run --package prep-watchdeck-attention pytest \
  apps/attention-core/tests/test_config.py -q
```

Expected: FAIL because package/member does not exist.

- [ ] **Step 3: Add workspace member and package metadata**

Root:

```toml
[tool.uv.workspace]
members = ["apps/market-core", "apps/ranking-core", "apps/attention-core"]
```

Package dependencies:

```toml
dependencies = [
  "aiohttp<3.13",
  "pydantic>=2.13.4",
  "prep-watchdeck-market",
  "prep-watchdeck-ranking",
]
```

Use workspace sources for both local packages.

Dev dependencies:

```text
pytest
ruff
pyrefly
```

- [ ] **Step 4: Implement configuration**

Signatures:

```python
@dataclass(frozen=True, slots=True)
class AttentionSettings:
    state_dir: Path
    market_state_dir: Path
    ranking_state_dir: Path
    ranking_port: int = 8769
    port: int = 8770
    evidence_interval_minutes: int = 5

def isolated_attention_state(state: Path, market_state: Path, ranking_state: Path) -> Path: ...
def validate_loopback_port(port: int, *, reserved: set[int]) -> int: ...
```

Reject overlap in both directions。

- [ ] **Step 5: Run tests and static checks**

```bash
uv lock
uv run --package prep-watchdeck-attention pytest apps/attention-core/tests/test_config.py -q
cd apps/attention-core
uv run ruff check src tests
uv run ruff format --check --diff src tests
uv run pyrefly check
```

Expected: all pass。

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock apps/attention-core
git commit -m "feat: add isolated attention core package"
```

---

### Task 3: Define strict Attention contracts

**Files:**
- Create: `apps/attention-core/src/prep_watchdeck_attention/models.py`
- Create: `apps/attention-core/tests/test_models.py`

**Interfaces:**
- Consumes: Pydantic 2。
- Produces: 全後続taskが使うcontract。

- [ ] **Step 1: Write failing model tests**

Tests must assert:

```text
unknown field rejected
NaN/Infinity rejected
ready value requires non-null value and null reason
unavailable value requires null value and non-empty reason
component score is 0..100
confluence unavailable when a required component is unavailable
generation identity fields are required
```

- [ ] **Step 2: Implement model types**

Required types:

```python
FeatureStatus = Literal["ready", "missing", "stale", "invalid", "unsupported"]
ComponentStatus = Literal["ready", "unavailable"]
AttentionStatus = Literal["ready", "partial", "unavailable", "stale"]
Direction = Literal["up", "down", "flat", "mixed", "unknown"]

class RawFeatureValue(Contract): ...
class InputReference(Contract): ...
class OriginalReference(Contract): ...
class FeatureSnapshotRow(Contract): ...
class AttentionComponent(Contract): ...
class AttentionRow(Contract): ...
class AttentionCoverage(Contract): ...
class AttentionResponse(Contract): ...
class OutcomeRow(Contract): ...
class CandidatePolicy(Contract): ...
class CandidateEvaluation(Contract): ...
class AttentionEvaluationReport(Contract): ...
class ShadowSlot(Contract): ...
class ShadowAllocation(Contract): ...
```

`Contract`はcamelCase serialization、`extra="forbid"`、`frozen=True`、`allow_inf_nan=False`。

- [ ] **Step 3: Run tests**

```bash
uv run --package prep-watchdeck-attention pytest \
  apps/attention-core/tests/test_models.py -q
```

Expected: pass。

- [ ] **Step 4: Commit**

```bash
git add apps/attention-core/src/prep_watchdeck_attention/models.py \
  apps/attention-core/tests/test_models.py
git commit -m "feat: define attention evidence contracts"
```

---

### Task 4: Implement stable local file reads

**Files:**
- Create: `apps/attention-core/src/prep_watchdeck_attention/stable_files.py`
- Create: `apps/attention-core/tests/test_stable_files.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True, slots=True)
class FileIdentity:
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int

def read_stable_regular_file(path: Path, *, max_bytes: int) -> bytes: ...
```

- [ ] **Step 1: Write failing tests**

Cover:

```text
regular file success
symlink rejected
FIFO/non-regular rejected
oversize rejected
file changed between fstat/lstat rejected
missing raises typed error
```

- [ ] **Step 2: Implement no-follow stable read**

Use:

```text
os.open(... O_RDONLY | O_NOFOLLOW | O_NONBLOCK)
fstat before/read/fstat after/lstat
```

Do not return partial bytes。

- [ ] **Step 3: Run tests**

```bash
uv run --package prep-watchdeck-attention pytest \
  apps/attention-core/tests/test_stable_files.py -q
```

- [ ] **Step 4: Commit**

```bash
git add apps/attention-core/src/prep_watchdeck_attention/stable_files.py \
  apps/attention-core/tests/test_stable_files.py
git commit -m "feat: add stable attention input file reads"
```

---

### Task 5: Read a consistent Market input bundle

**Files:**
- Create: `apps/attention-core/src/prep_watchdeck_attention/market_input.py`
- Create: `apps/attention-core/tests/test_market_input.py`

**Interfaces:**
- Consumes:
  - `MarketServiceStateArtifact`
  - `UniverseSnapshotArtifact`
  - `MarketMetricsArtifact`
  - `read_stable_regular_file`
- Produces:

```python
@dataclass(frozen=True, slots=True)
class MarketInputBundle:
    service: MarketServiceStateArtifact
    universe: UniverseSnapshotArtifact
    metrics: MarketMetricsArtifact | None
    metrics_error: str | None

def read_market_inputs(
    market_state_dir: Path,
    *,
    now: datetime,
    retries: int = 1,
) -> MarketInputBundle: ...
```

- [ ] **Step 1: Write fixtures from the existing contract models**

Use actual `prep_watchdeck_market` models. Do not duplicate JSON contract。

- [ ] **Step 2: Write failing tests**

Required tests:

```text
service-state before/after identical -> success
service-state changes once -> retry succeeds
service-state changes twice -> typed failure
artifact generatedAt differs from service file state -> failure
universe stale -> failure
metrics missing -> bundle succeeds with metrics_error
metrics malformed -> partial input, not empty metrics
future timestamp -> failure
```

- [ ] **Step 3: Implement bundle consistency**

Current Universe is required。

Market metrics is optional but invalid/missing reason must be retained。

- [ ] **Step 4: Run tests**

```bash
uv run --package prep-watchdeck-attention pytest \
  apps/attention-core/tests/test_market_input.py -q
```

- [ ] **Step 5: Commit**

```bash
git add apps/attention-core/src/prep_watchdeck_attention/market_input.py \
  apps/attention-core/tests/test_market_input.py
git commit -m "feat: read consistent market inputs for attention"
```

---

### Task 6: Read one canonical Ranking generation

**Files:**
- Create: `apps/attention-core/src/prep_watchdeck_attention/ranking_input.py`
- Create: `apps/attention-core/tests/test_ranking_input.py`

**Interfaces:**
- Produces:

```python
CANONICAL_RANKING_QUERY: Mapping[str, str]

class RankingInputReader:
    def __init__(self, *, port: int, fetcher: Callable[..., Awaitable[...]] | None = None): ...
    async def read(self, *, now_ms: int) -> RankingResponse: ...
```

- [ ] **Step 1: Write failing tests**

Required:

```text
exact canonical query
loopback URL only
redirect rejected
5 second timeout
8 MiB response limit
Pydantic schema validation
ranking stale >150 seconds rejected
future cutoff rejected
one read performs one HTTP request
```

- [ ] **Step 2: Implement reader**

Endpoint:

```text
http://127.0.0.1:<port>/rankings
```

No environment proxy。

- [ ] **Step 3: Test against an aiohttp loopback fixture**

Assert request count exactly one。

- [ ] **Step 4: Run tests and commit**

```bash
uv run --package prep-watchdeck-attention pytest \
  apps/attention-core/tests/test_ranking_input.py -q
git add apps/attention-core/src/prep_watchdeck_attention/ranking_input.py \
  apps/attention-core/tests/test_ranking_input.py
git commit -m "feat: read canonical ranking generations"
```

---

### Task 7: Implement exact cross-surface identity joins

**Files:**
- Create: `apps/attention-core/src/prep_watchdeck_attention/identity.py`
- Create: `apps/attention-core/tests/test_identity.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True, slots=True)
class JoinedAsset:
    ranked: RankedRow
    universe: tuple[UniverseInstrumentArtifact, ...]
    metrics: tuple[MarketMetricRow, ...]
    state: Literal["ready", "partial", "invalid", "excluded"]
    reasons: tuple[str, ...]

def join_attention_assets(
    ranking: RankingResponse,
    market: MarketInputBundle,
) -> tuple[JoinedAsset, ...]: ...
```

- [ ] **Step 1: Write hostile tests**

```text
exact ID+version success
same symbol, wrong version rejected
same base, different instrument rejected
mapping review excluded
unsupported/out_of_scope retained as excluded
metrics row without matching Universe version ignored with reason
duplicate Universe identity rejected
duplicate metrics identity rejected
one current original gives partial, not cross-Venue consensus
```

- [ ] **Step 2: Implement exact lookup maps**

Keys:

```python
(venue_instrument_id, venue_instrument_version_id)
```

No fallback。

- [ ] **Step 3: Run tests and commit**

```bash
uv run --package prep-watchdeck-attention pytest \
  apps/attention-core/tests/test_identity.py -q
git add apps/attention-core/src/prep_watchdeck_attention/identity.py \
  apps/attention-core/tests/test_identity.py
git commit -m "feat: join attention inputs by exact contract version"
```

---

### Task 8: Build immutable raw feature snapshots

**Files:**
- Create: `apps/attention-core/src/prep_watchdeck_attention/features.py`
- Create: `apps/attention-core/tests/test_features.py`

**Interfaces:**
- Consumes: `JoinedAsset`。
- Produces:

```python
def build_feature_row(
    asset: JoinedAsset,
    *,
    decision_at: datetime,
) -> FeatureSnapshotRow: ...

def build_feature_generation(
    market: MarketInputBundle,
    ranking: RankingResponse,
    *,
    decision_at: datetime,
) -> tuple[InputReference, tuple[FeatureSnapshotRow, ...]]: ...
```

- [ ] **Step 1: Write failing arithmetic tests**

Exact cases:

```text
mark dispersion 2 and 3 venues
funding absolute max and range
spread bps
OI median for 1/2/3 venues
zero OI change is ready zero
stale L1 excluded
future observedAt rejected
negative/inverted BBO invalid
market-metrics tradeChange stored as native return, not activity
volume24hRaw not aggregated
input skew retained
```

- [ ] **Step 2: Implement feature helpers**

Required signatures:

```python
def spread_bps(bid: float, ask: float) -> float: ...
def mark_dispersion_bps(values: Sequence[float]) -> float: ...
def median_ready(
    values: Sequence[RawFeatureValue],
    *,
    minimum_sources: int = 1,
) -> RawFeatureValue: ...
```

- [ ] **Step 3: Build deterministic generation ID**

Hash canonical JSON of:

```text
input source generation/version IDs
decisionAt
feature contract version
sorted feature rows
```

- [ ] **Step 4: Run tests and commit**

```bash
uv run --package prep-watchdeck-attention pytest \
  apps/attention-core/tests/test_features.py -q
git add apps/attention-core/src/prep_watchdeck_attention/features.py \
  apps/attention-core/tests/test_features.py
git commit -m "feat: build immutable attention feature snapshots"
```

---

### Task 9: Implement deterministic midrank percentiles

**Files:**
- Create: `apps/attention-core/src/prep_watchdeck_attention/percentiles.py`
- Create: `apps/attention-core/tests/test_percentiles.py`

**Interfaces:**
- Produces:

```python
def midrank_percentiles(
    values: Mapping[str, float],
    *,
    minimum_peers: int,
) -> dict[str, float]: ...
```

- [ ] **Step 1: Write property and example tests**

Required:

```text
0..100
stable under input order permutation
ties receive identical midpoint
all equal -> 50
minimum peers failure
NaN/Infinity rejection
stable asset ID tie-break does not change tied percentile
```

Use Hypothesis only if already available through dev workspace; otherwise parameterized pytest。

- [ ] **Step 2: Implement**

For all equal values return 50 for every item。

For `n > 1`:

```text
100 * (midrank - 1) / (n - 1)
```

- [ ] **Step 3: Run tests and commit**

```bash
uv run --package prep-watchdeck-attention pytest \
  apps/attention-core/tests/test_percentiles.py -q
git add apps/attention-core/src/prep_watchdeck_attention/percentiles.py \
  apps/attention-core/tests/test_percentiles.py
git commit -m "feat: add stable attention percentiles"
```

---

### Task 10: Implement component policies and current Attention response

**Files:**
- Create: `apps/attention-core/src/prep_watchdeck_attention/components.py`
- Create: `apps/attention-core/tests/test_components.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True, slots=True)
class ComponentPolicy:
    version: str
    minimum_peers: int = 20

def score_attention(
    generation: InputReference,
    features: Sequence[FeatureSnapshotRow],
    *,
    policy: ComponentPolicy,
    previous: AttentionResponse | None = None,
) -> AttentionResponse: ...
```

- [ ] **Step 1: Write failing tests for each policy**

Exact behavior:

```text
movement uses max abs 15m/1h and retains direction
activity uses max turnover ratio
positioning uses max abs ready OI/funding signal
dislocation uses max mark/funding/spread signal
missing is never zero-filled
confluence requires all four components ready
score and readyComponentCount remain distinct
row order stable by selected component rank then asset ID
previous response only supplies comparable rank change
policy version change disables rank change
```

- [ ] **Step 2: Implement raw selection and percentile scoring**

Component rank is per component。

Default public order:

```text
confluence, then movement, then activity, then assetId
```

Rows without confluence remain present after eligible rows。

- [ ] **Step 3: Run tests and commit**

```bash
uv run --package prep-watchdeck-attention pytest \
  apps/attention-core/tests/test_components.py -q
git add apps/attention-core/src/prep_watchdeck_attention/components.py \
  apps/attention-core/tests/test_components.py
git commit -m "feat: score explainable attention components"
```

---

### Task 11: Add immutable SQLite evidence storage

**Files:**
- Create: `apps/attention-core/src/prep_watchdeck_attention/storage.py`
- Create: `apps/attention-core/tests/test_storage.py`

**Interfaces:**
- Produces:

```python
class AttentionStore:
    def __init__(self, state_dir: Path): ...
    def save_generation(
        self,
        inputs: InputReference,
        features: Sequence[FeatureSnapshotRow],
        response: AttentionResponse,
        *,
        evidence: bool,
    ) -> bool: ...
    def latest_response(self) -> AttentionResponse | None: ...
    def pending_outcomes(
        self,
        *,
        horizon_minutes: int,
        now: datetime,
    ) -> list[...]: ...
    def close(self) -> None: ...
```

- [ ] **Step 1: Write failing tests**

Required:

```text
WAL enabled
foreign_keys enabled
same generation idempotent
same generation different bytes conflict
transaction rollback on row failure
evidence=false does not enter long-term feature tables
evidence cadence uses exact 5-minute boundary
state path symlink/overlap rejected
latest response readback equals saved response
```

- [ ] **Step 2: Implement schema**

Tables:

```text
metadata
input_generations
feature_rows
component_rows
outcome_rows
candidate_policies
candidate_runs
shadow_allocations
```

Store complete JSON payload plus indexed identity/time/status columns。Do not prematurely normalize every raw feature into columns。

- [ ] **Step 3: Add database fingerprint/readback checks**

After transaction, read saved payload and compare SHA-256。

- [ ] **Step 4: Run tests and commit**

```bash
uv run --package prep-watchdeck-attention pytest \
  apps/attention-core/tests/test_storage.py -q
git add apps/attention-core/src/prep_watchdeck_attention/storage.py \
  apps/attention-core/tests/test_storage.py
git commit -m "feat: persist immutable attention evidence"
```

---

### Task 12: Build the current Attention service and API

**Files:**
- Create: `apps/attention-core/src/prep_watchdeck_attention/service.py`
- Create: `apps/attention-core/src/prep_watchdeck_attention/cli.py`
- Create: `apps/attention-core/tests/test_service.py`

**Interfaces:**
- Produces:
  - `AttentionService`
  - loopback `GET /attention`
  - loopback `GET /health`
  - CLI `watchdeck-attention serve`

- [ ] **Step 1: Write service tests**

Required:

```text
first generation pending -> 503
successful generation -> schema response
API read performs no Provider call and no input reread
unknown query rejected
non-loopback remote rejected
Host header not loopback rejected
Cache-Control no-store
generation failure preserves last validated response as stale, not fresh
DB write failure prevents publishing candidate
same input generation not duplicated
```

- [ ] **Step 2: Implement generation loop**

Schedule after the minute boundary with a bounded delay。

Do not assume Ranking is ready; retry within one bounded generation attempt, then record failure。

Current response must be created only after SQLite transaction/readback success。

- [ ] **Step 3: Implement CLI**

Commands:

```text
watchdeck-attention serve
watchdeck-attention status
watchdeck-attention validate-state
```

`status` is read-only。

- [ ] **Step 4: Run package gate**

```bash
cd apps/attention-core
uv run python -m pytest -q
uv run ruff check src tests
uv run ruff format --check --diff src tests
uv run pyrefly check
```

- [ ] **Step 5: Commit**

```bash
git add apps/attention-core
git commit -m "feat: publish current attention generations"
```

---

### Task 13: Generate Attention schemas

**Files:**
- Create: `scripts/attention/generate-schema.py`
- Create: `schemas/attention-response.schema.json`
- Create: `schemas/attention-evaluation.schema.json`
- Create: `schemas/attention-shadow-allocation.schema.json`
- Test: `apps/attention-core/tests/test_schema_generation.py`

**Interfaces:**
- Consumes: Pydantic models。
- Produces: checked JSON schema。

- [ ] **Step 1: Write check-mode failure test**

Generated content difference must exit nonzero。

- [ ] **Step 2: Implement generator**

Follow `scripts/ranking/generate-schema.py` pattern。

- [ ] **Step 3: Generate and check**

```bash
uv run --package prep-watchdeck-attention python scripts/attention/generate-schema.py
uv run --package prep-watchdeck-attention python scripts/attention/generate-schema.py --check
```

- [ ] **Step 4: Commit**

```bash
git add scripts/attention schemas/attention-*.schema.json \
  apps/attention-core/tests/test_schema_generation.py
git commit -m "feat: publish attention schemas"
```

---

### Task 14: Implement prospective outcome settlement

**Files:**
- Create: `apps/attention-core/src/prep_watchdeck_attention/outcomes.py`
- Create: `apps/attention-core/tests/test_outcomes.py`

**Interfaces:**
- Produces:

```python
class ReferenceBarReader(Protocol):
    def bars(
        self,
        reference_key: str,
        *,
        after: int,
        through: int,
    ) -> Sequence[MinuteBar]: ...

def settle_generation_outcomes(
    store: AttentionStore,
    ranking_store: ReferenceBarReader,
    *,
    generation_id: str,
    now_ms: int,
) -> tuple[OutcomeRow, ...]: ...
```

- [ ] **Step 1: Write no-leakage tests**

Required:

```text
input cutoff bar excluded from future outcome
15m horizon needs all 15 future closed bars
60m horizon needs all 60 future closed bars
missing interior bar -> unscorable
reference revision change -> unscorable
future correction creates new outcome edition
pending horizon remains pending
max absolute return and close return arithmetic
```

- [ ] **Step 2: Implement read-only reference bar adapter**

Initial development adapter uses an exported fixture or a read-only copy of Ranking SQLite。Do not open the active Ranking SQLite as a second writer。

- [ ] **Step 3: Add CLI**

```text
watchdeck-attention settle-outcomes
```

No external REST。

- [ ] **Step 4: Run tests and commit**

```bash
uv run --package prep-watchdeck-attention pytest \
  apps/attention-core/tests/test_outcomes.py -q
git add apps/attention-core/src/prep_watchdeck_attention/outcomes.py \
  apps/attention-core/tests/test_outcomes.py
git commit -m "feat: settle prospective attention outcomes"
```

---

### Task 15: Implement candidate-family evaluation

**Files:**
- Create: `apps/attention-core/src/prep_watchdeck_attention/evaluation.py`
- Create: `apps/attention-core/tests/test_evaluation.py`

**Interfaces:**
- Produces:

```python
def evaluate_candidate_family(
    store: AttentionStore,
    *,
    policy_ids: Sequence[str],
    baseline_policy_ids: Sequence[str],
    k_values: tuple[int, ...],
    minimum_practical_delta: float,
    bootstrap_samples: int,
    seed: int,
) -> AttentionEvaluationReport: ...
```

- [ ] **Step 1: Write deterministic metric tests**

Metrics:

```text
Recall@10/20
Precision@10/20
NDCG@10/20
mean future max absolute return
median lead time
coverage
unscorable rate
set churn
```

- [ ] **Step 2: Write dependence/multiplicity hostile tests**

Required:

```text
candidate order invariance
generation order invariance
exact duplicate candidate does not strengthen evidence
chance winner among many candidates not supported
stable planted edge supported with enough blocks
UTC-day and 6-hour sensitivity disagreement -> inconclusive
too few day blocks -> not_estimable
coverage regression -> rejected_coverage
same outcome generation counted once
```

- [ ] **Step 3: Implement family freeze**

Saved candidate policy IDs/hashes must match evaluation input。New candidate requires new family ID。

- [ ] **Step 4: Implement joint block max-T**

Name:

```text
attention-family-max-t-v1
```

Do not label as paper-exact White/SPA/Romano-Wolf。

- [ ] **Step 5: Implement MDE/power planning**

Fields:

```text
minimumPracticalDelta
estimatedPower
MDE80
planningOnly=true
```

Power result never overrides evidence decision。

- [ ] **Step 6: Run tests and commit**

```bash
uv run --package prep-watchdeck-attention pytest \
  apps/attention-core/tests/test_evaluation.py -q
git add apps/attention-core/src/prep_watchdeck_attention/evaluation.py \
  apps/attention-core/tests/test_evaluation.py
git commit -m "feat: validate attention candidate families"
```

---

### Task 16: Implement shadow hot-set allocators

**Files:**
- Create: `apps/attention-core/src/prep_watchdeck_attention/allocation.py`
- Create: `apps/attention-core/tests/test_allocation.py`

**Interfaces:**
- Produces:

```python
class AllocationPolicy(Contract):
    id: str
    kind: Literal["top-k-v1", "hysteresis-v1", "cost-aware-greedy-v1"]
    k: int
    buffer: int = 0
    minimum_hold_minutes: int = 0
    switch_penalty: float = 0.0

def allocate_shadow_hotset(
    response: AttentionResponse,
    *,
    policy: AllocationPolicy,
    previous: ShadowAllocation | None,
    manual_selection_id: str | None,
) -> ShadowAllocation: ...
```

- [ ] **Step 1: Write allocator tests**

Required:

```text
top-k exact selection
manual selection appears as pinned context but is not mutated
hysteresis retains rank K+buffer
exit beyond buffer
minimum hold prevents early switch
cost-aware avoids switch when benefit <= penalty
stale/unavailable asset cannot enter
map/policy version change makes previous allocation incomparable
deterministic tie handling
```

- [ ] **Step 2: Implement shadow-only persistence**

Save desired set and transition stats:

```text
added
removed
retained
churn
estimatedSwitchCost
```

Do not write `selection.json`。

- [ ] **Step 3: Add API response attachment**

`GET /attention` may include latest shadow allocation, but Attention score remains independent。

- [ ] **Step 4: Run tests and commit**

```bash
uv run --package prep-watchdeck-attention pytest \
  apps/attention-core/tests/test_allocation.py -q
git add apps/attention-core/src/prep_watchdeck_attention/allocation.py \
  apps/attention-core/tests/test_allocation.py
git commit -m "feat: add shadow attention hot-set allocation"
```

---

### Task 17: Add the isolated runner

**Files:**
- Create: `scripts/attention/run-isolated.py`
- Test: `apps/attention-core/tests/test_isolated_runner.py`

**Interfaces:**
- Consumes: state roots、ports、package CLI。
- Produces: local development isolation。

- [ ] **Step 1: Write argument/path tests**

Reject overlapping roots and non-loopback bind。

- [ ] **Step 2: Implement runner**

Follow Ranking isolated runner safety style。

Initial runner may execute without bubblewrap on unsupported test platforms, but production qualification must test the Linux restricted mode。

- [ ] **Step 3: Run tests and commit**

```bash
uv run --package prep-watchdeck-attention pytest \
  apps/attention-core/tests/test_isolated_runner.py -q
git add scripts/attention/run-isolated.py \
  apps/attention-core/tests/test_isolated_runner.py
git commit -m "feat: add isolated attention runner"
```

---

### Task 18: Add Web reader and API proxy

**Files:**
- Modify: `apps/web/package.json`
- Create: `apps/web/src/lib/generated/attention-response.d.ts`
- Create: `apps/web/src/lib/server/attention.ts`
- Create: `apps/web/src/lib/server/attention.test.ts`
- Create: `apps/web/src/routes/api/attention/+server.ts`

**Interfaces:**
- Produces: `AttentionReader.read()`、Web `/api/attention`。

- [ ] **Step 1: Extend generated type command**

Add `attention-response.schema.json`。

Do not hand-edit generated type。

- [ ] **Step 2: Write server reader tests**

Required:

```text
port validation
loopback URL
redirect error
5 second timeout
8 MiB limit
Ajv schema validation
future decisionAt rejected
duplicate row ID rejected
no-store
503 when core unavailable
403 for unauthorized request
```

- [ ] **Step 3: Implement `AttentionReader`**

Pattern after RankingReader, but use Attention schema。

- [ ] **Step 4: Run Web unit tests**

```bash
cd apps/web
bun run generate:types
bun run test -- src/lib/server/attention.test.ts
bun run check
```

- [ ] **Step 5: Commit**

```bash
git add apps/web/package.json apps/web/src/lib/generated/attention-response.d.ts \
  apps/web/src/lib/server/attention.ts apps/web/src/lib/server/attention.test.ts \
  apps/web/src/routes/api/attention
git commit -m "feat: expose attention data to the web"
```

---

### Task 19: Add the Attention UI surface

**Files:**
- Create: `apps/web/src/lib/attention/attention.ts`
- Create: `apps/web/src/lib/attention/attention.test.ts`
- Create: `apps/web/src/lib/components/attention/AttentionWorkspace.svelte`
- Create: `apps/web/src/routes/attention/+page.server.ts`
- Create: `apps/web/src/routes/attention/+page.svelte`
- Modify: `apps/web/src/routes/+layout.svelte`
- Test: `apps/web/tests/e2e/attention.e2e.ts`

**Interfaces:**
- Consumes: `AttentionResponse`。
- Produces: `/attention`。

- [ ] **Step 1: Write pure presentation tests**

Required:

```text
component label
direction label
quality/reason label
score null display
favorite overlay does not change market rank
stable local filtering
```

- [ ] **Step 2: Implement minimal page**

Controls:

```text
component: confluence/movement/activity/positioning/dislocation
search
ready only / include unavailable
favorites overlay
```

Columns:

```text
rank
asset
score
direction
ready components
quality
data-as-of
reason
```

- [ ] **Step 3: Add detail links**

Reference link:

```text
/?mode=reference&selected=<row.id>
```

Native links use exact original instrument ID/version。

Do not duplicate TradingView/native chart in first UI。

- [ ] **Step 4: Add navigation**

Add `注目` without changing existing route meaning。

- [ ] **Step 5: E2E**

Desktop and mobile:

```text
page loads fixture
component switch
missing score reason
keyboard focus
favorite overlay
reference/native link identity
no horizontal page overflow at 390px
stale response warning
```

- [ ] **Step 6: Run Web gate and commit**

```bash
cd apps/web
bun run test
bun run check
bun run build
bun run test:e2e -- attention.e2e.ts
git add apps/web
git commit -m "feat: add attention workspace"
```

---

### Task 20: Integrate repository and CI gates

**Files:**
- Modify: `.github/workflows/verify.yml`
- Modify: `scripts/verify-local.sh`
- Modify: `AGENTS.md`
- Modify: `README.md`

**Interfaces:**
- Produces: path-aware Attention gate。

- [ ] **Step 1: Add `attention` output to CI change detection**

Paths:

```text
apps/attention-core/*
scripts/attention/*
schemas/attention-*
```

Attention schema also selects Web/E2E。

- [ ] **Step 2: Add CI job**

Commands:

```bash
uv sync --frozen --package prep-watchdeck-attention --group dev
uv lock --check
cd apps/attention-core
uv run python -m pytest -q
uv run ruff check src tests
uv run ruff format --check --diff src tests
uv run pyrefly check
cd ../..
uv run --package prep-watchdeck-attention python scripts/attention/generate-schema.py --check
```

- [ ] **Step 3: Add local full gate**

Insert Attention package gate before Web generated types。

- [ ] **Step 4: Update AGENTS paths and commands**

Add:

```text
Attention Core / tests
Attention state root
schema generator
focused checks
no Provider calls
no selection writes
```

- [ ] **Step 5: Run repository contract tests**

```bash
bun test \
  scripts/maintenance/document-contracts.test.mjs \
  scripts/maintenance/product-boundary.test.mjs \
  scripts/maintenance/runtime-targets.test.mjs
```

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/verify.yml scripts/verify-local.sh AGENTS.md README.md
git commit -m "ci: verify attention core"
```

---

### Task 21: Document current contracts and validation

**Files:**
- Modify: `docs/current/architecture.md`
- Modify: `docs/current/data-contracts.md`
- Modify: `docs/current/ui-workflow.md`
- Modify: `docs/current/validation.md`
- Modify: `docs/plans/active/attention-core/RESUME.md`
- Modify: `docs/plans/active/attention-core/acceptance.json`

**Interfaces:**
- Produces: Repository current truth after source completion。

- [ ] **Step 1: Document process boundary**

Clearly state:

```text
Attention Core is read-only relative to Market/Ranking
Provider calls = 0
current generation every minute
evidence generation every 5 minutes
manual selection unchanged
shadow allocation only
```

- [ ] **Step 2: Document schemas/API**

```text
GET /api/attention
attention-response-v1
attention-evaluation-v1
attention-shadow-allocation-v1
```

- [ ] **Step 3: Document validation boundary**

Separate:

```text
source/unit validation
isolated runtime
prospective evidence
production service deployment
actual capture
```

- [ ] **Step 4: Update acceptance evidence**

Only mark items pass with command/output/hash evidence。

- [ ] **Step 5: Run doc checks and commit**

```bash
bun scripts/maintenance/check-document-metadata.mjs
bun scripts/maintenance/check-document-links.mjs
git diff --check
git add docs
git commit -m "docs: record attention core contracts"
```

---

### Task 22: Run focused and full validation

**Files:**
- Modify only if a failing test identifies a scoped defect。

**Interfaces:**
- Produces: source acceptance evidence。

- [ ] **Step 1: Attention package gate**

```bash
cd apps/attention-core
uv run python -m pytest -q
uv run ruff check src tests
uv run ruff format --check --diff src tests
uv run pyrefly check
```

- [ ] **Step 2: Schema check**

```bash
cd ../..
uv run --package prep-watchdeck-attention python scripts/attention/generate-schema.py --check
```

- [ ] **Step 3: Related regression**

```bash
cd apps/ranking-core
uv run python -m pytest -q
cd ../market-core
uv run python -m pytest -q
```

- [ ] **Step 4: Web gate**

```bash
cd ../web
bun run generate:types
bun run test
bun run check
bun run build
PREP_WATCHDECK_FULL_E2E=1 bun run test:e2e
```

- [ ] **Step 5: Full local gate**

```bash
cd ../..
bash scripts/verify-local.sh
```

Expected: exit 0。

- [ ] **Step 6: Verify no prohibited writes**

Check isolated test roots only。

Confirm:

```text
no production Market DB connection
no production Ranking state modification
no selection.json modification
no Provider request by Attention Core
no systemd operation
no deploy
```

- [ ] **Step 7: Diff audit**

```bash
git diff --check
git status --short
git diff --stat
```

- [ ] **Step 8: Update acceptance ledger**

Record exact HEAD, test commands, counts, logs/hashes, blocked production items。

- [ ] **Step 9: Commit final source-only checkpoint**

```bash
git add <only attention task files>
git commit -m "feat: complete attention core shadow validation"
```

---

## Deferred Plan: Actual multi-capture

Do not implement in Tasks 1–22。

A separate spec/Decision is required after shadow evidence。

Required future design topics:

```text
capture command version
manual pinned lane
number of automatic slots
Provider connection/subscription capacity
lease ownership
DB schema
depth/trade retention
queue bounds
first-event latency
cleanup deadline
rate limits
artifact/API
rollback
```

Current `selection.json` and `selected_group_leases_single_active_idx` remain unchanged。

---

## Plan Self-Review

### Spec coverage

- Separate app/service: Tasks 2, 12, 17。
- Stable Market/Ranking reads: Tasks 4–6。
- Exact identity: Task 7。
- Raw features and component policies: Tasks 8–10。
- Evidence storage: Task 11。
- Outcome no-leakage: Task 14。
- Candidate-family correction and power: Task 15。
- Shadow allocation: Task 16。
- Web/UI: Tasks 18–19。
- CI/docs/acceptance: Tasks 20–22。
- Actual capture deferred by explicit gate。

### Type consistency

The following names are fixed across tasks:

```text
MarketInputBundle
RankingInputReader
JoinedAsset
FeatureSnapshotRow
AttentionResponse
AttentionStore
AttentionEvaluationReport
ShadowAllocation
```

### Scope

One implementation branch may complete F0–F7。Actual capture is a separate architectural project。

### Implementation recommendation

Use subagent-driven development because contracts、statistics、storage、service、Web、validation are separable review units、and a silent identity/time error would invalidate all later evidence。
