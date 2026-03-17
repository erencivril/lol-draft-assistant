import { useState } from "react";
import type {
  RuneRecommendResponse,
  RunePageRecommendation,
  RuneDefinition,
} from "../types";

function formatGames(value: number) {
  return new Intl.NumberFormat("en-US").format(value);
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
}: {
  page: RunePageRecommendation;
  rank: number;
  runeLookup: Record<string, RuneDefinition>;
  onApply?: (keystoneId: number) => void;
  applyDisabled: boolean;
}) {
  const [open, setOpen] = useState(false);
  const rune = runeLookup[String(page.keystone_id)];
  const keystoneName = rune?.name ?? `Keystone ${page.keystone_id}`;
  const treeName = rune?.tree_name ?? "";

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
            <span>WR <span className="font-mono font-medium text-zinc-200">{page.avg_win_rate.toFixed(1)}%</span></span>
            <span>{formatGames(page.total_games)} games</span>
          </div>

          <div className="mt-2 flex items-center gap-2">
            {onApply ? (
              <button
                type="button"
                className="rounded bg-cyan-600 px-2.5 py-1 text-[11px] font-semibold text-white transition-colors hover:bg-cyan-500 disabled:cursor-not-allowed disabled:opacity-40"
                onClick={() => onApply(page.keystone_id)}
                disabled={applyDisabled}
                title={applyDisabled ? "Connect to League client to auto-apply" : "Apply this rune page via LCU"}
              >
                Apply
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
                  <span className="font-mono text-zinc-400">{d.win_rate.toFixed(1)}%</span>
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

  return (
    <div className="flex flex-col gap-2">
      {data.fallback_used ? (
        <div className="rounded border border-amber-500/20 bg-amber-500/5 px-3 py-2">
          <p className="text-[11px] text-amber-400">Limited matchup data - showing general rune recommendations</p>
        </div>
      ) : null}

      {data.rune_pages.map((page, i) => (
        <KeystoneCard
          key={page.keystone_id}
          page={page}
          rank={i + 1}
          runeLookup={runeLookup}
          onApply={onApplyRunes}
          applyDisabled={!lcuConnected}
        />
      ))}
    </div>
  );
}
