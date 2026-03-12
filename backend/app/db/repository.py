from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import aiosqlite

from app.db.schema import SCHEMA_SQL
from app.domain.settings import UserSettings


@dataclass(slots=True)
class ChampionRecord:
    champion_id: int
    key: str
    name: str
    image_url: str
    roles: list[str]
    patch: str


@dataclass(slots=True)
class TierStatRecord:
    champion_id: int
    region: str
    rank_tier: str
    role: str
    tier_rank: int = 0
    win_rate: float = 0.0
    pick_rate: float = 0.0
    ban_rate: float = 0.0
    tier_grade: str = "B"
    pbi: float = 0.0
    games: int = 0
    scope_generation_id: str | None = None
    patch: str = ""
    source: str = ""
    fetched_at: str = ""


@dataclass(slots=True)
class MatchupRecord:
    champion_id: int
    opponent_id: int
    region: str
    rank_tier: str
    role: str
    opponent_role: str
    win_rate: float
    delta1: float
    delta2: float
    games: int
    patch: str
    source: str
    fetched_at: str


@dataclass(slots=True)
class SynergyRecord:
    champion_id: int
    teammate_id: int
    region: str
    rank_tier: str
    role: str
    teammate_role: str
    duo_win_rate: float
    synergy_delta: float
    normalised_delta: float
    games: int
    patch: str
    source: str
    fetched_at: str


@dataclass(slots=True)
class PatchGenerationRecord:
    patch: str
    is_active: bool
    detected_at: str
    ready_at: str | None
    scope_total: int
    ready_scopes: int
    partial_scopes: int
    stale_scopes: int
    failed_scopes: int
    notes: str


@dataclass(slots=True)
class ScopeStatusRecord:
    region: str
    rank_tier: str
    role: str
    patch: str
    status: str
    empty_scope: bool
    last_success_at: str | None
    last_error: str
    last_tier_refresh_at: str | None
    last_build_refresh_at: str | None
    next_tier_due_at: str | None
    next_build_due_at: str | None
    tier_rows: int
    matchup_rows: int
    synergy_rows: int
    http_ok: bool
    fallback_used: bool
    fallback_used_recently: bool
    fallback_failures: int
    tier_signature: str
    build_signature: str
    patch_generation_id: str | None
    updated_at: str


@dataclass(slots=True)
class ScopeRefreshJobRecord:
    id: int
    region: str
    rank_tier: str
    role: str
    patch: str
    mode: str
    status: str
    priority: int
    fallback_used: bool
    notes: str
    scheduled_at: str
    started_at: str | None
    finished_at: str | None


@dataclass(slots=True)
class ParserEventRecord:
    id: int
    region: str
    rank_tier: str
    role: str
    patch: str
    champion_id: int | None
    stage: str
    event_type: str
    severity: str
    used_fallback: bool
    message: str
    created_at: str


@dataclass(slots=True)
class BridgeSessionRecord:
    device_id: str
    label: str
    token_hash: str
    connected: bool
    last_seen_at: str | None
    auto_region: str | None
    auto_rank_tier: str | None
    client_patch: str | None
    queue_type: str | None
    source: str
    draft_state_json: str | None
    created_at: str
    updated_at: str


class DatabaseRepository:
    def __init__(self, connection: aiosqlite.Connection) -> None:
        self.connection = connection

    async def initialize(self) -> None:
        await self.connection.executescript(SCHEMA_SQL)
        await self._apply_migrations()
        await self._normalize_champion_image_urls()
        await self.connection.commit()
        await self.seed_default_settings()

    async def _apply_migrations(self) -> None:
        await self._ensure_column(
            table_name="tier_stats",
            column_name="tier_rank",
            column_sql="INTEGER NOT NULL DEFAULT 0",
        )
        await self._ensure_column(
            table_name="tier_stats",
            column_name="pbi",
            column_sql="REAL NOT NULL DEFAULT 0",
        )
        await self._ensure_column(
            table_name="tier_stats",
            column_name="scope_generation_id",
            column_sql="TEXT",
        )
        await self._ensure_column(
            table_name="synergies",
            column_name="normalised_delta",
            column_sql="REAL NOT NULL DEFAULT 0",
        )

    async def _ensure_column(self, *, table_name: str, column_name: str, column_sql: str) -> None:
        cursor = await self.connection.execute(f"PRAGMA table_info({table_name})")
        rows = await cursor.fetchall()
        existing_columns = {row["name"] for row in rows}
        if column_name in existing_columns:
            return
        await self.connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")

    async def _normalize_champion_image_urls(self) -> None:
        await self.connection.execute(
            """
            UPDATE champions
            SET image_url = REPLACE(image_url, '.png.png', '.png')
            WHERE image_url LIKE '%.png.png'
            """
        )

    async def seed_default_settings(self) -> None:
        settings = UserSettings().model_dump(mode="json")
        for key, value in settings.items():
            await self.connection.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, json.dumps(value)),
            )
        await self.connection.commit()

    async def get_settings(self) -> UserSettings:
        cursor = await self.connection.execute("SELECT key, value FROM settings")
        rows = await cursor.fetchall()
        data = {row["key"]: json.loads(row["value"]) for row in rows}
        return UserSettings.model_validate(data)

    async def update_settings(self, settings: UserSettings) -> UserSettings:
        payload = settings.model_dump(mode="json")
        for key, value in payload.items():
            await self.connection.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)),
            )
        await self.connection.commit()
        return settings

    async def upsert_champions(self, records: list[ChampionRecord]) -> None:
        await self.connection.executemany(
            """
            INSERT INTO champions (id, key, name, image_url, roles_json, patch, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                key = excluded.key,
                name = excluded.name,
                image_url = excluded.image_url,
                roles_json = excluded.roles_json,
                patch = excluded.patch,
                updated_at = excluded.updated_at
            """,
            [
                (
                    record.champion_id,
                    record.key,
                    record.name,
                    record.image_url,
                    json.dumps(record.roles),
                    record.patch,
                    datetime.now(UTC).isoformat(),
                )
                for record in records
            ],
        )
        await self.connection.commit()

    async def get_champion_lookup(self) -> dict[int, ChampionRecord]:
        cursor = await self.connection.execute("SELECT * FROM champions")
        rows = await cursor.fetchall()
        return {
            row["id"]: ChampionRecord(
                champion_id=row["id"],
                key=row["key"],
                name=row["name"],
                image_url=row["image_url"],
                roles=json.loads(row["roles_json"]),
                patch=row["patch"],
            )
            for row in rows
        }

    async def replace_tier_stats(self, *, region: str, rank_tier: str, role: str, patch: str, records: list[TierStatRecord]) -> None:
        await self.connection.execute(
            "DELETE FROM tier_stats WHERE region = ? AND rank_tier = ? AND role = ? AND patch = ?",
            (region, rank_tier, role, patch),
        )
        await self.connection.executemany(
            """
            INSERT INTO tier_stats (
                champion_id, region, rank_tier, role, tier_rank, win_rate, pick_rate,
                ban_rate, tier_grade, pbi, games, scope_generation_id, patch, source, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    record.champion_id,
                    record.region,
                    record.rank_tier,
                    record.role,
                    record.tier_rank,
                    record.win_rate,
                    record.pick_rate,
                    record.ban_rate,
                    record.tier_grade,
                    record.pbi,
                    record.games,
                    record.scope_generation_id,
                    record.patch,
                    record.source,
                    record.fetched_at,
                )
                for record in records
            ],
        )
        await self.connection.commit()

    async def replace_matchups(self, *, region: str, rank_tier: str, role: str, patch: str, records: list[MatchupRecord]) -> None:
        await self.connection.execute(
            "DELETE FROM matchups WHERE region = ? AND rank_tier = ? AND role = ? AND patch = ?",
            (region, rank_tier, role, patch),
        )
        if records:
            await self.connection.executemany(
                """
                INSERT INTO matchups (
                    champion_id, opponent_id, region, rank_tier, role, opponent_role,
                    win_rate, delta1, delta2, games, patch, source, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        record.champion_id,
                        record.opponent_id,
                        record.region,
                        record.rank_tier,
                        record.role,
                        record.opponent_role,
                        record.win_rate,
                        record.delta1,
                        record.delta2,
                        record.games,
                        record.patch,
                        record.source,
                        record.fetched_at,
                    )
                    for record in records
                ],
            )
        await self.connection.commit()

    async def replace_synergies(self, *, region: str, rank_tier: str, role: str, patch: str, records: list[SynergyRecord]) -> None:
        await self.connection.execute(
            "DELETE FROM synergies WHERE region = ? AND rank_tier = ? AND role = ? AND patch = ?",
            (region, rank_tier, role, patch),
        )
        if records:
            await self.connection.executemany(
                """
                INSERT INTO synergies (
                    champion_id, teammate_id, region, rank_tier, role, teammate_role,
                    duo_win_rate, synergy_delta, normalised_delta, games, patch, source, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        record.champion_id,
                        record.teammate_id,
                        record.region,
                        record.rank_tier,
                        record.role,
                        record.teammate_role,
                        record.duo_win_rate,
                        record.synergy_delta,
                        record.normalised_delta,
                        record.games,
                        record.patch,
                        record.source,
                        record.fetched_at,
                    )
                    for record in records
                ],
            )
        await self.connection.commit()

    async def start_provider_run(
        self,
        *,
        provider_name: str,
        region: str,
        rank_tier: str,
        role: str,
        patch: str,
        pages_total: int,
        notes: str = "",
    ) -> int:
        cursor = await self.connection.execute(
            """
            INSERT INTO provider_runs (
                provider_name, region, rank_tier, role, patch, status,
                pages_total, pages_done, retries, started_at, notes
            ) VALUES (?, ?, ?, ?, ?, 'running', ?, 0, 0, ?, ?)
            """,
            (provider_name, region, rank_tier, role, patch, pages_total, datetime.now(UTC).isoformat(), notes),
        )
        await self.connection.commit()
        return int(cursor.lastrowid)

    async def complete_provider_run(self, run_id: int, *, status: str, pages_done: int, notes: str = "") -> None:
        await self.connection.execute(
            """
            UPDATE provider_runs
            SET status = ?, pages_done = ?, finished_at = ?, notes = ?
            WHERE id = ?
            """,
            (status, pages_done, datetime.now(UTC).isoformat(), notes, run_id),
        )
        await self.connection.commit()

    async def latest_provider_run(
        self,
        *,
        provider_name: str,
        region: str,
        rank_tier: str,
        role: str,
        patch: str,
    ) -> dict[str, Any] | None:
        cursor = await self.connection.execute(
            """
            SELECT * FROM provider_runs
            WHERE provider_name = ? AND region = ? AND rank_tier = ? AND role = ? AND patch = ?
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (provider_name, region, rank_tier, role, patch),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def fail_stale_provider_runs(self, *, started_before: str) -> int:
        cursor = await self.connection.execute(
            """
            UPDATE provider_runs
            SET status = 'failed',
                finished_at = COALESCE(finished_at, ?),
                notes = CASE
                    WHEN notes = '' THEN 'Marked failed after stale running scrape'
                    ELSE notes || ' | Marked failed after stale running scrape'
                END
            WHERE status = 'running' AND started_at < ?
            """,
            (datetime.now(UTC).isoformat(), started_before),
        )
        await self.connection.commit()
        return int(cursor.rowcount or 0)

    async def latest_patch(self) -> str | None:
        cursor = await self.connection.execute("SELECT patch FROM champions ORDER BY updated_at DESC LIMIT 1")
        row = await cursor.fetchone()
        return row["patch"] if row else None

    async def purge_stale_data(self, *, patch: str) -> dict[str, int]:
        deleted: dict[str, int] = {}
        for table_name in ("tier_stats", "matchups", "synergies"):
            cursor = await self.connection.execute(
                f"SELECT COUNT(*) AS value FROM {table_name} WHERE patch <> ?",
                (patch,),
            )
            deleted[table_name] = int((await cursor.fetchone())["value"])
            await self.connection.execute(f"DELETE FROM {table_name} WHERE patch <> ?", (patch,))
        await self.connection.commit()
        return deleted

    async def data_patches(self) -> list[str]:
        cursor = await self.connection.execute(
            """
            SELECT DISTINCT patch FROM (
                SELECT patch FROM tier_stats
                UNION
                SELECT patch FROM matchups
                UNION
                SELECT patch FROM synergies
            )
            ORDER BY patch DESC
            """
        )
        rows = await cursor.fetchall()
        return [str(row["patch"]) for row in rows if row["patch"]]

    async def status_snapshot(self) -> dict[str, Any]:
        latest_patch = await self.latest_patch()
        snapshot: dict[str, Any] = {}
        cursor = await self.connection.execute("SELECT COUNT(*) AS value FROM champions")
        snapshot["champion_count"] = int((await cursor.fetchone())["value"])
        snapshot["latest_patch"] = latest_patch

        scope_rollup = None
        if latest_patch:
            cursor = await self.connection.execute(
                """
                SELECT
                    COUNT(*) AS scope_count,
                    COALESCE(SUM(tier_rows), 0) AS tier_stats_count,
                    COALESCE(SUM(matchup_rows), 0) AS matchups_count,
                    COALESCE(SUM(synergy_rows), 0) AS synergies_count,
                    MAX(COALESCE(last_build_refresh_at, last_tier_refresh_at, last_success_at)) AS latest_data_fetch_at
                FROM scope_status
                WHERE patch = ?
                """,
                (latest_patch,),
            )
            scope_rollup = await cursor.fetchone()

        if latest_patch and scope_rollup and int(scope_rollup["scope_count"] or 0) > 0:
            snapshot["tier_stats_count"] = int(scope_rollup["tier_stats_count"] or 0)
            snapshot["matchups_count"] = int(scope_rollup["matchups_count"] or 0)
            snapshot["synergies_count"] = int(scope_rollup["synergies_count"] or 0)
            snapshot["latest_data_fetch_at"] = scope_rollup["latest_data_fetch_at"]
            cursor = await self.connection.execute(
                """
                SELECT
                    COALESCE(SUM(tier_rows), 0) + COALESCE(SUM(matchup_rows), 0) + COALESCE(SUM(synergy_rows), 0) AS value
                FROM scope_status
                WHERE patch <> ?
                """,
                (latest_patch,),
            )
            snapshot["historical_rows"] = int((await cursor.fetchone())["value"] or 0)
            cursor = await self.connection.execute("SELECT DISTINCT patch FROM scope_status WHERE patch <> ? ORDER BY patch", (latest_patch,))
            snapshot["data_patches"] = [row["patch"] for row in await cursor.fetchall()]
        else:
            queries = {
                "tier_stats_count": (
                    "SELECT COUNT(*) AS value FROM tier_stats WHERE patch = ?",
                    (latest_patch,),
                ),
                "matchups_count": (
                    "SELECT COUNT(*) AS value FROM matchups WHERE patch = ?",
                    (latest_patch,),
                ),
                "synergies_count": (
                    "SELECT COUNT(*) AS value FROM synergies WHERE patch = ?",
                    (latest_patch,),
                ),
            }
            for key, (query, params) in queries.items():
                if latest_patch is None:
                    snapshot[key] = 0
                    continue
                cursor = await self.connection.execute(query, params)
                snapshot[key] = int((await cursor.fetchone())["value"])

            snapshot["data_patches"] = [
                patch_name for patch_name in await self.data_patches() if patch_name != latest_patch
            ]

            if latest_patch:
                historical_rows = 0
                for table_name in ("tier_stats", "matchups", "synergies"):
                    cursor = await self.connection.execute(
                        f"SELECT COUNT(*) AS value FROM {table_name} WHERE patch <> ?",
                        (latest_patch,),
                    )
                    historical_rows += int((await cursor.fetchone())["value"])
                snapshot["historical_rows"] = historical_rows

                cursor = await self.connection.execute(
                    """
                    SELECT MAX(fetched_at) AS value FROM (
                        SELECT fetched_at FROM tier_stats WHERE patch = ?
                        UNION ALL
                        SELECT fetched_at FROM matchups WHERE patch = ?
                        UNION ALL
                        SELECT fetched_at FROM synergies WHERE patch = ?
                    )
                    """,
                    (latest_patch, latest_patch, latest_patch),
                )
                fetched_row = await cursor.fetchone()
                snapshot["latest_data_fetch_at"] = fetched_row["value"] if fetched_row else None
            else:
                snapshot["historical_rows"] = 0
                snapshot["latest_data_fetch_at"] = None

        cursor = await self.connection.execute("SELECT * FROM provider_runs ORDER BY started_at DESC LIMIT 1")
        latest_run = await cursor.fetchone()
        snapshot["latest_run"] = dict(latest_run) if latest_run else None
        active_generation = await self.active_patch_generation()
        snapshot["active_patch_generation"] = (
            {
                "patch": active_generation.patch,
                "scope_total": active_generation.scope_total,
                "ready_scopes": active_generation.ready_scopes,
                "partial_scopes": active_generation.partial_scopes,
                "stale_scopes": active_generation.stale_scopes,
                "failed_scopes": active_generation.failed_scopes,
                "ready_at": active_generation.ready_at,
            }
            if active_generation
            else None
        )
        return snapshot

    async def upsert_patch_generation(self, *, patch: str, is_active: bool, scope_total: int, notes: str = "") -> None:
        now = datetime.now(UTC).isoformat()
        if is_active:
            await self.connection.execute("UPDATE patch_generations SET is_active = 0 WHERE is_active = 1")
        await self.connection.execute(
            """
            INSERT INTO patch_generations (
                patch, is_active, detected_at, scope_total, notes
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(patch) DO UPDATE SET
                is_active = excluded.is_active,
                scope_total = excluded.scope_total,
                notes = CASE WHEN excluded.notes <> '' THEN excluded.notes ELSE patch_generations.notes END
            """,
            (patch, 1 if is_active else 0, now, scope_total, notes),
        )
        await self.connection.commit()

    async def refresh_patch_generation_metrics(self, *, patch: str) -> None:
        cursor = await self.connection.execute(
            """
            SELECT
                COUNT(*) AS scope_total,
                SUM(CASE WHEN status = 'ready' THEN 1 ELSE 0 END) AS ready_scopes,
                SUM(CASE WHEN status = 'partial' THEN 1 ELSE 0 END) AS partial_scopes,
                SUM(CASE WHEN status = 'stale' THEN 1 ELSE 0 END) AS stale_scopes,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_scopes
            FROM scope_status
            WHERE patch = ?
            """,
            (patch,),
        )
        row = await cursor.fetchone()
        if row is None:
            return
        ready_at: str | None = None
        scope_total = int(row["scope_total"] or 0)
        ready_scopes = int(row["ready_scopes"] or 0)
        partial_scopes = int(row["partial_scopes"] or 0)
        stale_scopes = int(row["stale_scopes"] or 0)
        failed_scopes = int(row["failed_scopes"] or 0)
        if scope_total > 0 and ready_scopes == scope_total and partial_scopes == 0 and stale_scopes == 0 and failed_scopes == 0:
            ready_at = datetime.now(UTC).isoformat()
        await self.connection.execute(
            """
            UPDATE patch_generations
            SET ready_at = COALESCE(?, ready_at),
                scope_total = ?,
                ready_scopes = ?,
                partial_scopes = ?,
                stale_scopes = ?,
                failed_scopes = ?
            WHERE patch = ?
            """,
            (ready_at, scope_total, ready_scopes, partial_scopes, stale_scopes, failed_scopes, patch),
        )
        await self.connection.commit()

    async def active_patch_generation(self) -> PatchGenerationRecord | None:
        cursor = await self.connection.execute(
            "SELECT * FROM patch_generations WHERE is_active = 1 ORDER BY detected_at DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        return self._patch_generation_from_row(row) if row else None

    async def list_patch_generations(self) -> list[PatchGenerationRecord]:
        cursor = await self.connection.execute("SELECT * FROM patch_generations ORDER BY detected_at DESC")
        rows = await cursor.fetchall()
        return [self._patch_generation_from_row(row) for row in rows]

    async def upsert_scope_status(
        self,
        *,
        region: str,
        rank_tier: str,
        role: str,
        patch: str,
        status: str,
        empty_scope: bool,
        last_success_at: str | None,
        last_error: str,
        last_tier_refresh_at: str | None,
        last_build_refresh_at: str | None,
        next_tier_due_at: str | None,
        next_build_due_at: str | None,
        tier_rows: int,
        matchup_rows: int,
        synergy_rows: int,
        http_ok: bool,
        fallback_used: bool,
        fallback_failures: int,
        tier_signature: str,
        build_signature: str,
        patch_generation_id: str | None,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        await self.connection.execute(
            """
            INSERT INTO scope_status (
                region, rank_tier, role, patch, status, empty_scope, last_success_at, last_error,
                last_tier_refresh_at, last_build_refresh_at, next_tier_due_at, next_build_due_at,
                tier_rows, matchup_rows, synergy_rows, http_ok, fallback_used, fallback_used_recently,
                fallback_failures, tier_signature, build_signature, patch_generation_id, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(region, rank_tier, role, patch) DO UPDATE SET
                status = excluded.status,
                empty_scope = excluded.empty_scope,
                last_success_at = excluded.last_success_at,
                last_error = excluded.last_error,
                last_tier_refresh_at = excluded.last_tier_refresh_at,
                last_build_refresh_at = excluded.last_build_refresh_at,
                next_tier_due_at = excluded.next_tier_due_at,
                next_build_due_at = excluded.next_build_due_at,
                tier_rows = excluded.tier_rows,
                matchup_rows = excluded.matchup_rows,
                synergy_rows = excluded.synergy_rows,
                http_ok = excluded.http_ok,
                fallback_used = excluded.fallback_used,
                fallback_used_recently = excluded.fallback_used_recently,
                fallback_failures = excluded.fallback_failures,
                tier_signature = excluded.tier_signature,
                build_signature = excluded.build_signature,
                patch_generation_id = excluded.patch_generation_id,
                updated_at = excluded.updated_at
            """,
            (
                region,
                rank_tier,
                role,
                patch,
                status,
                1 if empty_scope else 0,
                last_success_at,
                last_error,
                last_tier_refresh_at,
                last_build_refresh_at,
                next_tier_due_at,
                next_build_due_at,
                tier_rows,
                matchup_rows,
                synergy_rows,
                1 if http_ok else 0,
                1 if fallback_used else 0,
                1 if fallback_used else 0,
                fallback_failures,
                tier_signature,
                build_signature,
                patch_generation_id,
                now,
            ),
        )
        await self.connection.commit()

    async def get_scope_status(self, *, region: str, rank_tier: str, role: str, patch: str) -> ScopeStatusRecord | None:
        cursor = await self.connection.execute(
            """
            SELECT * FROM scope_status
            WHERE region = ? AND rank_tier = ? AND role = ? AND patch = ?
            LIMIT 1
            """,
            (region, rank_tier, role, patch),
        )
        row = await cursor.fetchone()
        return self._scope_status_from_row(row) if row else None

    async def list_scope_status(
        self,
        *,
        patch: str | None = None,
        region: str | None = None,
        rank_tier: str | None = None,
        role: str | None = None,
    ) -> list[ScopeStatusRecord]:
        clauses: list[str] = []
        params: list[Any] = []
        if patch is not None:
            clauses.append("patch = ?")
            params.append(patch)
        if region is not None:
            clauses.append("region = ?")
            params.append(region)
        if rank_tier is not None:
            clauses.append("rank_tier = ?")
            params.append(rank_tier)
        if role is not None:
            clauses.append("role = ?")
            params.append(role)

        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        cursor = await self.connection.execute(
            f"SELECT * FROM scope_status {where_clause} ORDER BY region, rank_tier, role",
            params,
        )
        rows = await cursor.fetchall()
        return [self._scope_status_from_row(row) for row in rows]

    async def start_scope_refresh_job(
        self,
        *,
        region: str,
        rank_tier: str,
        role: str,
        patch: str,
        mode: str,
        priority: int,
        notes: str = "",
    ) -> int:
        now = datetime.now(UTC).isoformat()
        cursor = await self.connection.execute(
            """
            INSERT INTO scope_refresh_jobs (
                region, rank_tier, role, patch, mode, status, priority, notes, scheduled_at, started_at
            ) VALUES (?, ?, ?, ?, ?, 'running', ?, ?, ?, ?)
            """,
            (region, rank_tier, role, patch, mode, priority, notes, now, now),
        )
        await self.connection.commit()
        return int(cursor.lastrowid)

    async def complete_scope_refresh_job(
        self,
        job_id: int,
        *,
        status: str,
        fallback_used: bool,
        notes: str = "",
    ) -> None:
        await self.connection.execute(
            """
            UPDATE scope_refresh_jobs
            SET status = ?, fallback_used = ?, notes = ?, finished_at = ?
            WHERE id = ?
            """,
            (status, 1 if fallback_used else 0, notes, datetime.now(UTC).isoformat(), job_id),
        )
        await self.connection.commit()

    async def list_scope_refresh_jobs(self, *, limit: int = 50) -> list[ScopeRefreshJobRecord]:
        cursor = await self.connection.execute(
            "SELECT * FROM scope_refresh_jobs ORDER BY COALESCE(finished_at, started_at, scheduled_at) DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [self._scope_refresh_job_from_row(row) for row in rows]

    async def record_parser_event(
        self,
        *,
        region: str,
        rank_tier: str,
        role: str,
        patch: str,
        stage: str,
        event_type: str,
        severity: str,
        message: str,
        champion_id: int | None = None,
        used_fallback: bool = False,
    ) -> None:
        await self.connection.execute(
            """
            INSERT INTO parser_events (
                region, rank_tier, role, patch, champion_id, stage, event_type, severity, used_fallback, message, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                region,
                rank_tier,
                role,
                patch,
                champion_id,
                stage,
                event_type,
                severity,
                1 if used_fallback else 0,
                message,
                datetime.now(UTC).isoformat(),
            ),
        )
        await self.connection.commit()

    async def parser_health_snapshot(self) -> dict[str, Any]:
        since = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
        summary_cursor = await self.connection.execute(
            """
            SELECT
                COUNT(*) AS total_events,
                SUM(CASE WHEN used_fallback = 1 THEN 1 ELSE 0 END) AS fallback_events,
                SUM(CASE WHEN severity = 'error' THEN 1 ELSE 0 END) AS error_events
            FROM parser_events
            WHERE created_at >= ?
            """,
            (since,),
        )
        summary = await summary_cursor.fetchone()
        recent_cursor = await self.connection.execute(
            "SELECT * FROM parser_events ORDER BY created_at DESC LIMIT 50"
        )
        rows = await recent_cursor.fetchall()
        return {
            "window_hours": 24,
            "total_events": int(summary["total_events"] or 0),
            "fallback_events": int(summary["fallback_events"] or 0),
            "error_events": int(summary["error_events"] or 0),
            "recent": [
                {
                    "id": event.id,
                    "region": event.region,
                    "rank_tier": event.rank_tier,
                    "role": event.role,
                    "patch": event.patch,
                    "champion_id": event.champion_id,
                    "stage": event.stage,
                    "event_type": event.event_type,
                    "severity": event.severity,
                    "used_fallback": event.used_fallback,
                    "message": event.message,
                    "created_at": event.created_at,
                }
                for event in (self._parser_event_from_row(row) for row in rows)
            ],
        }

    async def upsert_bridge_session(
        self,
        *,
        device_id: str,
        label: str,
        token_hash: str,
        connected: bool,
        auto_region: str | None = None,
        auto_rank_tier: str | None = None,
        client_patch: str | None = None,
        queue_type: str | None = None,
        draft_state_json: str | None = None,
        source: str = "bridge",
    ) -> None:
        now = datetime.now(UTC).isoformat()
        await self.connection.execute(
            """
            INSERT INTO bridge_sessions (
                device_id, label, token_hash, connected, last_seen_at, auto_region, auto_rank_tier,
                client_patch, queue_type, source, draft_state_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(device_id) DO UPDATE SET
                label = excluded.label,
                token_hash = excluded.token_hash,
                connected = excluded.connected,
                last_seen_at = excluded.last_seen_at,
                auto_region = excluded.auto_region,
                auto_rank_tier = excluded.auto_rank_tier,
                client_patch = excluded.client_patch,
                queue_type = excluded.queue_type,
                source = excluded.source,
                draft_state_json = COALESCE(excluded.draft_state_json, bridge_sessions.draft_state_json),
                updated_at = excluded.updated_at
            """,
            (
                device_id,
                label,
                token_hash,
                1 if connected else 0,
                now,
                auto_region,
                auto_rank_tier,
                client_patch,
                queue_type,
                source,
                draft_state_json,
                now,
                now,
            ),
        )
        await self.connection.commit()

    async def delete_bridge_session(self, *, device_id: str) -> None:
        await self.connection.execute("DELETE FROM bridge_sessions WHERE device_id = ?", (device_id,))
        await self.connection.commit()

    async def expire_bridge_sessions(self, *, stale_before: str) -> list[BridgeSessionRecord]:
        cursor = await self.connection.execute(
            """
            SELECT * FROM bridge_sessions
            WHERE connected = 1 AND COALESCE(last_seen_at, updated_at) < ?
            """,
            (stale_before,),
        )
        rows = await cursor.fetchall()
        if rows:
            await self.connection.execute(
                """
                UPDATE bridge_sessions
                SET connected = 0, updated_at = ?
                WHERE connected = 1 AND COALESCE(last_seen_at, updated_at) < ?
                """,
                (datetime.now(UTC).isoformat(), stale_before),
            )
            await self.connection.commit()
        return [self._bridge_session_from_row(row) for row in rows]

    async def latest_bridge_session(self) -> BridgeSessionRecord | None:
        cursor = await self.connection.execute(
            """
            SELECT * FROM bridge_sessions
            WHERE connected = 1
            ORDER BY COALESCE(last_seen_at, updated_at) DESC
            LIMIT 1
            """
        )
        row = await cursor.fetchone()
        return self._bridge_session_from_row(row) if row else None

    async def get_bridge_session(self, *, device_id: str) -> BridgeSessionRecord | None:
        cursor = await self.connection.execute(
            """
            SELECT * FROM bridge_sessions
            WHERE device_id = ?
            LIMIT 1
            """,
            (device_id,),
        )
        row = await cursor.fetchone()
        return self._bridge_session_from_row(row) if row else None

    async def list_bridge_sessions(self) -> list[BridgeSessionRecord]:
        cursor = await self.connection.execute(
            "SELECT * FROM bridge_sessions ORDER BY COALESCE(last_seen_at, updated_at) DESC"
        )
        rows = await cursor.fetchall()
        return [self._bridge_session_from_row(row) for row in rows]

    def _patch_generation_from_row(self, row: Any) -> PatchGenerationRecord:
        return PatchGenerationRecord(
            patch=row["patch"],
            is_active=bool(row["is_active"]),
            detected_at=row["detected_at"],
            ready_at=row["ready_at"],
            scope_total=int(row["scope_total"]),
            ready_scopes=int(row["ready_scopes"]),
            partial_scopes=int(row["partial_scopes"]),
            stale_scopes=int(row["stale_scopes"]),
            failed_scopes=int(row["failed_scopes"]),
            notes=row["notes"],
        )

    def _scope_status_from_row(self, row: Any) -> ScopeStatusRecord:
        return ScopeStatusRecord(
            region=row["region"],
            rank_tier=row["rank_tier"],
            role=row["role"],
            patch=row["patch"],
            status=row["status"],
            empty_scope=bool(row["empty_scope"]),
            last_success_at=row["last_success_at"],
            last_error=row["last_error"],
            last_tier_refresh_at=row["last_tier_refresh_at"],
            last_build_refresh_at=row["last_build_refresh_at"],
            next_tier_due_at=row["next_tier_due_at"],
            next_build_due_at=row["next_build_due_at"],
            tier_rows=int(row["tier_rows"]),
            matchup_rows=int(row["matchup_rows"]),
            synergy_rows=int(row["synergy_rows"]),
            http_ok=bool(row["http_ok"]),
            fallback_used=bool(row["fallback_used"]),
            fallback_used_recently=bool(row["fallback_used_recently"]),
            fallback_failures=int(row["fallback_failures"]),
            tier_signature=row["tier_signature"],
            build_signature=row["build_signature"],
            patch_generation_id=row["patch_generation_id"],
            updated_at=row["updated_at"],
        )

    def _scope_refresh_job_from_row(self, row: Any) -> ScopeRefreshJobRecord:
        return ScopeRefreshJobRecord(
            id=int(row["id"]),
            region=row["region"],
            rank_tier=row["rank_tier"],
            role=row["role"],
            patch=row["patch"],
            mode=row["mode"],
            status=row["status"],
            priority=int(row["priority"]),
            fallback_used=bool(row["fallback_used"]),
            notes=row["notes"],
            scheduled_at=row["scheduled_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )

    def _parser_event_from_row(self, row: Any) -> ParserEventRecord:
        return ParserEventRecord(
            id=int(row["id"]),
            region=row["region"],
            rank_tier=row["rank_tier"],
            role=row["role"],
            patch=row["patch"],
            champion_id=row["champion_id"],
            stage=row["stage"],
            event_type=row["event_type"],
            severity=row["severity"],
            used_fallback=bool(row["used_fallback"]),
            message=row["message"],
            created_at=row["created_at"],
        )

    def _bridge_session_from_row(self, row: Any) -> BridgeSessionRecord:
        return BridgeSessionRecord(
            device_id=row["device_id"],
            label=row["label"],
            token_hash=row["token_hash"],
            connected=bool(row["connected"]),
            last_seen_at=row["last_seen_at"],
            auto_region=row["auto_region"],
            auto_rank_tier=row["auto_rank_tier"],
            client_patch=row["client_patch"],
            queue_type=row["queue_type"],
            source=row["source"],
            draft_state_json=row["draft_state_json"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def load_tier_stats(self, *, region: str, rank_tier: str, role: str, patch: str) -> list[TierStatRecord]:
        cursor = await self.connection.execute(
            "SELECT * FROM tier_stats WHERE region = ? AND rank_tier = ? AND role = ? AND patch = ?",
            (region, rank_tier, role, patch),
        )
        rows = await cursor.fetchall()
        return [TierStatRecord(**dict(row)) for row in rows]

    async def load_matchups(self, *, region: str, rank_tier: str, role: str, patch: str) -> list[MatchupRecord]:
        cursor = await self.connection.execute(
            "SELECT * FROM matchups WHERE region = ? AND rank_tier = ? AND role = ? AND patch = ?",
            (region, rank_tier, role, patch),
        )
        rows = await cursor.fetchall()
        return [MatchupRecord(**dict(row)) for row in rows]

    async def load_synergies(self, *, region: str, rank_tier: str, role: str, patch: str) -> list[SynergyRecord]:
        cursor = await self.connection.execute(
            "SELECT * FROM synergies WHERE region = ? AND rank_tier = ? AND role = ? AND patch = ?",
            (region, rank_tier, role, patch),
        )
        rows = await cursor.fetchall()
        return [SynergyRecord(**dict(row)) for row in rows]

    async def load_all_tier_stats(self, *, patch: str) -> list[TierStatRecord]:
        cursor = await self.connection.execute("SELECT * FROM tier_stats WHERE patch = ?", (patch,))
        rows = await cursor.fetchall()
        return [TierStatRecord(**dict(row)) for row in rows]

    async def load_all_matchups(self, *, patch: str) -> list[MatchupRecord]:
        cursor = await self.connection.execute("SELECT * FROM matchups WHERE patch = ?", (patch,))
        rows = await cursor.fetchall()
        return [MatchupRecord(**dict(row)) for row in rows]

    async def load_all_synergies(self, *, patch: str) -> list[SynergyRecord]:
        cursor = await self.connection.execute("SELECT * FROM synergies WHERE patch = ?", (patch,))
        rows = await cursor.fetchall()
        return [SynergyRecord(**dict(row)) for row in rows]

    async def scope_counts(self, *, region: str, rank_tier: str, role: str, patch: str) -> dict[str, int]:
        queries = {
            "tier_stats": "SELECT COUNT(*) AS value FROM tier_stats WHERE region = ? AND rank_tier = ? AND role = ? AND patch = ?",
            "matchups": "SELECT COUNT(*) AS value FROM matchups WHERE region = ? AND rank_tier = ? AND role = ? AND patch = ?",
            "synergies": "SELECT COUNT(*) AS value FROM synergies WHERE region = ? AND rank_tier = ? AND role = ? AND patch = ?",
        }
        counts: dict[str, int] = {}
        for key, query in queries.items():
            cursor = await self.connection.execute(query, (region, rank_tier, role, patch))
            counts[key] = int((await cursor.fetchone())["value"])
        return counts
