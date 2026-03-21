import { useState } from "react";
import type {
  RuneRecommendResponse,
  RunePageRecommendation,
  RuneDefinition,
  SpellRecommendation,
} from "../types";

function formatGames(value: number) {
  if (value >= 1000) return `${(value / 1000).toFixed(1)}K`;
  return new Intl.NumberFormat("en-US").format(value);
}

function wrColor(wr: number) {
  if (wr >= 52) return "text-emerald-400";
  if (wr <= 48) return "text-red-400";
  return "text-zinc-200";
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

function SpellIcon({ spellId }: { spellId: number }) {
  const name = SPELL_NAMES[spellId] ?? `Spell ${spellId}`;
  return (
    <img
      src={spellIconUrl(spellId)}
      alt={name}
      title={name}
      className="size-7 rounded"
    />
  );
}

function SummonerSpellsSection({ spells }: { spells: SpellRecommendation[] }) {
  const [showAlts, setShowAlts] = useState(false);
  if (spells.length === 0) return null;

  const best = spells[0];
  const alts = spells.slice(1);

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-3">
      <h4 className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-600">Summoner Spells</h4>
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1.5">
          <SpellIcon spellId={best.spell1_id} />
          <SpellIcon spellId={best.spell2_id} />
        </div>
        <div className="min-w-0 flex-1">
          <span className="text-sm font-medium text-zinc-200">
            {SPELL_NAMES[best.spell1_id] ?? best.spell1_id} + {SPELL_NAMES[best.spell2_id] ?? best.spell2_id}
          </span>
          <div className="mt-0.5 flex items-center gap-3 text-[11px] text-zinc-500">
            <span>WR <span className={`font-mono font-medium ${wrColor(best.avg_win_rate)}`}>{best.avg_win_rate.toFixed(1)}%</span></span>
            <span>PR <span className="font-mono text-zinc-400">{best.pick_rate.toFixed(1)}%</span></span>
            <span>{formatGames(best.total_games)} games</span>
          </div>
        </div>
      </div>

      {alts.length > 0 ? (
        <div className="mt-2">
          <button
            type="button"
            className="text-[10px] text-cyan-500 hover:text-cyan-400"
            onClick={() => setShowAlts(!showAlts)}
          >
            {showAlts ? "Hide alternatives" : `+${alts.length} alt${alts.length > 1 ? "s" : ""}`}
          </button>
          {showAlts ? (
            <div className="mt-1.5 space-y-1.5">
              {alts.map((sp) => (
                <div key={`${sp.spell1_id}-${sp.spell2_id}`} className="flex items-center gap-2.5 text-xs">
                  <div className="flex items-center gap-1">
                    <img src={spellIconUrl(sp.spell1_id)} alt="" className="size-5 rounded" />
                    <img src={spellIconUrl(sp.spell2_id)} alt="" className="size-5 rounded" />
                  </div>
                  <span className="text-zinc-300">{SPELL_NAMES[sp.spell1_id]} + {SPELL_NAMES[sp.spell2_id]}</span>
                  <span className={`font-mono ${wrColor(sp.avg_win_rate)}`}>{sp.avg_win_rate.toFixed(1)}%</span>
                  <span className="text-zinc-600">{formatGames(sp.total_games)} games</span>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function RuneIcon({ runeId, runeLookup }: { runeId: number; runeLookup: Record<string, RuneDefinition> }) {
  const rune = runeLookup[String(runeId)];
  if (!rune) {
    return <span className="inline-block size-6 rounded-full bg-zinc-800 text-center text-[9px] leading-6 text-zinc-500">{runeId}</span>;
  }
  return (
    <img
      src={rune.image_url}
      alt={rune.name}
      title={`${rune.name} (${rune.tree_name})`}
      className="size-6 rounded-full"
    />
  );
}

function KeystoneCard({
  page,
  rank,
  runeLookup,
  onApply,
  applyDisabled,
  hasSpells,
}: {
  page: RunePageRecommendation;
  rank: number;
  runeLookup: Record<string, RuneDefinition>;
  onApply?: (keystoneId: number) => void;
  applyDisabled: boolean;
  hasSpells: boolean;
}) {
  const [open, setOpen] = useState(false);
  const rune = runeLookup[String(page.keystone_id)];
  const keystoneName = rune?.name ?? `Keystone ${page.keystone_id}`;
  const treeName = rune?.tree_name ?? "";
  const wr = page.avg_win_rate;

  return (
    <div className="rounded-[var(--radius-card)] border border-zinc-800 bg-zinc-900/40 p-3">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 shrink-0 font-mono text-xs font-bold text-zinc-600">#{rank}</span>

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <RuneIcon runeId={page.keystone_id} runeLookup={runeLookup} />
            <span className="text-sm font-semibold text-zinc-100">{keystoneName}</span>
            {treeName ? <span className="text-xs text-zinc-500">{treeName}</span> : null}
          </div>

          <div className="mt-2 flex items-center gap-4 text-xs text-zinc-400">
            <span>WR <span className={`font-mono font-medium ${wrColor(wr)}`}>{wr.toFixed(1)}%</span></span>
            <span>{formatGames(page.total_games)} games</span>
          </div>

          <div className="mt-2 flex items-center gap-2">
            {onApply ? (
              <button
                type="button"
                className="rounded bg-cyan-600 px-2.5 py-1 text-[11px] font-semibold text-white transition-colors hover:bg-cyan-500 disabled:cursor-not-allowed disabled:opacity-40"
                onClick={() => onApply(page.keystone_id)}
                disabled={applyDisabled}
                title={applyDisabled ? "Connect to League client to auto-apply" : "Apply runes and summoner spells via LCU"}
              >
                {hasSpells ? "Apply Runes & Spells" : "Apply"}
              </button>
            ) : null}

            <button
              type="button"
              className="text-[11px] font-medium text-cyan-500 hover:text-cyan-400"
              onClick={() => setOpen(!open)}
            >
              {open ? "Hide matchups" : "Show matchups"}
            </button>
          </div>

          {open && page.matchup_details.length > 0 ? (
            <div className="mt-3 space-y-1">
              <h4 className="text-[10px] font-semibold uppercase tracking-wider text-zinc-600">Per-matchup</h4>
              {page.matchup_details.map((d) => (
                <div key={`${d.opponent_id}-${d.opponent_role}`} className="flex items-center gap-3 text-xs">
                  <span className="text-zinc-300">{d.opponent_name || `ID ${d.opponent_id}`}</span>
                  <span className="text-zinc-600">{d.opponent_role}</span>
                  <span className={`font-mono ${wrColor(d.win_rate)}`}>{d.win_rate.toFixed(1)}%</span>
                  <span className="text-zinc-600">{formatGames(d.games)} games</span>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

type RunePanelProps = {
  data: RuneRecommendResponse | null;
  runeLookup: Record<string, RuneDefinition>;
  loading: boolean;
  lcuConnected: boolean;
  onApplyRunes?: (keystoneId: number) => void;
};

export function RunePanel({ data, runeLookup, loading, lcuConnected, onApplyRunes }: RunePanelProps) {
  if (loading) {
    return <p className="py-6 text-center text-xs text-zinc-600">Loading rune recommendations...</p>;
  }

  if (!data || data.rune_pages.length === 0) {
    return <p className="py-6 text-center text-xs text-zinc-600">No rune recommendations available. Lock a champion to see suggestions.</p>;
  }

  const hasSpells = (data.summoner_spells?.length ?? 0) > 0;

  return (
    <div className="flex flex-col gap-2">
      {data.fallback_used ? (
        <div className="rounded border border-amber-500/20 bg-amber-500/5 px-3 py-2">
          <p className="text-[11px] text-amber-400">Limited matchup data - showing general rune recommendations</p>
        </div>
      ) : null}

      {hasSpells ? <SummonerSpellsSection spells={data.summoner_spells} /> : null}

      {data.rune_pages.map((page, i) => (
        <KeystoneCard
          key={page.keystone_id}
          page={page}
          rank={i + 1}
          runeLookup={runeLookup}
          onApply={onApplyRunes}
          applyDisabled={!lcuConnected}
          hasSpells={hasSpells}
        />
      ))}
    </div>
  );
}
