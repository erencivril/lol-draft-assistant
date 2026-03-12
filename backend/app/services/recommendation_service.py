from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
import json
import logging
import sqlite3

from app.db.repository import ChampionRecord, DatabaseRepository, MatchupRecord, SynergyRecord, TierStatRecord
from app.domain.draft import DraftState, RoleCandidate, TeamSlot
from app.domain.recommendation import RecommendationBundle, RecommendationItem
from app.domain.ranks import normalize_rank_tier
from app.domain.regions import normalize_region
from app.domain.roles import normalize_role_name
from app.domain.settings import ResolvedFilters, UserSettings

from .explanation_builder import (
    build_ban_explanation,
    build_pick_explanation,
    combined_scenario_summary,
    matchup_insight,
    sample_penalty_note,
    synergy_insight,
)
from .role_inference import ResolvedTeamContext, resolve_team_context
from .scoring import (
    TierCandidate,
    combine_metric,
    compose_ban_score,
    compose_predraft_pick_score,
    compose_pick_score,
    display_band,
    evidence_score,
    has_thin_evidence,
    low_sample_penalty,
    normalize_delta,
    normalize_synergy,
    role_fit_score,
    summarize_relations,
    tier_score,
)
from .scoring_constants import (
    BAN_CONFIDENCE_BASE,
    BAN_CONFIDENCE_CERTAINTY_WEIGHT,
    BAN_CONFIDENCE_EVIDENCE_WEIGHT,
    BAN_CONFIDENCE_GAMES_DIVISOR,
    BAN_CONFIDENCE_GAMES_MAX,
    BAN_CONFIDENCE_SAMPLE_WEIGHT,
    CONFIDENCE_CAP_INCOMPLETE_SCOPE,
    CONFIDENCE_CAP_PATCH_MISMATCH,
    PICK_CONFIDENCE_BASE,
    PICK_CONFIDENCE_CERTAINTY_WEIGHT,
    PICK_CONFIDENCE_EVIDENCE_WEIGHT,
    PICK_CONFIDENCE_GAMES_DIVISOR,
    PICK_CONFIDENCE_GAMES_MAX,
    PICK_CONFIDENCE_SAMPLE_WEIGHT,
    SUPPORTED_ROLES,
    THIN_EVIDENCE_MULTIPLIER,
)


@dataclass(slots=True)
class RecommendationRuntimeSnapshot:
    draft_state: DraftState
    recommendations: RecommendationBundle


@dataclass(slots=True)
class IndexSnapshot:
    patch: str | None
    champion_lookup: dict[int, ChampionRecord]
    tier_index: dict[tuple[str, str, str, int], TierStatRecord]
    tier_scope_index: dict[tuple[str, str, str], list[TierStatRecord]]
    matchup_index: dict[tuple[str, str, str, str, int, int], MatchupRecord]
    synergy_index: dict[tuple[str, str, str, str, int, int], SynergyRecord]


class RecommendationService:
    def __init__(self, repository: DatabaseRepository) -> None:
        self.repository = repository
        self.patch: str | None = None
        self._indexes_ready = False
        self.champion_lookup: dict[int, ChampionRecord] = {}
        self.tier_index: dict[tuple[str, str, str, int], TierStatRecord] = {}
        self.tier_scope_index: dict[tuple[str, str, str], list[TierStatRecord]] = defaultdict(list)
        self.matchup_index: dict[tuple[str, str, str, str, int, int], MatchupRecord] = {}
        self.synergy_index: dict[tuple[str, str, str, str, int, int], SynergyRecord] = {}
        self._rebuild_lock = asyncio.Lock()
        self._rebuild_task: asyncio.Task[None] | None = None
        self._champion_lookup_lock = asyncio.Lock()
        self._scope_cache_lock = asyncio.Lock()
        self._loaded_tier_scopes: set[tuple[str, str, str, str]] = set()
        self._loaded_matchup_scopes: set[tuple[str, str, str, str]] = set()
        self._loaded_synergy_scopes: set[tuple[str, str, str, str]] = set()
        self._logger = logging.getLogger("lda.services.recommendation_service")
        self._database_path: str | None = None

    async def rebuild_indexes(self) -> None:
        async with self._rebuild_lock:
            self._logger.info("Rebuilding recommendation indexes")
            self._indexes_ready = False
            snapshot = await self._load_index_snapshot()

            self.patch = snapshot.patch
            self.champion_lookup = snapshot.champion_lookup
            self.tier_index = snapshot.tier_index
            self.tier_scope_index = snapshot.tier_scope_index
            self.matchup_index = snapshot.matchup_index
            self.synergy_index = snapshot.synergy_index

            if not snapshot.patch:
                self._indexes_ready = True
                self._logger.info("Recommendation indexes rebuilt with no active patch data")
                return

            self._indexes_ready = True
            self._logger.info(
                "Recommendation indexes ready for patch %s (%s tiers, %s matchups, %s synergies)",
                self.patch,
                len(self.tier_index),
                len(self.matchup_index),
                len(self.synergy_index),
            )

    async def ensure_indexes_ready(self, *, wait: bool = True) -> bool:
        if self._indexes_ready:
            return True
        if self._rebuild_task and not self._rebuild_task.done():
            if wait:
                await self._rebuild_task
            return self._indexes_ready
        if wait:
            await self.rebuild_indexes()
            return self._indexes_ready
        self.warm_indexes_in_background()
        return False

    async def ensure_champion_lookup_ready(self) -> None:
        if self.champion_lookup:
            return
        async with self._champion_lookup_lock:
            if self.champion_lookup:
                return
            try:
                self.champion_lookup = await self.repository.get_champion_lookup()
                if self.patch is None:
                    self.patch = await self.repository.latest_patch()
            except Exception:
                self._logger.exception("Failed to prime champion lookup")

    async def ensure_runtime_scope_ready(self, *, region: str, rank_tier: str, relation_roles: set[str]) -> bool:
        patch = await self._ensure_patch_current()
        if not patch:
            return False
        await self._ensure_tier_scope_loaded(region=region, rank_tier=rank_tier, patch=patch, roles=set(SUPPORTED_ROLES))
        if relation_roles:
            await self._ensure_matchup_scope_loaded(region=region, rank_tier=rank_tier, patch=patch, roles=relation_roles)
            await self._ensure_synergy_scope_loaded(region=region, rank_tier=rank_tier, patch=patch, roles=relation_roles)
        return True

    async def _ensure_patch_current(self) -> str | None:
        latest_patch = await self.repository.latest_patch()
        if latest_patch == self.patch:
            return latest_patch
        self.patch = latest_patch
        self._indexes_ready = False
        self.tier_index.clear()
        self.tier_scope_index = defaultdict(list)
        self.matchup_index.clear()
        self.synergy_index.clear()
        self._loaded_tier_scopes.clear()
        self._loaded_matchup_scopes.clear()
        self._loaded_synergy_scopes.clear()
        return latest_patch

    async def _ensure_tier_scope_loaded(self, *, region: str, rank_tier: str, patch: str, roles: set[str]) -> None:
        requested_roles = {role for role in roles if role}
        missing = {
            (region, rank_tier, role, patch)
            for role in requested_roles
            if (region, rank_tier, role, patch) not in self._loaded_tier_scopes
        }
        if not missing:
            return
        async with self._scope_cache_lock:
            for _, _, role, _ in sorted(missing):
                scope_key = (region, rank_tier, role, patch)
                if scope_key in self._loaded_tier_scopes:
                    continue
                records = await self.repository.load_tier_stats(region=region, rank_tier=rank_tier, role=role, patch=patch)
                self.tier_scope_index[(region, rank_tier, role)] = records
                for record in records:
                    self.tier_index[(record.region, record.rank_tier, record.role, record.champion_id)] = record
                self._loaded_tier_scopes.add(scope_key)

    async def _ensure_matchup_scope_loaded(self, *, region: str, rank_tier: str, patch: str, roles: set[str]) -> None:
        requested_roles = {role for role in roles if role}
        missing = {
            (region, rank_tier, role, patch)
            for role in requested_roles
            if (region, rank_tier, role, patch) not in self._loaded_matchup_scopes
        }
        if not missing:
            return
        async with self._scope_cache_lock:
            for _, _, role, _ in sorted(missing):
                scope_key = (region, rank_tier, role, patch)
                if scope_key in self._loaded_matchup_scopes:
                    continue
                records = await self.repository.load_matchups(region=region, rank_tier=rank_tier, role=role, patch=patch)
                for record in records:
                    key = (record.region, record.rank_tier, record.role, record.opponent_role, record.champion_id, record.opponent_id)
                    self.matchup_index[key] = record
                self._loaded_matchup_scopes.add(scope_key)

    async def _ensure_synergy_scope_loaded(self, *, region: str, rank_tier: str, patch: str, roles: set[str]) -> None:
        requested_roles = {role for role in roles if role}
        missing = {
            (region, rank_tier, role, patch)
            for role in requested_roles
            if (region, rank_tier, role, patch) not in self._loaded_synergy_scopes
        }
        if not missing:
            return
        async with self._scope_cache_lock:
            for _, _, role, _ in sorted(missing):
                scope_key = (region, rank_tier, role, patch)
                if scope_key in self._loaded_synergy_scopes:
                    continue
                records = await self.repository.load_synergies(region=region, rank_tier=rank_tier, role=role, patch=patch)
                for record in records:
                    key = (record.region, record.rank_tier, record.role, record.teammate_role, record.champion_id, record.teammate_id)
                    self.synergy_index[key] = record
                self._loaded_synergy_scopes.add(scope_key)

    async def _load_index_snapshot(self) -> IndexSnapshot:
        database_path = await self._resolve_database_path()
        if not database_path or database_path == ":memory:":
            return await self._load_index_snapshot_async()
        return await asyncio.to_thread(self._load_index_snapshot_sync, database_path)

    async def _resolve_database_path(self) -> str | None:
        if self._database_path is not None:
            return self._database_path
        cursor = await self.repository.connection.execute("PRAGMA database_list")
        rows = await cursor.fetchall()
        for row in rows:
            if row["name"] == "main":
                self._database_path = row["file"] or ":memory:"
                return self._database_path
        self._database_path = ":memory:"
        return self._database_path

    async def _load_index_snapshot_async(self) -> IndexSnapshot:
        champion_lookup = await self.repository.get_champion_lookup()
        patch = await self.repository.latest_patch()
        tier_index: dict[tuple[str, str, str, int], TierStatRecord] = {}
        tier_scope_index: dict[tuple[str, str, str], list[TierStatRecord]] = defaultdict(list)
        matchup_index: dict[tuple[str, str, str, str, int, int], MatchupRecord] = {}
        synergy_index: dict[tuple[str, str, str, str, int, int], SynergyRecord] = {}

        if patch:
            for record in await self.repository.load_all_tier_stats(patch=patch):
                tier_index[(record.region, record.rank_tier, record.role, record.champion_id)] = record
                tier_scope_index[(record.region, record.rank_tier, record.role)].append(record)

            for record in await self.repository.load_all_matchups(patch=patch):
                key = (record.region, record.rank_tier, record.role, record.opponent_role, record.champion_id, record.opponent_id)
                matchup_index[key] = record

            for record in await self.repository.load_all_synergies(patch=patch):
                key = (record.region, record.rank_tier, record.role, record.teammate_role, record.champion_id, record.teammate_id)
                synergy_index[key] = record

        return IndexSnapshot(
            patch=patch,
            champion_lookup=champion_lookup,
            tier_index=tier_index,
            tier_scope_index=tier_scope_index,
            matchup_index=matchup_index,
            synergy_index=synergy_index,
        )

    def _load_index_snapshot_sync(self, database_path: str) -> IndexSnapshot:
        connection = sqlite3.connect(database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        champion_lookup: dict[int, ChampionRecord] = {}
        tier_index: dict[tuple[str, str, str, int], TierStatRecord] = {}
        tier_scope_index: dict[tuple[str, str, str], list[TierStatRecord]] = defaultdict(list)
        matchup_index: dict[tuple[str, str, str, str, int, int], MatchupRecord] = {}
        synergy_index: dict[tuple[str, str, str, str, int, int], SynergyRecord] = {}

        try:
            patch_row = connection.execute("SELECT patch FROM champions ORDER BY updated_at DESC LIMIT 1").fetchone()
            patch = patch_row["patch"] if patch_row else None

            for row in connection.execute("SELECT * FROM champions"):
                champion_lookup[row["id"]] = ChampionRecord(
                    champion_id=row["id"],
                    key=row["key"],
                    name=row["name"],
                    image_url=row["image_url"],
                    roles=json.loads(row["roles_json"]),
                    patch=row["patch"],
                )

            if not patch:
                return IndexSnapshot(
                    patch=None,
                    champion_lookup=champion_lookup,
                    tier_index=tier_index,
                    tier_scope_index=tier_scope_index,
                    matchup_index=matchup_index,
                    synergy_index=synergy_index,
                )

            for row in connection.execute("SELECT * FROM tier_stats WHERE patch = ?", (patch,)):
                record = TierStatRecord(**dict(row))
                tier_index[(record.region, record.rank_tier, record.role, record.champion_id)] = record
                tier_scope_index[(record.region, record.rank_tier, record.role)].append(record)

            for row in connection.execute("SELECT * FROM matchups WHERE patch = ?", (patch,)):
                record = MatchupRecord(**dict(row))
                key = (record.region, record.rank_tier, record.role, record.opponent_role, record.champion_id, record.opponent_id)
                matchup_index[key] = record

            for row in connection.execute("SELECT * FROM synergies WHERE patch = ?", (patch,)):
                record = SynergyRecord(**dict(row))
                key = (record.region, record.rank_tier, record.role, record.teammate_role, record.champion_id, record.teammate_id)
                synergy_index[key] = record

            return IndexSnapshot(
                patch=patch,
                champion_lookup=champion_lookup,
                tier_index=tier_index,
                tier_scope_index=tier_scope_index,
                matchup_index=matchup_index,
                synergy_index=synergy_index,
            )
        finally:
            connection.close()

    def warm_indexes_in_background(self) -> asyncio.Task[None]:
        if self._rebuild_task and not self._rebuild_task.done():
            return self._rebuild_task

        task = asyncio.create_task(self.rebuild_indexes())
        self._rebuild_task = task

        def _finalize(completed_task: asyncio.Task[None]) -> None:
            if self._rebuild_task is completed_task:
                self._rebuild_task = None
            try:
                completed_task.result()
            except asyncio.CancelledError:
                self._logger.info("Recommendation index warmup task cancelled")
            except Exception:
                self._logger.exception("Recommendation index warmup task failed")

        task.add_done_callback(_finalize)
        return task

    async def recommend(
        self,
        draft_state: DraftState,
        filters: ResolvedFilters,
        settings: UserSettings,
        draft_role_overrides: dict[tuple[str, int], str] | None = None,
    ) -> RecommendationBundle:
        return (await self.analyze(draft_state, filters, settings, draft_role_overrides)).recommendations

    async def analyze(
        self,
        draft_state: DraftState,
        filters: ResolvedFilters,
        settings: UserSettings,
        draft_role_overrides: dict[tuple[str, int], str] | None = None,
    ) -> RecommendationRuntimeSnapshot:
        await self.ensure_champion_lookup_ready()
        if self._rebuild_task and not self._rebuild_task.done():
            region = normalize_region(filters.region) or filters.region
            rank_tier = normalize_rank_tier(filters.rank_tier) or filters.rank_tier
            bundle = RecommendationBundle(
                region=region,
                rank_tier=rank_tier,
                patch=self.patch,
                active_patch_generation=self.patch,
                exact_data_available=False,
                patch_trusted=True,
                scope_complete=False,
                scope_ready=False,
                scope_freshness="warming",
                warnings=["Recommendation indexes are warming up on the server. Try again in a few seconds."],
            )
            return RecommendationRuntimeSnapshot(
                draft_state=self._hydrate_base_draft_state(draft_state),
                recommendations=bundle,
            )

        region = normalize_region(filters.region) or filters.region
        rank_tier = normalize_rank_tier(filters.rank_tier) or filters.rank_tier
        detected_local_role = normalize_role_name(draft_state.local_player_assigned_role)
        local_role = normalize_role_name(filters.role) or detected_local_role or "middle"

        if not await self.ensure_runtime_scope_ready(
            region=region,
            rank_tier=rank_tier,
            relation_roles={local_role},
        ):
            bundle = RecommendationBundle(
                region=region,
                rank_tier=rank_tier,
                patch=self.patch,
                active_patch_generation=self.patch,
                exact_data_available=False,
                patch_trusted=True,
                scope_complete=False,
                scope_ready=False,
                scope_freshness="warming",
                warnings=["Recommendation data is not available on the server yet."],
            )
            return RecommendationRuntimeSnapshot(
                draft_state=self._hydrate_base_draft_state(draft_state),
                recommendations=bundle,
            )

        overrides = draft_role_overrides or {}
        scope_complete = self._scope_is_complete(region=region, rank_tier=rank_tier)
        patch_warning = self._patch_warning(draft_state.patch)
        patch_trusted = patch_warning is None
        scope_runtime = await self._scope_runtime(region=region, rank_tier=rank_tier, role=local_role)

        base_draft = self._hydrate_base_draft_state(draft_state)
        my_team_slots = self._hydrate_local_slot(
            slots=base_draft.my_team_picks,
            local_player_cell_id=base_draft.local_player_cell_id,
            local_role=local_role,
            role_mode=settings.role_mode,
            detected_local_role=detected_local_role,
        )
        role_collision_slot: TeamSlot | None = None
        for slot in base_draft.my_team_picks:
            if slot.is_local_player:
                continue
            assigned = normalize_role_name(slot.assigned_role)
            manual_override = overrides.get(("ally", slot.cell_id))
            effective = normalize_role_name(manual_override) or assigned
            if effective == local_role and slot.champion_id:
                role_collision_slot = slot
                break
        ally_context = resolve_team_context(
            team="ally",
            slots=[slot for slot in my_team_slots if not slot.is_local_player],
            region=region,
            rank_tier=rank_tier,
            reserved_roles={local_role} if role_collision_slot is None else set(),
            overrides=overrides,
            champion_lookup=self.champion_lookup,
            tier_index=self.tier_index,
            champion_name_fn=self._champion_name,
        )
        enemy_context = resolve_team_context(
            team="enemy",
            slots=base_draft.enemy_team_picks,
            region=region,
            rank_tier=rank_tier,
            reserved_roles=set(),
            overrides=overrides,
            champion_lookup=self.champion_lookup,
            tier_index=self.tier_index,
            champion_name_fn=self._champion_name,
        )
        await self.ensure_runtime_scope_ready(
            region=region,
            rank_tier=rank_tier,
            relation_roles={local_role, *enemy_context.open_role_weights.keys()},
        )
        resolved_draft_state = self._merge_draft_state(
            draft_state=base_draft,
            my_team_slots=my_team_slots,
            ally_context=ally_context,
            enemy_context=enemy_context,
            local_role=local_role,
        )

        excluded = set(resolved_draft_state.my_bans + resolved_draft_state.enemy_bans)
        excluded.update(
            slot.champion_id
            for slot in resolved_draft_state.my_team_picks + resolved_draft_state.enemy_team_picks
            if slot.champion_id
        )

        scoped_filters = ResolvedFilters(region=region, rank_tier=rank_tier, role=local_role)
        pick_candidates = self._collect_tier_candidates(
            region=region,
            rank_tier=rank_tier,
            roles={local_role},
            excluded=excluded,
        )
        picks = [
            self._build_pick_recommendation(
                candidate=candidate,
                enemy_context=enemy_context,
                ally_context=ally_context,
                filters=scoped_filters,
                settings=settings,
                patch_trusted=patch_trusted,
                scope_complete=scope_complete,
            )
            for candidate in pick_candidates.values()
        ]
        picks.sort(key=lambda item: item.total_score, reverse=True)

        ban_candidates = self._collect_tier_candidates(
            region=region,
            rank_tier=rank_tier,
            roles=set(enemy_context.open_role_weights),
            excluded=excluded,
            role_weights=enemy_context.open_role_weights,
        )
        deduped_bans: dict[int, RecommendationItem] = {}
        for candidate in ban_candidates.values():
            item = self._build_ban_recommendation(
                candidate=candidate,
                ally_context=ally_context,
                enemy_context=enemy_context,
                filters=scoped_filters,
                patch_trusted=patch_trusted,
                scope_complete=scope_complete,
            )
            current = deduped_bans.get(item.champion_id)
            if current is None or item.total_score > current.total_score:
                deduped_bans[item.champion_id] = item
        bans = sorted(deduped_bans.values(), key=lambda item: item.total_score, reverse=True)

        warnings: list[str] = []
        exact_data_available = self._scope_has_tier_data(region=region, rank_tier=rank_tier, role=local_role)
        if not exact_data_available:
            warnings.append(f"No exact data for {region} / {rank_tier} / {local_role} on patch {self.patch or 'unknown'}.")
        elif not scope_complete:
            warnings.append(f"Exact scope {region} / {rank_tier} is only partially scraped. Missing role data lowers coverage.")

        if settings.role_mode == "auto" and not detected_local_role:
            warnings.append(
                f"Client did not expose your assigned role, so the saved role override '{local_role}' is being used."
            )

        if role_collision_slot is not None:
            collision_name = self._champion_name(role_collision_slot.champion_id) or "Teammate"
            warnings.append(
                f"Your selected role '{local_role}' overlaps with {collision_name}'s assigned position. "
                f"Recommendations assume you are playing {local_role}."
            )

        inferred_roles = ally_context.inferred_count + enemy_context.inferred_count
        if inferred_roles:
            warnings.append(
                f"Inferred {inferred_roles} visible draft role(s) from champion lane data because the client did not provide assigned positions."
            )

        for context in (ally_context, enemy_context):
            if context.warning:
                warnings.append(context.warning)

        if patch_warning:
            warnings.append(patch_warning)

        top_items = (picks[: settings.top_n] if picks else []) + (bans[: settings.top_n] if bans else [])
        if any(item.thin_evidence for item in top_items):
            warnings.append("Some top recommendations rely on low-sample matchup and synergy edges, so their total scores were reduced.")

        bundle = RecommendationBundle(
            picks=picks[: settings.top_n],
            bans=bans[: settings.top_n],
            region=region,
            rank_tier=rank_tier,
            patch=self.patch,
            active_patch_generation=scope_runtime["active_patch_generation"],
            exact_data_available=exact_data_available,
            patch_trusted=patch_trusted,
            scope_complete=scope_complete,
            scope_ready=scope_runtime["scope_ready"],
            scope_last_synced_at=scope_runtime["scope_last_synced_at"],
            scope_freshness=scope_runtime["scope_freshness"],
            fallback_used_recently=scope_runtime["fallback_used_recently"],
            warnings=warnings,
        )
        return RecommendationRuntimeSnapshot(draft_state=resolved_draft_state, recommendations=bundle)

    # --- Hydration helpers ---

    def _hydrate_base_draft_state(self, draft_state: DraftState) -> DraftState:
        return draft_state.model_copy(
            update={
                "my_team_picks": [self._hydrate_slot(slot) for slot in draft_state.my_team_picks],
                "enemy_team_picks": [self._hydrate_slot(slot) for slot in draft_state.enemy_team_picks],
            }
        )

    def _hydrate_slot(self, slot: TeamSlot) -> TeamSlot:
        champion = self.champion_lookup.get(slot.champion_id)
        assigned_role = normalize_role_name(slot.assigned_role)
        candidates = [RoleCandidate(role=assigned_role, confidence=1.0)] if assigned_role else []
        return slot.model_copy(
            update={
                "champion_name": champion.name if champion else slot.champion_name,
                "champion_image_url": champion.image_url if champion else slot.champion_image_url,
                "effective_role": assigned_role or slot.effective_role,
                "role_source": "lcu" if assigned_role else slot.role_source,
                "role_confidence": 1.0 if assigned_role else slot.role_confidence,
                "role_candidates": candidates or slot.role_candidates,
            }
        )

    def _hydrate_local_slot(
        self,
        *,
        slots: list[TeamSlot],
        local_player_cell_id: int | None,
        local_role: str,
        role_mode: str,
        detected_local_role: str | None,
    ) -> list[TeamSlot]:
        hydrated: list[TeamSlot] = []
        for slot in slots:
            if slot.cell_id != local_player_cell_id:
                hydrated.append(slot)
                continue
            role_source = "lcu" if detected_local_role and role_mode == "auto" else "manual"
            hydrated.append(
                slot.model_copy(
                    update={
                        "effective_role": local_role,
                        "role_source": role_source,
                        "role_confidence": 1.0,
                        "role_candidates": [RoleCandidate(role=local_role, confidence=1.0)],
                    }
                )
            )
        return hydrated

    def _merge_draft_state(
        self,
        *,
        draft_state: DraftState,
        my_team_slots: list[TeamSlot],
        ally_context: ResolvedTeamContext,
        enemy_context: ResolvedTeamContext,
        local_role: str,
    ) -> DraftState:
        ally_lookup = {slot.cell_id: slot for slot in ally_context.slots}
        enemy_lookup = {slot.cell_id: slot for slot in enemy_context.slots}
        merged_my_team = [ally_lookup.get(slot.cell_id, slot) for slot in my_team_slots]
        merged_enemy_team = [enemy_lookup.get(slot.cell_id, slot) for slot in draft_state.enemy_team_picks]
        return draft_state.model_copy(
            update={
                "my_team_picks": merged_my_team,
                "enemy_team_picks": merged_enemy_team,
                "my_team_declared_roles": [slot.effective_role or slot.assigned_role or "" for slot in merged_my_team],
                "enemy_team_declared_roles": [slot.effective_role or slot.assigned_role or "" for slot in merged_enemy_team],
                "local_player_effective_role": local_role,
            }
        )

    # --- Recommendation building ---

    def _build_pick_recommendation(
        self,
        *,
        candidate: TierCandidate,
        enemy_context: ResolvedTeamContext,
        ally_context: ResolvedTeamContext,
        filters: ResolvedFilters,
        settings: UserSettings,
        patch_trusted: bool,
        scope_complete: bool,
    ) -> RecommendationItem:
        enemy_slots = [slot for slot in enemy_context.slots if slot.champion_id]
        ally_slots = [slot for slot in ally_context.slots if slot.champion_id]
        counter_summary = summarize_relations(
            slots=enemy_slots,
            role_probabilities=enemy_context.role_probabilities,
            certainty_multiplier=enemy_context.certainty_multiplier,
            loader=lambda slot, matched_role: self._lookup_matchup(
                region=filters.region, rank_tier=filters.rank_tier,
                role=candidate.role, champion_id=candidate.champion_id,
                slot=slot, matched_role=matched_role,
            ),
            normalizer=normalize_delta,
            detail_builder=lambda slot, matched_role, record, signed_edge, net_contribution, sc: matchup_insight(
                kind="counter", slot=slot, matched_role=matched_role, record=record,
                signed_edge=signed_edge, net_contribution=net_contribution, sample_confidence=sc,
                champion_name=self._champion_name(slot.champion_id),
            ),
            sample_penalty_note_fn=lambda slot, matched_role, games, sc: sample_penalty_note(
                slot=slot, matched_role=matched_role, games=games, sample_confidence=sc,
                champion_name=self._champion_name(slot.champion_id),
            ),
            candidate_role=candidate.role,
        )
        synergy_summary = summarize_relations(
            slots=ally_slots,
            role_probabilities=ally_context.role_probabilities,
            certainty_multiplier=ally_context.certainty_multiplier,
            loader=lambda slot, matched_role: self._lookup_synergy(
                region=filters.region, rank_tier=filters.rank_tier,
                role=candidate.role, champion_id=candidate.champion_id,
                slot=slot, matched_role=matched_role,
            ),
            normalizer=normalize_synergy,
            detail_builder=lambda slot, matched_role, record, signed_edge, net_contribution, sc: synergy_insight(
                kind="synergy", slot=slot, matched_role=matched_role, record=record,
                signed_edge=signed_edge, net_contribution=net_contribution, sample_confidence=sc,
                champion_name=self._champion_name(slot.champion_id),
            ),
            sample_penalty_note_fn=lambda slot, matched_role, games, sc: sample_penalty_note(
                slot=slot, matched_role=matched_role, games=games, sample_confidence=sc,
                champion_name=self._champion_name(slot.champion_id),
            ),
            candidate_role=candidate.role,
        )
        ts = tier_score(candidate.record)
        rfs = role_fit_score(candidate.record)
        # draft_progress: 0.0 (no picks visible) → 1.0 (all 9 possible picks visible)
        draft_progress = min((len(enemy_slots) + len(ally_slots)) / 9.0, 1.0)
        if not enemy_slots and not ally_slots:
            composition = compose_predraft_pick_score(candidate.record)
        else:
            composition = compose_pick_score(
                record=candidate.record,
                counter_score=counter_summary.score,
                synergy_score=synergy_summary.score,
                enemy_count=len(enemy_slots),
                ally_count=len(ally_slots),
                low_sample_penalty_val=low_sample_penalty(candidate.record),
                draft_progress=draft_progress,
            )
        thin = has_thin_evidence(counter_summary, synergy_summary)
        total = max(0.0, composition.total * (THIN_EVIDENCE_MULTIPLIER if thin else 1.0))
        champion_name_val = self._champion_name(candidate.champion_id)
        ev_score = evidence_score(counter_summary.coverage, synergy_summary.coverage, enemy_slots, ally_slots)
        rc = combine_metric(enemy_context.role_certainty, ally_context.role_certainty, enemy_slots, ally_slots)
        sc = combine_metric(counter_summary.sample_confidence, synergy_summary.sample_confidence, enemy_slots, ally_slots)
        confidence = min(
            1.0,
            PICK_CONFIDENCE_BASE
            + min(candidate.record.games / PICK_CONFIDENCE_GAMES_DIVISOR, PICK_CONFIDENCE_GAMES_MAX)
            + (PICK_CONFIDENCE_EVIDENCE_WEIGHT * ev_score)
            + (PICK_CONFIDENCE_CERTAINTY_WEIGHT * rc)
            + (PICK_CONFIDENCE_SAMPLE_WEIGHT * sc),
        )
        if not patch_trusted:
            confidence = min(confidence, CONFIDENCE_CAP_PATCH_MISMATCH)
        if not scope_complete:
            confidence = min(confidence, CONFIDENCE_CAP_INCOMPLETE_SCOPE)
        reasons = [
            f"Tier #{candidate.record.tier_rank or '?'} / {candidate.record.tier_grade} / WR {candidate.record.win_rate:.1f}% / {candidate.record.games:,} games",
            f"Counter coverage {counter_summary.coverage:.0%}",
            f"Synergy coverage {synergy_summary.coverage:.0%}",
        ]
        reasons.extend(insight.summary for insight in counter_summary.insights[:2])
        reasons.extend(insight.summary for insight in synergy_summary.insights[:2])
        explanation = build_pick_explanation(
            champion_name=champion_name_val, candidate=candidate, filters=filters,
            composition=composition, counter_summary=counter_summary, synergy_summary=synergy_summary,
            scenario_summary=combined_scenario_summary(enemy_context, ally_context), thin_evidence=thin,
        )
        return RecommendationItem(
            champion_id=candidate.champion_id, champion_name=champion_name_val,
            suggested_role=candidate.role, total_score=round(total * 100, 2), display_band=display_band(total * 100),
            counter_score=round(counter_summary.score, 4), synergy_score=round(synergy_summary.score, 4),
            tier_score=round(ts, 4), role_fit_score=round(rfs, 4),
            matchup_coverage=round(counter_summary.coverage, 4), synergy_coverage=round(synergy_summary.coverage, 4),
            evidence_score=round(ev_score, 4), role_certainty=round(rc, 4),
            sample_confidence=round(sc, 4), thin_evidence=thin, confidence=round(confidence, 4),
            reasons=reasons, explanation=explanation,
        )

    def _build_ban_recommendation(
        self,
        *,
        candidate: TierCandidate,
        ally_context: ResolvedTeamContext,
        enemy_context: ResolvedTeamContext,
        filters: ResolvedFilters,
        patch_trusted: bool,
        scope_complete: bool,
    ) -> RecommendationItem:
        ally_slots = [slot for slot in ally_context.slots if slot.champion_id]
        enemy_slots = [slot for slot in enemy_context.slots if slot.champion_id]
        counter_summary = summarize_relations(
            slots=ally_slots,
            role_probabilities=ally_context.role_probabilities,
            certainty_multiplier=ally_context.certainty_multiplier,
            loader=lambda slot, matched_role: self._lookup_matchup(
                region=filters.region, rank_tier=filters.rank_tier,
                role=candidate.role, champion_id=candidate.champion_id,
                slot=slot, matched_role=matched_role,
            ),
            normalizer=normalize_delta,
            detail_builder=lambda slot, matched_role, record, signed_edge, net_contribution, sc: matchup_insight(
                kind="threat", slot=slot, matched_role=matched_role, record=record,
                signed_edge=signed_edge, net_contribution=net_contribution, sample_confidence=sc,
                champion_name=self._champion_name(slot.champion_id),
            ),
            sample_penalty_note_fn=lambda slot, matched_role, games, sc: sample_penalty_note(
                slot=slot, matched_role=matched_role, games=games, sample_confidence=sc,
                champion_name=self._champion_name(slot.champion_id),
            ),
            candidate_role=candidate.role,
        )
        synergy_summary = summarize_relations(
            slots=enemy_slots,
            role_probabilities=enemy_context.role_probabilities,
            certainty_multiplier=enemy_context.certainty_multiplier,
            loader=lambda slot, matched_role: self._lookup_synergy(
                region=filters.region, rank_tier=filters.rank_tier,
                role=candidate.role, champion_id=candidate.champion_id,
                slot=slot, matched_role=matched_role,
            ),
            normalizer=normalize_synergy,
            detail_builder=lambda slot, matched_role, record, signed_edge, net_contribution, sc: synergy_insight(
                kind="enemy_synergy", slot=slot, matched_role=matched_role, record=record,
                signed_edge=signed_edge, net_contribution=net_contribution, sample_confidence=sc,
                champion_name=self._champion_name(slot.champion_id),
            ),
            sample_penalty_note_fn=lambda slot, matched_role, games, sc: sample_penalty_note(
                slot=slot, matched_role=matched_role, games=games, sample_confidence=sc,
                champion_name=self._champion_name(slot.champion_id),
            ),
            candidate_role=candidate.role,
        )
        tier_threat = tier_score(candidate.record)
        pick_rate = candidate.record.pick_rate
        ban_rate = candidate.record.ban_rate
        pick_rate_score = min(pick_rate / 20.0, 1.0) if pick_rate else 0.4
        ban_rate_score = min(ban_rate / 30.0, 1.0) if ban_rate else 0.3
        composition = compose_ban_score(
            tier_threat=tier_threat, pick_rate_score=pick_rate_score, ban_rate_score=ban_rate_score,
            counter_threat=counter_summary.score, synergy_threat=synergy_summary.score,
            matchup_slots_present=bool(ally_slots), synergy_slots_present=bool(enemy_slots),
            role_likelihood_score=candidate.role_prior,
        )
        thin = has_thin_evidence(counter_summary, synergy_summary)
        total = max(0.0, composition.total * (THIN_EVIDENCE_MULTIPLIER if thin else 1.0))
        champion_name_val = self._champion_name(candidate.champion_id)
        ev_score = evidence_score(counter_summary.coverage, synergy_summary.coverage, ally_slots, enemy_slots)
        rc = combine_metric(ally_context.role_certainty, enemy_context.role_certainty, ally_slots, enemy_slots)
        sc = combine_metric(counter_summary.sample_confidence, synergy_summary.sample_confidence, ally_slots, enemy_slots)
        confidence = min(
            1.0,
            BAN_CONFIDENCE_BASE
            + min(candidate.record.games / BAN_CONFIDENCE_GAMES_DIVISOR, BAN_CONFIDENCE_GAMES_MAX)
            + (BAN_CONFIDENCE_EVIDENCE_WEIGHT * ev_score)
            + (BAN_CONFIDENCE_CERTAINTY_WEIGHT * rc)
            + (BAN_CONFIDENCE_SAMPLE_WEIGHT * sc),
        )
        if not patch_trusted:
            confidence = min(confidence, CONFIDENCE_CAP_PATCH_MISMATCH)
        if not scope_complete:
            confidence = min(confidence, CONFIDENCE_CAP_INCOMPLETE_SCOPE)
        reasons = [
            f"Tier {candidate.record.tier_grade} / PR {pick_rate:.1f}% / {candidate.record.games:,} games",
            f"Threat coverage {counter_summary.coverage:.0%}",
            f"Enemy synergy coverage {synergy_summary.coverage:.0%}",
        ]
        reasons.extend(insight.summary for insight in counter_summary.insights[:2])
        reasons.extend(insight.summary for insight in synergy_summary.insights[:2])
        explanation = build_ban_explanation(
            champion_name=champion_name_val, candidate=candidate, filters=filters,
            composition=composition, counter_summary=counter_summary, synergy_summary=synergy_summary,
            scenario_summary=combined_scenario_summary(enemy_context, ally_context), thin_evidence=thin,
        )
        return RecommendationItem(
            champion_id=candidate.champion_id, champion_name=champion_name_val,
            suggested_role=candidate.role, total_score=round(total * 100, 2), display_band=display_band(total * 100),
            counter_score=round(counter_summary.score, 4), synergy_score=round(synergy_summary.score, 4),
            tier_score=round(tier_threat, 4), role_fit_score=round(candidate.role_prior, 4),
            matchup_coverage=round(counter_summary.coverage, 4), synergy_coverage=round(synergy_summary.coverage, 4),
            evidence_score=round(ev_score, 4), role_certainty=round(rc, 4),
            sample_confidence=round(sc, 4), thin_evidence=thin, confidence=round(confidence, 4),
            reasons=reasons, explanation=explanation,
        )

    # --- Data lookups ---

    def _collect_tier_candidates(
        self,
        *,
        region: str,
        rank_tier: str,
        roles: set[str],
        excluded: set[int],
        role_weights: dict[str, float] | None = None,
    ) -> dict[tuple[int, str], TierCandidate]:
        grouped: dict[tuple[int, str], TierCandidate] = {}
        weights = role_weights or {}
        for role in roles:
            role_weight = weights.get(role, 1.0)
            if role_weight <= 0:
                continue
            for record in self.tier_scope_index.get((region, rank_tier, role), []):
                if record.champion_id in excluded:
                    continue
                grouped[(record.champion_id, record.role)] = TierCandidate(
                    champion_id=record.champion_id,
                    role=record.role,
                    record=record,
                    role_prior=role_weight,
                )
        return grouped

    def _lookup_matchup(
        self,
        *,
        region: str,
        rank_tier: str,
        role: str,
        champion_id: int,
        slot: TeamSlot,
        matched_role: str,
    ) -> MatchupRecord | None:
        return self.matchup_index.get((region, rank_tier, role, matched_role, champion_id, slot.champion_id))

    def _lookup_synergy(
        self,
        *,
        region: str,
        rank_tier: str,
        role: str,
        champion_id: int,
        slot: TeamSlot,
        matched_role: str,
    ) -> SynergyRecord | None:
        return self.synergy_index.get((region, rank_tier, role, matched_role, champion_id, slot.champion_id))

    def _scope_has_tier_data(self, *, region: str, rank_tier: str, role: str) -> bool:
        return bool(self.tier_scope_index.get((region, rank_tier, role), []))

    async def _scope_runtime(self, *, region: str, rank_tier: str, role: str) -> dict[str, object]:
        scope_status = None
        if self.patch:
            scope_status = await self.repository.get_scope_status(region=region, rank_tier=rank_tier, role=role, patch=self.patch)
        active_generation = await self.repository.active_patch_generation()
        freshness = "unknown"
        scope_ready = False
        scope_last_synced_at = None
        fallback_used_recently = False
        if scope_status is not None:
            scope_last_synced_at = scope_status.last_build_refresh_at or scope_status.last_tier_refresh_at or scope_status.last_success_at
            fallback_used_recently = scope_status.fallback_used_recently
            if scope_status.empty_scope:
                freshness = "empty"
                scope_ready = True
            elif scope_status.status == "ready":
                freshness = "fresh"
                scope_ready = True
            elif scope_status.status == "partial":
                freshness = "warming"
            elif scope_status.status == "failed":
                freshness = "failed"
            else:
                freshness = "stale"
        return {
            "scope_ready": scope_ready,
            "scope_last_synced_at": scope_last_synced_at,
            "scope_freshness": freshness,
            "fallback_used_recently": fallback_used_recently,
            "active_patch_generation": active_generation.patch if active_generation else self.patch,
        }

    def _scope_is_complete(self, *, region: str, rank_tier: str) -> bool:
        return all(self._scope_has_tier_data(region=region, rank_tier=rank_tier, role=role) for role in SUPPORTED_ROLES)

    def _champion_name(self, champion_id: int) -> str:
        champion = self.champion_lookup.get(champion_id)
        return champion.name if champion else f"Champion #{champion_id}"

    def _patch_warning(self, client_patch: str | None) -> str | None:
        if not client_patch or not self.patch:
            return None
        if self._patch_family(client_patch) == self._patch_family(self.patch):
            return None
        return (
            f"Client patch {client_patch} does not match local data patch {self.patch}. "
            "Run a refresh before trusting exact recommendations."
        )

    def _patch_family(self, patch: str | None) -> str | None:
        if not patch:
            return None
        parts = patch.split(".")
        return ".".join(parts[:2]) if len(parts) >= 2 else patch
