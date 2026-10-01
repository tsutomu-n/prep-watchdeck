from __future__ import annotations

import os
from collections.abc import Iterator
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from prep_watchdeck_market.database import apply_migrations


@pytest.fixture(scope="module")
def isolated_feature_database(request: pytest.FixtureRequest) -> Iterator[None]:
    """Give multi-connection feature tests their own migrated disposable database."""
    source = os.environ.get("TEST_DATABASE_URL")
    if not source:
        yield
        return
    target = urlsplit(source)
    if (
        target.hostname != "127.0.0.1"
        or target.port in {None, 5432, 55432}
        or target.path != "/prep_watchdeck_test"
        or target.username != "prep_watchdeck_test"
    ):
        raise ValueError("isolated TEST_DATABASE_URL required")
    database = f"feature_test_{uuid4().hex}"
    url = urlunsplit(target._replace(path=f"/{database}"))
    module = request.module
    previous = module.TEST_DATABASE_URL
    with psycopg.connect(source, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        try:
            with psycopg.connect(url, autocommit=True) as connection:
                apply_migrations(connection)
            module.TEST_DATABASE_URL = url
            yield
        finally:
            module.TEST_DATABASE_URL = previous
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))
