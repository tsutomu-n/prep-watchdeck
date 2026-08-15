from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, LiteralString, cast

import psycopg
from psycopg import Connection

_MIGRATION_NAME = re.compile(r"^(?P<version>[0-9]{4})_(?P<name>[a-z][a-z0-9_]*)\.sql$")
_MIGRATION_LOCK_ID = 5_564_222_490_961_443_701
_MIGRATIONS_DIRECTORY = Path(__file__).resolve().parents[2] / "migrations"


class DatabaseError(RuntimeError):
    """A database operation failed without exposing connection credentials."""


class MigrationError(DatabaseError):
    """The migration history or a migration file is invalid."""


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    path: Path
    checksum: str
    sql: str


@dataclass(frozen=True, slots=True)
class MigrationResult:
    applied: tuple[int, ...]
    current_version: int
    pending: int


@dataclass(frozen=True, slots=True)
class DatabaseHealth:
    ready: bool
    current_version: int
    latest_version: int
    pending: int


def discover_migrations(directory: Path | None = None) -> tuple[Migration, ...]:
    migrations_directory = directory or _MIGRATIONS_DIRECTORY
    if not migrations_directory.is_dir():
        raise MigrationError("migration directory is missing")

    migrations: list[Migration] = []
    versions: set[int] = set()
    for path in sorted(migrations_directory.glob("*.sql")):
        match = _MIGRATION_NAME.fullmatch(path.name)
        if match is None:
            raise MigrationError(f"invalid migration filename: {path.name}")
        version = int(match.group("version"))
        if version in versions:
            raise MigrationError(f"duplicate migration version {version}")
        versions.add(version)
        content = path.read_bytes()
        try:
            migration_sql = content.decode("utf-8")
        except UnicodeDecodeError:
            raise MigrationError(f"migration {path.name} is not UTF-8") from None
        if not migration_sql.strip():
            raise MigrationError(f"migration {path.name} is empty")
        migrations.append(
            Migration(
                version=version,
                name=match.group("name"),
                path=path,
                checksum=hashlib.sha256(content).hexdigest(),
                sql=migration_sql,
            )
        )

    if not migrations:
        raise MigrationError("no migrations found")
    return tuple(migrations)


def migration_digest(migrations: Sequence[Migration]) -> str:
    digest = hashlib.sha256()
    for migration in migrations:
        digest.update(f"{migration.version}:{migration.name}:{migration.checksum}\n".encode())
    return digest.hexdigest()


def apply_migrations(
    connection: Connection[Any], migrations: Sequence[Migration] | None = None
) -> MigrationResult:
    ordered_migrations = tuple(migrations or discover_migrations())
    _validate_local_sequence(ordered_migrations)

    try:
        with connection.transaction(), connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", (_MIGRATION_LOCK_ID,))
            cursor.execute(
                """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version bigint PRIMARY KEY CHECK (version > 0),
                        name text NOT NULL,
                        checksum char(64) NOT NULL,
                        applied_at timestamptz NOT NULL DEFAULT clock_timestamp()
                    )
                """
            )
            cursor.execute(
                """
                    SELECT version, name, checksum
                    FROM schema_migrations
                    ORDER BY version
                """
            )
            applied_rows = tuple(cursor.fetchall())
            pending = _pending_migrations(ordered_migrations, applied_rows)

            applied_versions: list[int] = []
            for migration in pending:
                try:
                    # Migrations are trusted package code; checksums guard applied history.
                    cursor.execute(cast(LiteralString, migration.sql))
                    cursor.execute(
                        """
                            INSERT INTO schema_migrations (version, name, checksum)
                            VALUES (%s, %s, %s)
                        """,
                        (migration.version, migration.name, migration.checksum),
                    )
                except psycopg.Error as exc:
                    raise MigrationError(
                        f"migration {migration.version:04d}_{migration.name} failed"
                    ) from exc
                applied_versions.append(migration.version)
    except MigrationError:
        raise
    except psycopg.Error as exc:
        raise MigrationError("migration history could not be read") from exc

    current_version = ordered_migrations[-1].version
    return MigrationResult(
        applied=tuple(applied_versions),
        current_version=current_version,
        pending=0,
    )


def migrate_database(database_url: str) -> MigrationResult:
    try:
        with psycopg.connect(database_url, connect_timeout=5) as connection:
            return apply_migrations(connection)
    except MigrationError:
        raise
    except (psycopg.Error, OSError):
        raise DatabaseError("database migration failed") from None


def check_database(database_url: str) -> DatabaseHealth:
    migrations = discover_migrations()
    latest_version = migrations[-1].version
    try:
        with (
            psycopg.connect(database_url, connect_timeout=5) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute("SELECT to_regclass('schema_migrations')")
            table_row = cursor.fetchone()
            if table_row is None or table_row[0] is None:
                return DatabaseHealth(
                    ready=False,
                    current_version=0,
                    latest_version=latest_version,
                    pending=len(migrations),
                )
            cursor.execute(
                """
                    SELECT version, name, checksum
                    FROM schema_migrations
                    ORDER BY version
                """
            )
            applied_rows = tuple(cursor.fetchall())
            pending = _pending_migrations(migrations, applied_rows)
            current_version = int(applied_rows[-1][0]) if applied_rows else 0
            return DatabaseHealth(
                ready=not pending and current_version == latest_version,
                current_version=current_version,
                latest_version=latest_version,
                pending=len(pending),
            )
    except MigrationError:
        raise
    except (psycopg.Error, OSError):
        raise DatabaseError("database health check failed") from None


def _validate_local_sequence(migrations: Sequence[Migration]) -> None:
    if not migrations:
        raise MigrationError("no migrations found")
    versions = [migration.version for migration in migrations]
    if versions != sorted(versions):
        raise MigrationError("migrations are not ordered by version")
    if len(versions) != len(set(versions)):
        duplicate = next(version for version in versions if versions.count(version) > 1)
        raise MigrationError(f"duplicate migration version {duplicate}")


def _pending_migrations(
    migrations: Sequence[Migration], applied_rows: Sequence[tuple[Any, ...]]
) -> tuple[Migration, ...]:
    applied = [(int(row[0]), str(row[1]), str(row[2]).strip()) for row in applied_rows]
    if len(applied) > len(migrations):
        raise MigrationError("database migration history is newer than this application")

    for index, (version, name, checksum) in enumerate(applied):
        expected = migrations[index]
        if version != expected.version or name != expected.name:
            raise MigrationError("database migration history is not a local prefix")
        if checksum != expected.checksum:
            raise MigrationError(f"migration checksum mismatch at version {version}")
    return tuple(migrations[len(applied) :])
