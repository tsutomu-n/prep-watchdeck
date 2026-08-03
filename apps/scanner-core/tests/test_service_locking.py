from __future__ import annotations

import subprocess
import sys

import duckdb

from prep_watchdeck.adapters.duckdb.service_store import DuckDbServiceStore


def test_service_store_does_not_allow_second_process_duckdb_writer(tmp_path) -> None:
    cache_db = tmp_path / "watchdeck.duckdb"
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import duckdb, sys, time; "
                "con = duckdb.connect(sys.argv[1]); "
                "con.execute('CREATE TABLE lock_holder (id INTEGER)'); "
                "print('ready', flush=True); "
                "time.sleep(10)"
            ),
            str(cache_db),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "ready"
        store = DuckDbServiceStore(cache_db)

        try:
            store.diagnostics()
        except duckdb.IOException as exc:
            assert "Could not set lock on file" in str(exc)
        else:
            raise AssertionError("expected DuckDB lock to reject a second service-store process")
    finally:
        holder.terminate()
        holder.wait(timeout=5)
