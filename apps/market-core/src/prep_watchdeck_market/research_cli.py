"""Explicit, bounded research operations; only observe opens a read-only database connection."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

import typer
from pydantic import ValidationError

from prep_watchdeck_market.bundle_files import BundleError, json_bytes, write_bundle
from prep_watchdeck_market.config import Settings
from prep_watchdeck_market.research.evaluation import evaluate_trial
from prep_watchdeck_market.research.files import isolated_root, load_json, load_model
from prep_watchdeck_market.research.journal import ObservationJournal, export_snapshot
from prep_watchdeck_market.research.models import instant
from prep_watchdeck_market.research.quality import (
    inspect_funding_sources,
    quality_report,
    reconcile_archives,
)
from prep_watchdeck_market.research.reader import read_observation, require_database_target
from prep_watchdeck_market.research.snapshot import verify_snapshot
from prep_watchdeck_market.research.tool_inputs import (
    compare_ccxt,
    export_hft_npz,
    local_ccxt_capabilities,
    prepare_hft_input,
)
from prep_watchdeck_market.research.trials import TrialRules, bind_trial, register_trial

app = typer.Typer(no_args_is_help=True, add_completion=False, help=__doc__)
InputPath = Annotated[Path, typer.Option()]
OutputPath = Annotated[Path, typer.Option("--output-dir")]


def _emit(value: object) -> None:
    typer.echo(json_bytes(value).decode().rstrip())


def _run(action: Callable[[], Any]) -> Any:
    try:
        result = action()
        _emit({"path": str(result)} if isinstance(result, Path) else result)
        return result
    except BundleError as error:
        _emit({"error": error.code})
        raise typer.Exit(2) from None
    except (ValidationError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
        _emit({"error": "research_input_invalid"})
        raise typer.Exit(2) from None
    except OSError:
        _emit({"error": "research_io_unavailable"})
        raise typer.Exit(2) from None
    except KeyboardInterrupt:
        _emit({"error": "research_interrupted"})
        raise typer.Exit(130) from None


def _mapping(path: Path) -> dict[str, Any]:
    value = load_json(path)
    if not isinstance(value, dict):
        raise BundleError("research_schema_invalid")
    return value


def _report(value: dict[str, Any], output: Path) -> Path:
    return write_bundle(isolated_root(output), uuid4().hex, {"report.json": json_bytes(value)})


@app.command("observe")
def observe_command(
    journal: InputPath,
    instrument: Annotated[str, typer.Option()],
    version: Annotated[int | None, typer.Option(min=1)] = None,
    samples: Annotated[int, typer.Option(min=1, max=1440)] = 1,
    interval_seconds: Annotated[int, typer.Option(min=5, max=600)] = 60,
    lookback_minutes: Annotated[int, typer.Option(min=1, max=60)] = 5,
    clock_error_seconds: Annotated[float, typer.Option(min=0, max=30)] = 1.0,
) -> None:
    """Record bounded future observations in a separate append-only journal; no daemon."""

    def execute() -> dict[str, Any]:
        if (samples - 1) * interval_seconds >= 86400:
            raise BundleError("research_capture_window_exceeded")
        try:
            settings = Settings()
        except ValidationError:
            raise BundleError("research_settings_invalid") from None
        require_database_target(settings.database_url)
        with ObservationJournal(
            journal,
            max_gap_seconds=max(120, interval_seconds * 2),
            clock_error_seconds=clock_error_seconds,
            excluded_roots=(settings.state_dir,),
        ) as writer:
            current_version = version
            if writer.target is not None:
                if writer.target.instrument_id != instrument or (
                    version is not None and writer.target.version_id != version
                ):
                    raise BundleError("research_target_changed")
                current_version = writer.target.version_id
            schedule = time.monotonic()
            started = datetime.now(UTC)
            captured = 0
            try:
                for index in range(samples):
                    if index:
                        time.sleep(max(0, schedule + index * interval_seconds - time.monotonic()))
                    started = datetime.now(UTC)
                    until = started.replace(second=0, microsecond=0)
                    read = read_observation(
                        settings.database_url,
                        instrument_id=instrument,
                        version_id=current_version,
                        since=until - timedelta(minutes=lookback_minutes),
                        until=until,
                    )
                    receipt = writer.record(
                        read.payload,
                        read_started_at=read.read_started_at,
                        read_completed_at=read.read_completed_at,
                        elapsed_seconds=read.elapsed_seconds,
                    )
                    current_version = read.payload.target.version_id
                    captured += 1
                    _emit(
                        {
                            "observation_id": receipt.observation_id,
                            "available_at": receipt.available_at.isoformat(),
                            "reasons": receipt.reasons,
                        }
                    )
            except KeyboardInterrupt:
                writer.record_failure("research_interrupted", started_at=started)
                raise
            except BundleError as error:
                writer.record_failure(error.code, started_at=started)
                raise
            except OSError:
                writer.record_failure("research_io_unavailable", started_at=started)
                raise
            return {
                "journal": str(writer.root),
                "captured": captured,
                "qualified": all(not row.reasons for row in writer.receipts),
            }

    result = _run(execute)
    if not result["qualified"]:
        raise typer.Exit(3)


@app.command("export-snapshot")
def export_command(journal: InputPath, output_dir: OutputPath) -> None:
    """Export exact journal bytes to a new self-contained hash-checked snapshot."""
    _run(lambda: export_snapshot(journal, output_dir))


@app.command("verify-snapshot")
def verify_command(
    snapshot: InputPath, cutoff: Annotated[str | None, typer.Option()] = None
) -> None:
    """Verify bytes, identity, temporal context and reader availability without DB access."""

    def execute() -> dict[str, Any]:
        checked = verify_snapshot(snapshot, cutoff=None if cutoff is None else instant(cutoff))
        return {
            "snapshot_sha256": checked.snapshot_sha256,
            "replay_valid": checked.replay_valid,
            "qualified_for_ab": checked.qualified_for_ab,
            "observed_evidence": checked.observed_evidence,
            "reasons": checked.reasons,
            "observations": len(checked.observations),
        }

    result = _run(execute)
    if not result["qualified_for_ab"]:
        raise typer.Exit(3)


@app.command("quality")
def quality_command(
    snapshot: InputPath,
    output_dir: OutputPath,
    cutoff: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Report native minute gaps and common cohort counts using Polars."""
    _run(
        lambda: _report(
            quality_report(snapshot, cutoff=None if cutoff is None else instant(cutoff)), output_dir
        )
    )


@app.command("reconcile-archives")
def archives_command(manifest: InputPath, output_dir: OutputPath) -> None:
    """Compare exact native Parquet sources; preserve originals and report candidates only."""
    _run(lambda: _report(reconcile_archives(_mapping(manifest)), output_dir))


@app.command("inspect-funding")
def funding_command(manifest: InputPath, output_dir: OutputPath) -> None:
    """Check immutable funding source hashes, identities, duplicate rates and actual coverage."""
    _run(lambda: _report(inspect_funding_sources(_mapping(manifest)), output_dir))


@app.command("compare-ccxt")
def ccxt_compare_command(snapshot: InputPath, reference: InputPath, output_dir: OutputPath) -> None:
    """Compare caller-supplied CCXT OHLCV evidence without fetching or backfilling."""
    _run(lambda: _report(compare_ccxt(snapshot, _mapping(reference)), output_dir))


@app.command("ccxt-capabilities")
def ccxt_capabilities_command(venue: Annotated[str, typer.Option()]) -> None:
    """Inspect optional locally installed CCXT capabilities without network or credentials."""
    _run(lambda: local_ccxt_capabilities(venue))


@app.command("prepare-hft")
def hft_command(metadata: InputPath, output_dir: OutputPath) -> None:
    """Gate continuous L2/trade evidence and prepare native hftbacktest event fields."""
    _run(lambda: prepare_hft_input(_mapping(metadata), output_dir))


@app.command("export-hft-npz")
def hft_npz_command(prepared: InputPath, output_dir: OutputPath) -> None:
    """Export prepared events with optional local NumPy; does not run a backtest."""
    _run(lambda: export_hft_npz(prepared, output_dir))


@app.command("register-trial")
def register_command(rules: InputPath, output_dir: OutputPath) -> None:
    """Freeze rules, cost assumptions and evaluator before the first decision time."""
    _run(lambda: register_trial(load_model(rules, TrialRules), output_dir))


@app.command("bind-trial")
def bind_command(registration: InputPath, snapshot: InputPath, output_dir: OutputPath) -> None:
    """Bind frozen rules to exact input bytes before evaluation."""
    _run(lambda: bind_trial(registration, snapshot, output_dir))


@app.command("evaluate")
def evaluate_command(trial: InputPath, snapshot: InputPath, output_dir: OutputPath) -> None:
    """Run fixed A/B and cash control; preserve failed and insufficient results."""

    def execute() -> dict[str, str]:
        path = evaluate_trial(trial, snapshot, output_dir)
        return {"path": str(path), "status": _mapping(path / "result.json")["status"]}

    result = _run(execute)
    if result["status"] != "ESTIMABLE_DESCRIPTIVE":
        raise typer.Exit(3)
