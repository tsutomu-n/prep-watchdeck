from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

import pytest

from prep_watchdeck_market import native_activity_publication as publication
from prep_watchdeck_market.native_activity import NativeActivityArtifact


def fixture(now):
    return NativeActivityArtifact(
        generation_id="isolated",
        generated_at=now,
        candle_cutoff=now.replace(second=0, microsecond=0) - timedelta(minutes=3),
        rows=(),
    )


def test_publication_is_atomic_and_preserves_newer_generation(monkeypatch, tmp_path):
    now = datetime(2026, 10, 8, 5, 0, tzinfo=UTC)
    artifact = fixture(now)
    monkeypatch.setattr(publication.psycopg, "connect", lambda *a, **kw: nullcontext(None))
    monkeypatch.setattr(publication, "read_native_activity", lambda *a, **kw: artifact)
    assert publication.publish_native_activity("unused", tmp_path, now=now) == 0
    path = tmp_path / "native-activity.json"
    first = path.read_bytes()
    assert NativeActivityArtifact.model_validate_json(first) == artifact
    monkeypatch.setattr(
        publication, "read_native_activity", lambda *a, **kw: fixture(now - timedelta(minutes=1))
    )
    publication.publish_native_activity("unused", tmp_path, now=now)
    assert path.read_bytes() == first


def test_publication_never_overwrites_foreign_schema_or_concurrent_writer(monkeypatch, tmp_path):
    now = datetime(2026, 10, 8, 5, 0, tzinfo=UTC)
    path = tmp_path / "native-activity.json"
    foreign = b'{"schemaVersion":2,"metricVersion":"future"}'
    path.write_bytes(foreign)
    with pytest.raises(ValueError, match="unknown activity schema"):
        publication.publish_native_activity("unused", tmp_path, now=now)
    assert path.read_bytes() == foreign
    path.unlink()
    monkeypatch.setattr(publication.psycopg, "connect", lambda *a, **kw: nullcontext(None))

    def project(*args, **kwargs):
        path.write_bytes(foreign)
        return fixture(now)

    monkeypatch.setattr(publication, "read_native_activity", project)
    with pytest.raises(ValueError, match="changed during projection"):
        publication.publish_native_activity("unused", tmp_path, now=now)
    assert path.read_bytes() == foreign
    assert not list(tmp_path.glob("*.pending"))
