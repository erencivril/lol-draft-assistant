import { useState } from "react";
import type {
  BuildRecommendResponse,
  BuildSlot,
  ItemDefinition,
  ItemMatchupContribution,
  ItemRecommendation,
  MatchupSummary,
  RuneDefinition,
} from "../types";

type ChampionInfo = {
  champion_id: number;
  name: string;
  image_url: string;
};

function formatGames(value: number) {
  if (value >= 1000) return `${(value / 1000).toFixed(1)}K`;
  return new Intl.NumberFormat("en-US").format(value);
}

function weightLabel(w: number) {
  if (w >= 4) return "Lane";
  if (w >= 2) return "Jg";
  return "Other";
}

function weightBadge(w: number) {
  if (w >= 4) return "rounded px-1.5 py-0.5 text-[9px] font-semibold bg-cyan-500/15 text-cyan-400";
  if (w >= 2) return "rounded px-1.5 py-0.5 text-[9px] font-semibold bg-amber-500/15 text-amber-400";
  return "rounded px-1.5 py-0.5 text-[9px] font-semibold bg-zinc-800 text-zinc-500";
}

function ItemIcon({ itemId, itemLookup }: { itemId: number; itemLookup: Record<string, ItemDefinition> }) {
  const item = itemLookup[String(itemId)];
  if (!item) {
    return <span className="inline-block size-8 rounded bg-zinc-800 text-center text-[9px] leading-8 text-zinc-500">{itemId}</span>;
  }
  return (
    <img
      src={item.image_url}
      alt={item.name}
      title={`${item.name} (${item.gold}g)`}
      className="size-8 rounded"
    />
  );
}

function MatchupContributions({ contributions }: { contributions: ItemMatchupContribution[] }) {
  if (!contributions || contributions.length === 0) return null;
  return (
    <div className="mt-1.5 space-y-0.5">
      {contributions.map((c) => (
        <div key={`${c.opponent_id}-${c.opponent_role}`} className="flex items-center gap-2 text-xs">
          <span className={weightBadge(c.position_weight ?? 1)}>
            {weightLabel(c.position_weight ?? 1)}
          </span>
          <span className="text-zinc-300">{c.opponent_name || `ID ${c.opponent_id}`}</span>
          <span className="font-mono text-zinc-400">{c.win_rate.toFixed(1)}%</span>
          <span className="text-zinc-600">{formatGames(c.games)} games</span>
        </div>
      ))}
    </div>
  );
}

function ItemCard({
  item,
  itemLookup,
  showMatchups,
}: {
  item: ItemRecommendation;
  itemLookup: Record<string, ItemDefinition>;
  showMatchups: boolean;
}) {
  const def = itemLookup[String(item.item_id)];
  const name = def?.name ?? `Item ${item.item_id}`;

  return (
    <div>
      <div className="flex items-center gap-2">
        <ItemIcon itemId={item.item_id} itemLookup={itemLookup} />
        <div className="min-w-0 flex-1">
          <span className="text-xs font-medium text-zinc-200">{name}</span>
          <div className="flex items-center gap-3 text-[11px] text-zinc-500">
            <span>WR <span className="font-mono text-zinc-300">{item.avg_win_rate.toFixed(1)}%</span></span>
            <span>{formatGames(item.total_games)} games</span>
          </div>
        </div>
      </div>
      {showMatchups ? <MatchupContributions contributions={item.matchup_contributions} /> : null}
    </div>
  );
}

function SlotRow({
  slot,
  itemLookup,
}: {
  slot: BuildSlot;
  itemLookup: Record<string, ItemDefinition>;
}) {
  const [showAlts, setShowAlts] = useState(false);
  const [showMatchups, setShowMatchups] = useState(false);
  const slotLabel = slot.slot_name === "starter" ? "Start" : slot.slot_name === "boots" ? "Boots" : slot.slot_name.replace("item", "Item ");

  const hasContributions = (slot.primary?.matchup_contributions?.length ?? 0) > 0;

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-2.5">
      <div className="flex items-center gap-2">
        <span className="w-12 shrink-0 text-[10px] font-semibold uppercase tracking-wider text-zinc-600">{slotLabel}</span>
        {slot.primary ? (
          <div className="min-w-0 flex-1">
            <ItemCard item={slot.primary} itemLookup={itemLookup} showMatchups={showMatchups} />
          </div>
        ) : (
          <span className="text-xs text-zinc-600">No data</span>
        )}
      </div>

      <div className="mt-1 flex items-center gap-3 pl-14">
        {hasContributions ? (
          <button
            type="button"
            className="text-[10px] text-cyan-500 hover:text-cyan-400"
            onClick={() => setShowMatchups(!showMatchups)}
          >
            {showMatchups ? "Hide matchups" : "Show matchups"}
          </button>
        ) : null}

        {slot.alternatives.length > 0 ? (
          <button
            type="button"
            className="text-[10px] text-cyan-500 hover:text-cyan-400"
            onClick={() => setShowAlts(!showAlts)}
          >
            {showAlts ? "Hide alternatives" : `+${slot.alternatives.length} alt${slot.alternatives.length > 1 ? "s" : ""}`}
          </button>
        ) : null}
      </div>

      {showAlts && slot.alternatives.length > 0 ? (
        <div className="mt-1.5 space-y-1.5 pl-14">
          {slot.alternatives.map((alt) => (
            <ItemCard key={alt.item_id} item={alt} itemLookup={itemLookup} showMatchups={showMatchups} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function MatchupHeader({
  summaries,
  championLookup,
}: {
  summaries: MatchupSummary[];
  championLookup: Map<number, ChampionInfo>;
}) {
  if (summaries.length === 0) return null;

  const sorted = [...summaries].sort((a, b) => b.position_weight - a.position_weight);

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-2.5">
      <h4 className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-600">Matchup Sources</h4>
      <div className="space-y-1">
        {sorted.map((m) => {
          const champ = championLookup.get(m.opponent_id);
          const wrColor = m.overall_win_rate >= 52 ? "text-emerald-400" : m.overall_win_rate <= 48 ? "text-red-400" : "text-zinc-300";
          return (
            <div key={`${m.opponent_id}-${m.opponent_role}`} className="flex items-center gap-2 text-xs">
              <span className={weightBadge(m.position_weight)}>
                {weightLabel(m.position_weight)}
              </span>
              {champ ? (
                <img src={champ.image_url} alt={champ.name} className="size-5 rounded" />
              ) : null}
              <span className="text-zinc-200">{m.opponent_name || `ID ${m.opponent_id}`}</span>
              <span className="text-zinc-600">{m.opponent_role}</span>
              <span className={`font-mono ${wrColor}`}>{m.overall_win_rate.toFixed(1)}%</span>
              <span className="text-zinc-600">{formatGames(m.total_games)} games</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

type BuildPanelProps = {
  data: BuildRecommendResponse | null;
  itemLookup: Record<string, ItemDefinition>;
  loading: boolean;
  championLookup?: Map<number, ChampionInfo>;
  runeLookup?: Record<string, RuneDefinition>;
};

export function BuildPanel({ data, itemLookup, loading, championLookup, runeLookup }: BuildPanelProps) {
  if (loading) {
    return <p className="py-6 text-center text-xs text-zinc-600">Loading build recommendations...</p>;
  }

  if (!data || data.slots.length === 0) {
    return <p className="py-6 text-center text-xs text-zinc-600">Select enemies to see build recommendations</p>;
  }

  const keystoneUsed = data.keystone_used ?? null;
  const matchupSummaries = data.matchup_summaries ?? [];
  const keystoneName = keystoneUsed && runeLookup
    ? runeLookup[String(keystoneUsed)]?.name ?? null
    : null;

  return (
    <div className="flex flex-col gap-2">
      {data.fallback_used ? (
        <div className="rounded border border-amber-500/20 bg-amber-500/5 px-3 py-2">
          <p className="text-[11px] text-amber-400">Limited matchup data - showing general build</p>
        </div>
      ) : null}

      {keystoneUsed != null ? (
        <div className="rounded border border-cyan-500/20 bg-cyan-500/5 px-3 py-2">
          <div className="flex items-center gap-2">
            {runeLookup?.[String(keystoneUsed)]?.image_url ? (
              <img
                src={runeLookup[String(keystoneUsed)].image_url}
                alt={keystoneName ?? ""}
                className="size-4"
              />
            ) : null}
            <p className="text-[11px] text-cyan-400">
              Build optimized for {keystoneName ?? `Keystone ${keystoneUsed}`} — items weighted for keystone coherence
            </p>
          </div>
        </div>
      ) : null}

      {championLookup && matchupSummaries.length > 0 ? (
        <MatchupHeader summaries={matchupSummaries} championLookup={championLookup} />
      ) : null}

      {data.skill_order ? (
        <div className="flex items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-900/40 px-3 py-2">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-zinc-600">Skill Order</span>
          <span className="font-mono text-sm font-semibold tracking-widest text-zinc-200">{data.skill_order}</span>
        </div>
      ) : null}

      {data.slots.map((slot) => (
        <SlotRow key={slot.slot_name} slot={slot} itemLookup={itemLookup} />
      ))}
    </div>
  );
}
