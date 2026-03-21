import { useState } from "react";
import type {
  BuildRecommendResponse,
  BuildSlot,
  ItemDefinition,
  ItemMatchupContribution,
  ItemRecommendation,
  MatchupSummary,
  RuneDefinition,
  SpellRecommendation,
  SkillEarlyLevel,
  SkillPathRecommendation,
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

function wrColor(wr: number) {
  if (wr >= 52) return "text-emerald-400";
  if (wr <= 48) return "text-red-400";
  return "text-zinc-300";
}

function roleLabel(role: string): string {
  switch (role) {
    case "top": return "Top";
    case "jungle": return "Jg";
    case "middle": return "Mid";
    case "bottom": return "Bot";
    case "support": return "Sup";
    default: return "?";
  }
}

function weightBadge(w: number) {
  if (w >= 4) return "rounded px-1.5 py-0.5 text-[9px] font-semibold bg-cyan-500/15 text-cyan-400";
  if (w >= 2) return "rounded px-1.5 py-0.5 text-[9px] font-semibold bg-amber-500/15 text-amber-400";
  return "rounded px-1.5 py-0.5 text-[9px] font-semibold bg-zinc-800 text-zinc-500";
}

const SPELL_NAMES: Record<number, string> = {
  1: "Cleanse", 3: "Exhaust", 4: "Flash", 6: "Ghost",
  7: "Heal", 11: "Smite", 12: "Teleport", 14: "Ignite",
  21: "Barrier", 32: "Snowball",
};

const SPELL_KEYS: Record<number, string> = {
  1: "SummonerBoost", 3: "SummonerExhaust", 4: "SummonerFlash", 6: "SummonerHaste",
  7: "SummonerHeal", 11: "SummonerSmite", 12: "SummonerTeleport", 14: "SummonerDot",
  21: "SummonerBarrier", 32: "SummonerSnowball",
};

function spellIconUrl(spellId: number): string {
  const key = SPELL_KEYS[spellId] ?? "SummonerFlash";
  return `https://ddragon.leagueoflegends.com/cdn/15.6.1/img/spell/${key}.png`;
}

const ABILITY_COLORS: Record<string, string> = {
  Q: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  W: "bg-green-500/20 text-green-400 border-green-500/30",
  E: "bg-orange-500/20 text-orange-400 border-orange-500/30",
  R: "bg-purple-500/20 text-purple-400 border-purple-500/30",
};

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
            {roleLabel(c.opponent_role)}
          </span>
          <span className="text-zinc-300">{c.opponent_name || `ID ${c.opponent_id}`}</span>
          <span className={`font-mono ${wrColor(c.win_rate)}`}>{c.win_rate.toFixed(1)}%</span>
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
  const wr = item.avg_win_rate;

  return (
    <div>
      <div className="flex items-center gap-2">
        <ItemIcon itemId={item.item_id} itemLookup={itemLookup} />
        <div className="min-w-0 flex-1">
          <span className="text-xs font-medium text-zinc-200">{name}</span>
          <div className="flex items-center gap-3 text-[11px] text-zinc-500">
            <span>WR <span className={`font-mono ${wrColor(wr)}`}>{wr.toFixed(1)}%</span></span>
            <span>{formatGames(item.total_games)} games</span>
            {item.matchup_contributions.length > 0 ? (
              <span className="rounded bg-zinc-800 px-1 py-0.5 text-[9px] text-zinc-500">
                {item.matchup_contributions.length} matchup{item.matchup_contributions.length > 1 ? "s" : ""}
              </span>
            ) : null}
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

function SummonerSpellsSummary({ spells }: { spells: SpellRecommendation[] }) {
  if (spells.length === 0) return null;
  const best = spells[0];
  return (
    <div className="flex items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-900/40 px-3 py-2">
      <span className="text-[10px] font-semibold uppercase tracking-wider text-zinc-600">Spells</span>
      <div className="flex items-center gap-1">
        <img src={spellIconUrl(best.spell1_id)} alt="" className="size-5 rounded" />
        <img src={spellIconUrl(best.spell2_id)} alt="" className="size-5 rounded" />
      </div>
      <span className="text-xs text-zinc-300">{SPELL_NAMES[best.spell1_id]} + {SPELL_NAMES[best.spell2_id]}</span>
      <span className={`font-mono text-xs ${wrColor(best.avg_win_rate)}`}>{best.avg_win_rate.toFixed(1)}%</span>
      <span className="text-[11px] text-zinc-600">{formatGames(best.total_games)} games</span>
    </div>
  );
}

function SkillOrderSection({
  skillOrder,
  skillEarly,
  skillPaths,
}: {
  skillOrder: string | null;
  skillEarly: SkillEarlyLevel[];
  skillPaths: SkillPathRecommendation[];
}) {
  const [showDetail, setShowDetail] = useState(false);
  const paths6 = skillPaths.filter((p) => p.through_level === 6);
  const paths15 = skillPaths.filter((p) => p.through_level === 15);
  const hasDetail = skillEarly.length > 0 || paths6.length > 0 || paths15.length > 0;

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-zinc-600">Skill Order</span>
          {skillOrder ? (
            <div className="flex items-center gap-1">
              {skillOrder.split("").map((letter, i) => (
                <span
                  key={i}
                  className={`rounded border px-1.5 py-0.5 text-xs font-bold ${ABILITY_COLORS[letter] ?? "bg-zinc-800 text-zinc-400 border-zinc-700"}`}
                >
                  {letter}
                </span>
              ))}
              <span className="ml-1 text-[10px] text-zinc-600">max</span>
            </div>
          ) : null}
        </div>
        {hasDetail ? (
          <button
            type="button"
            className="text-[10px] text-cyan-500 hover:text-cyan-400"
            onClick={() => setShowDetail(!showDetail)}
          >
            {showDetail ? "Hide detail" : "Show detail"}
          </button>
        ) : null}
      </div>

      {/* Level 1-3 priority - always visible if available */}
      {skillEarly.length > 0 ? (
        <div className="mt-2 flex items-center gap-3">
          {skillEarly.map((se) => (
            <div key={se.level} className="flex items-center gap-1.5 text-[11px]">
              <span className="text-zinc-600">Lv{se.level}</span>
              <span className={`rounded border px-1 py-0.5 text-[10px] font-bold ${ABILITY_COLORS[se.best_ability] ?? ""}`}>
                {se.best_ability}
              </span>
              <span className={`font-mono ${wrColor(se.win_rate)}`}>{se.win_rate.toFixed(1)}%</span>
              <span className="text-zinc-600">{se.pick_rate.toFixed(0)}% PR</span>
            </div>
          ))}
        </div>
      ) : null}

      {showDetail ? (
        <div className="mt-3 space-y-3">
          {/* Skill path through level 6 */}
          {paths6.length > 0 ? (
            <div>
              <h5 className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-600">Skill Path (Lv 1-6)</h5>
              <div className="space-y-1.5">
                {paths6.map((path, i) => (
                  <div key={path.sequence} className="flex items-center gap-2">
                    <span className="w-5 shrink-0 font-mono text-[10px] font-bold text-zinc-600">#{i + 1}</span>
                    <div className="flex items-center gap-0.5">
                      {path.abilities.map((ability, j) => (
                        <span
                          key={j}
                          className={`size-5 rounded border text-center text-[10px] font-bold leading-5 ${ABILITY_COLORS[ability] ?? "bg-zinc-800 text-zinc-400 border-zinc-700"}`}
                        >
                          {ability}
                        </span>
                      ))}
                    </div>
                    <span className={`font-mono text-[11px] ${wrColor(path.avg_win_rate)}`}>{path.avg_win_rate.toFixed(1)}%</span>
                    <span className="text-[10px] text-zinc-600">{formatGames(path.total_games)} games</span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {/* Skill path through level 15 */}
          {paths15.length > 0 ? (
            <div>
              <h5 className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-600">Full Skill Path (Lv 1-15)</h5>
              <div className="space-y-1.5">
                {paths15.map((path, i) => (
                  <div key={path.sequence}>
                    <div className="flex items-center gap-2">
                      <span className="w-5 shrink-0 font-mono text-[10px] font-bold text-zinc-600">#{i + 1}</span>
                      <div className="flex flex-wrap items-center gap-0.5">
                        {path.abilities.map((ability, j) => (
                          <span
                            key={j}
                            className={`size-4 rounded border text-center text-[8px] font-bold leading-4 ${ABILITY_COLORS[ability] ?? "bg-zinc-800 text-zinc-400 border-zinc-700"}`}
                          >
                            {ability}
                          </span>
                        ))}
                      </div>
                      <span className={`font-mono text-[11px] ${wrColor(path.avg_win_rate)}`}>{path.avg_win_rate.toFixed(1)}%</span>
                      <span className="text-[10px] text-zinc-600">{formatGames(path.total_games)}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {/* Level 1-3 alternatives */}
          {skillEarly.some((se) => se.alternatives.length > 0) ? (
            <div>
              <h5 className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-600">Early Levels Detail</h5>
              <div className="space-y-1">
                {skillEarly.map((se) => (
                  <div key={se.level} className="flex items-start gap-2 text-[11px]">
                    <span className="mt-0.5 w-6 shrink-0 text-zinc-600">Lv{se.level}</span>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={`rounded border px-1 py-0.5 text-[10px] font-bold ${ABILITY_COLORS[se.best_ability] ?? ""}`}>
                        {se.best_ability} {se.win_rate.toFixed(1)}% / {se.pick_rate.toFixed(0)}%
                      </span>
                      {se.alternatives.map((alt) => (
                        <span
                          key={alt.ability}
                          className="rounded bg-zinc-800 px-1 py-0.5 text-[10px] text-zinc-500"
                        >
                          {alt.ability} {alt.wr.toFixed(1)}% / {alt.pr.toFixed(0)}%
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
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
          return (
            <div key={`${m.opponent_id}-${m.opponent_role}`} className="flex items-center gap-2 text-xs">
              <span className={weightBadge(m.position_weight)}>
                {roleLabel(m.opponent_role)}
              </span>
              {champ ? (
                <img src={champ.image_url} alt={champ.name} className="size-5 rounded" />
              ) : null}
              <span className="text-zinc-200">{m.opponent_name || `ID ${m.opponent_id}`}</span>
              <span className="text-zinc-600">{m.opponent_role}</span>
              <span className={`font-mono ${wrColor(m.overall_win_rate)}`}>{m.overall_win_rate.toFixed(1)}%</span>
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

      {/* Summoner Spells Summary */}
      {data.summoner_spells?.length > 0 ? (
        <SummonerSpellsSummary spells={data.summoner_spells} />
      ) : null}

      {/* Enhanced Skill Order Section */}
      <SkillOrderSection
        skillOrder={data.skill_order}
        skillEarly={data.skill_early ?? []}
        skillPaths={data.skill_paths ?? []}
      />

      {data.slots.map((slot) => (
        <SlotRow key={slot.slot_name} slot={slot} itemLookup={itemLookup} />
      ))}
    </div>
  );
}
