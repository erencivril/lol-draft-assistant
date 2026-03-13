import { useMemo, useState } from "react";
import type { ChampionCatalogItem } from "../api/client";
import { roleOptions } from "../constants/filters";
import type { DraftState, TeamSlot } from "../types";
import { ChampionPicker } from "./ChampionPicker";

type TeamName = "ally" | "enemy";

type DraftBoardProps = {
  champions: ChampionCatalogItem[];
  draftState: DraftState;
  lcuConnected: boolean;
  targetCellId: number;
  localPlayerCellId: number;
  hasOverrides?: boolean;
  onSlotChampionChange: (team: TeamName, cellId: number, championId: number) => void;
  onSlotRoleChange: (team: TeamName, cellId: number, role: string) => void;
  onTargetSlotChange: (cellId: number) => void;
  onRecommendForMe: () => void;
  onBanChange: (team: TeamName, index: number, championId: number) => void;
  onResetOverrides?: () => void;
};

type PickerTarget =
  | {
      kind: "slot";
      team: TeamName;
      cellId: number;
      currentChampionId: number;
      label: string;
    }
  | {
      kind: "ban";
      team: TeamName;
      index: number;
      currentChampionId: number;
      label: string;
    };

const unknownRoleValue = "__unknown__";

function normalizeChampionImageUrl(url?: string | null) {
  if (!url) {
    return null;
  }
  return url.replace(".png.png", ".png");
}

function roleLabel(role?: string | null) {
  return role ? role.charAt(0).toUpperCase() + role.slice(1) : "Unknown";
}

function SlotCard({
  slot,
  title,
  lcuConnected,
  isTarget = false,
  currentActorCellId,
  currentActionType,
  onOpenPicker,
  onRoleChange,
  onSelectTarget,
}: {
  slot: TeamSlot;
  title: string;
  lcuConnected: boolean;
  isTarget?: boolean;
  currentActorCellId?: number | null;
  currentActionType?: string | null;
  onOpenPicker: () => void;
  onRoleChange: (role: string) => void;
  onSelectTarget?: () => void;
}) {
  const championSelected = slot.champion_id > 0;
  const isCurrentActor = currentActorCellId === slot.cell_id;
  const actionLabel = currentActionType?.toLowerCase() === "ban" ? "Banning now" : "Picking now";
  const disabledPicker = slot.is_local_player && !championSelected;
  const subtitle = slot.is_local_player
    ? isTarget
      ? "Local + recommendation target"
      : "Local slot"
    : isTarget
      ? "Recommendation target"
      : "Editable slot";
  const emptyStateCopy = slot.is_local_player
    ? isTarget
      ? "Recommendations use your role slot."
      : "Your role stays fixed while you inspect another ally slot."
    : isTarget
      ? "Recommendations are generated for this slot."
      : "Search the full champion pool";

  return (
    <article
      className={`rounded-2xl border p-3 transition-colors ${
        isCurrentActor
          ? "border-cyan-500/60 bg-cyan-500/10"
          : "border-zinc-800 bg-zinc-900/65"
      }`}
    >
      <div className="mb-3 flex items-center justify-between gap-2">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-zinc-500">{title}</p>
          <p className="text-xs text-zinc-400">{subtitle}</p>
        </div>
        <div className="flex items-center gap-2">
          {slot.is_local_player ? (
            <span className="rounded-full bg-cyan-500/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.18em] text-cyan-300">
              You
            </span>
          ) : lcuConnected ? (
            <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.18em] text-zinc-400">
              LCU + Override
            </span>
          ) : null}
          {isTarget ? (
            <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.18em] text-emerald-300">
              Target
            </span>
          ) : null}
        </div>
      </div>

      <button
        type="button"
        disabled={disabledPicker}
        className="flex w-full items-center gap-3 rounded-2xl border border-zinc-800 bg-zinc-950/70 p-3 text-left transition-colors hover:border-zinc-700 disabled:cursor-not-allowed disabled:opacity-80"
        onClick={onOpenPicker}
      >
        {championSelected && slot.champion_image_url ? (
          <img
            alt={slot.champion_name ?? `Champion ${slot.champion_id}`}
            src={normalizeChampionImageUrl(slot.champion_image_url) ?? undefined}
            className="size-14 rounded-xl border border-zinc-700 object-cover"
          />
        ) : (
          <div className="grid size-14 place-items-center rounded-xl border border-dashed border-zinc-700 bg-zinc-900 text-[10px] font-semibold uppercase tracking-[0.18em] text-zinc-500">
            {slot.is_local_player ? "You" : "Pick"}
          </div>
        )}

        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-zinc-100">
            {championSelected
              ? slot.champion_name ?? `Champion ${slot.champion_id}`
              : slot.is_local_player
                ? "Your champion is kept open"
                : "Select champion"}
          </p>
          <p className="mt-1 text-xs text-zinc-400">
            {championSelected ? "Click to change selection" : emptyStateCopy}
          </p>
          {isCurrentActor ? (
            <p className="mt-2 text-[11px] font-medium text-cyan-300">{actionLabel}</p>
          ) : null}
        </div>
      </button>

      <label className="mt-3 grid gap-1.5 text-xs font-medium text-zinc-500">
        Role
        <select
          aria-label={`${title} role`}
          className="rounded-xl border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none transition-colors focus:border-cyan-500 disabled:cursor-not-allowed disabled:opacity-70"
          value={slot.effective_role ?? slot.assigned_role ?? unknownRoleValue}
          onChange={(event) =>
            onRoleChange(event.target.value === unknownRoleValue ? "" : event.target.value)
          }
        >
          <option value={unknownRoleValue}>Unknown</option>
          {roleOptions.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>

      <div className="mt-3 flex items-center justify-between gap-3 text-[11px] text-zinc-500">
        <span>{roleLabel(slot.effective_role ?? slot.assigned_role)}</span>
        <div className="flex items-center gap-3">
          <span>{slot.role_source === "manual" ? "Manual" : slot.role_source.toUpperCase()}</span>
          {onSelectTarget ? (
            <button
              type="button"
              aria-label={`Analyze ${title}`}
              aria-pressed={isTarget}
              className={`rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] transition-colors ${
                isTarget
                  ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                  : "border-zinc-700 text-zinc-400 hover:border-zinc-500 hover:text-zinc-100"
              }`}
              onClick={onSelectTarget}
            >
              {isTarget ? "Target" : "Analyze"}
            </button>
          ) : null}
        </div>
      </div>
    </article>
  );
}

function BanRow({
  title,
  team,
  bans,
  champions,
  onChange,
}: {
  title: string;
  team: TeamName;
  bans: number[];
  champions: ChampionCatalogItem[];
  onChange: (index: number, championId: number) => void;
}) {
  const [pickerIndex, setPickerIndex] = useState<number | null>(null);
  const activeChampionId = pickerIndex == null ? 0 : bans[pickerIndex] ?? 0;
  const championLookup = useMemo(
    () => Object.fromEntries(champions.map((champion) => [champion.champion_id, champion])),
    [champions]
  );
  const selectedChampionIds = bans.filter((championId) => championId > 0);

  return (
    <section className="rounded-[var(--radius-panel)] border border-zinc-800 bg-zinc-900/55 p-4">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-zinc-500">Bans</p>
          <h3 className="text-sm font-semibold text-zinc-100">{title}</h3>
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-5">
        {bans.map((championId, index) => {
          const champion = championId > 0 ? championLookup[championId] : undefined;
          return (
            <button
              key={`${team}-ban-${index}`}
              type="button"
              className="rounded-2xl border border-zinc-800 bg-zinc-950/70 p-3 text-left transition-colors hover:border-zinc-700"
              onClick={() => setPickerIndex(index)}
            >
              <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-zinc-500">Ban {index + 1}</p>
              <div className="mt-3 flex items-center gap-3">
                {champion ? (
                  <img
                    alt={champion.name}
                    src={normalizeChampionImageUrl(champion.image_url) ?? undefined}
                    className="size-10 rounded-xl border border-zinc-700 object-cover"
                  />
                ) : (
                  <div className="grid size-10 place-items-center rounded-xl border border-dashed border-zinc-700 bg-zinc-900 text-[10px] font-semibold uppercase tracking-[0.18em] text-zinc-500">
                    Ban
                  </div>
                )}
                <span className="truncate text-sm text-zinc-200">{champion?.name ?? "Open"}</span>
              </div>
            </button>
          );
        })}
      </div>

      <ChampionPicker
        open={pickerIndex != null}
        title={`${title} - ban slot`}
        champions={champions}
        disabledChampionIds={selectedChampionIds.filter((championId) => championId !== activeChampionId)}
        selectedChampionId={activeChampionId}
        onClose={() => setPickerIndex(null)}
        onSelect={(championId) => {
          if (pickerIndex == null) {
            return;
          }
          onChange(pickerIndex, championId);
        }}
      />
    </section>
  );
}

export function DraftBoard({
  champions,
  draftState,
  lcuConnected,
  targetCellId,
  localPlayerCellId,
  hasOverrides = false,
  onSlotChampionChange,
  onSlotRoleChange,
  onTargetSlotChange,
  onRecommendForMe,
  onBanChange,
  onResetOverrides,
}: DraftBoardProps) {
  const [pickerTarget, setPickerTarget] = useState<PickerTarget | null>(null);
  const selectedChampionIds = useMemo(() => {
    const championIds = [
      ...draftState.my_team_picks.map((slot) => slot.champion_id),
      ...draftState.enemy_team_picks.map((slot) => slot.champion_id),
      ...draftState.my_bans,
      ...draftState.enemy_bans,
    ];
    return championIds.filter((championId) => championId > 0);
  }, [draftState.enemy_bans, draftState.enemy_team_picks, draftState.my_bans, draftState.my_team_picks]);
  const pickerDisabledChampionIds = pickerTarget
    ? selectedChampionIds.filter((championId) => championId !== pickerTarget.currentChampionId)
    : [];

  const allyBans = [...draftState.my_bans, ...Array.from({ length: Math.max(0, 5 - draftState.my_bans.length) }, () => 0)];
  const enemyBans = [...draftState.enemy_bans, ...Array.from({ length: Math.max(0, 5 - draftState.enemy_bans.length) }, () => 0)];
  const targetSlot = draftState.my_team_picks.find((slot) => slot.cell_id === targetCellId);
  const targetLabel = targetSlot?.is_local_player ? "Your slot" : targetSlot ? `Ally ${targetSlot.cell_id}` : "Your slot";

  return (
    <div className="space-y-4">
      <section className="rounded-[var(--radius-panel)] border border-zinc-800 bg-zinc-900/55 p-4">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-cyan-400">Draft Board</p>
            <h2 className="text-lg font-semibold text-zinc-100">{lcuConnected ? "LCU auto-fill active" : "Manual draft mode"}</h2>
            <p className="mt-1 text-xs text-zinc-500">Target: {targetLabel}</p>
          </div>
          <div className="flex items-center gap-2">
            {targetCellId !== localPlayerCellId ? (
              <button
                type="button"
                className="rounded-full border border-zinc-700 px-3 py-1.5 text-xs font-medium text-zinc-300 transition-colors hover:border-zinc-500 hover:text-zinc-100"
                onClick={onRecommendForMe}
              >
                Recommend for me
              </button>
            ) : null}
            {hasOverrides && onResetOverrides ? (
              <button
                type="button"
                className="rounded-full border border-zinc-700 px-3 py-1.5 text-xs font-medium text-zinc-300 transition-colors hover:border-zinc-500 hover:text-zinc-100"
                onClick={onResetOverrides}
              >
                Clear overrides
              </button>
            ) : null}
          </div>
        </div>

        <div className="grid gap-4 xl:grid-cols-2">
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-zinc-100">Allies</h3>
              <span className="text-xs text-zinc-500">{lcuConnected ? "Auto-filled, still editable" : "Choose visible picks manually"}</span>
            </div>
            <div className="grid gap-3">
              {draftState.my_team_picks.map((slot) => (
                <SlotCard
                  key={`ally-${slot.cell_id}`}
                  slot={slot}
                  title={slot.is_local_player ? "Your slot" : `Ally ${slot.cell_id}`}
                  lcuConnected={lcuConnected}
                  isTarget={slot.cell_id === targetCellId}
                  currentActorCellId={draftState.current_actor_cell_id}
                  currentActionType={draftState.current_action_type}
                  onOpenPicker={() =>
                    !slot.is_local_player &&
                    setPickerTarget({
                      kind: "slot",
                      team: "ally",
                      cellId: slot.cell_id,
                      currentChampionId: slot.champion_id,
                      label: slot.is_local_player ? "Your role slot" : `Ally ${slot.cell_id}`,
                    })
                  }
                  onRoleChange={(role) => onSlotRoleChange("ally", slot.cell_id, role)}
                  onSelectTarget={() => onTargetSlotChange(slot.cell_id)}
                />
              ))}
            </div>
          </div>

          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-zinc-100">Enemies</h3>
              <span className="text-xs text-zinc-500">Track the draft state slot by slot</span>
            </div>
            <div className="grid gap-3">
              {draftState.enemy_team_picks.map((slot) => (
                <SlotCard
                  key={`enemy-${slot.cell_id}`}
                  slot={slot}
                  title={`Enemy ${slot.cell_id - 5}`}
                  lcuConnected={lcuConnected}
                  currentActorCellId={draftState.current_actor_cell_id}
                  currentActionType={draftState.current_action_type}
                  onOpenPicker={() =>
                    setPickerTarget({
                      kind: "slot",
                      team: "enemy",
                      cellId: slot.cell_id,
                      currentChampionId: slot.champion_id,
                      label: `Enemy ${slot.cell_id - 5}`,
                    })
                  }
                  onRoleChange={(role) => onSlotRoleChange("enemy", slot.cell_id, role)}
                />
              ))}
            </div>
          </div>
        </div>
      </section>

      <div className="grid gap-4 xl:grid-cols-2">
        <BanRow title="Your side bans" team="ally" bans={allyBans} champions={champions} onChange={(index, championId) => onBanChange("ally", index, championId)} />
        <BanRow title="Enemy side bans" team="enemy" bans={enemyBans} champions={champions} onChange={(index, championId) => onBanChange("enemy", index, championId)} />
      </div>

      <ChampionPicker
        open={pickerTarget != null}
        title={pickerTarget?.label ?? "Champion slot"}
        champions={champions}
        disabledChampionIds={pickerDisabledChampionIds}
        selectedChampionId={pickerTarget?.currentChampionId ?? 0}
        onClose={() => setPickerTarget(null)}
        onSelect={(championId) => {
          if (!pickerTarget || pickerTarget.kind !== "slot") {
            return;
          }
          onSlotChampionChange(pickerTarget.team, pickerTarget.cellId, championId);
        }}
      />
    </div>
  );
}
