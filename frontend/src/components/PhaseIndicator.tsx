import type { DraftState } from "../types";

type PhaseIndicatorProps = {
  draftState: DraftState;
};

function phaseBadge(actionType?: string | null) {
  const normalized = actionType?.toLowerCase();
  if (normalized === "ban") return { label: "BAN", color: "bg-red-500/20 text-red-400" };
  if (normalized === "pick") return { label: "PICK", color: "bg-cyan-500/20 text-cyan-400" };
  return { label: actionType?.toUpperCase() ?? "DRAFT", color: "bg-zinc-700/50 text-zinc-400" };
}

function timerColor(seconds: number) {
  if (seconds <= 5) return "text-red-400";
  if (seconds <= 10) return "text-amber-400";
  return "text-zinc-100";
}

function actionPresentParticiple(actionType?: string | null) {
  if (actionType?.toLowerCase() === "pick") return "picking";
  if (actionType?.toLowerCase() === "ban") return "banning";
  return "acting";
}

function findActorContext(draftState: DraftState) {
  const actorCellId = draftState.current_actor_cell_id;
  if (actorCellId == null) return null;

  const allySlot = draftState.my_team_picks.find((slot) => slot.cell_id === actorCellId);
  if (allySlot) {
    return {
      team: "ally" as const,
      role: allySlot.effective_role ?? allySlot.assigned_role ?? null,
      isLocalPlayer: allySlot.is_local_player,
    };
  }

  const enemySlot = draftState.enemy_team_picks.find((slot) => slot.cell_id === actorCellId);
  if (enemySlot) {
    return {
      team: "enemy" as const,
      role: enemySlot.effective_role ?? enemySlot.assigned_role ?? null,
      isLocalPlayer: false,
    };
  }

  return null;
}

export function PhaseIndicator({ draftState }: PhaseIndicatorProps) {
  const badge = phaseBadge(draftState.current_action_type);
  const timer = draftState.timer_seconds_left ?? 0;
  const localRole = draftState.local_player_effective_role ?? draftState.local_player_assigned_role;
  const isMyTurn = draftState.is_local_players_turn;
  const actorContext = findActorContext(draftState);
  const actionProgressLabel = actionPresentParticiple(draftState.current_action_type);
  const actionVerb = draftState.current_action_type
    ? draftState.current_action_type.charAt(0).toUpperCase() + draftState.current_action_type.slice(1).toLowerCase()
    : "Act";
  const waitingCopy = actorContext?.team === "enemy"
    ? `Enemy team is ${actionProgressLabel}`
    : actorContext?.team === "ally"
      ? actorContext.isLocalPlayer
        ? `Your Turn to ${actionVerb}`
        : `Teammate is ${actionProgressLabel}`
      : "Waiting...";
  const actorRole = actorContext?.role ?? localRole;

  return (
    <div className="flex items-center justify-between border-b border-zinc-800 bg-zinc-900/60 px-4 py-2">
      <span className={`rounded px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${badge.color}`}>
        {badge.label}
      </span>

      <div className="flex items-center gap-2 text-sm">
        {isMyTurn ? (
          <span className="font-semibold text-cyan-400">Your Turn to {actionVerb}</span>
        ) : (
          <span className="text-zinc-500">{waitingCopy}</span>
        )}
        {actorRole ? (
          <span className="text-xs capitalize text-zinc-500">({actorRole})</span>
        ) : null}
      </div>

      <span className={`font-mono text-lg font-bold tabular-nums ${timerColor(timer)}`}>
        {timer}s
      </span>
    </div>
  );
}
