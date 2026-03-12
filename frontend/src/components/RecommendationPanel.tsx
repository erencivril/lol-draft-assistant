import { useState } from "react";
import type {
  RecommendationBundle,
  RecommendationItem,
  RecommendationRelationDetail,
  RecommendationScoreComponent,
} from "../types";

function formatGames(value: number) {
  return new Intl.NumberFormat("en-US").format(value);
}

function confidenceColor(score: number) {
  if (score >= 70) return "bg-emerald-500";
  if (score >= 40) return "bg-amber-400";
  return "bg-red-400";
}

function confidenceTextColor(score: number) {
  if (score >= 70) return "text-emerald-400";
  if (score >= 40) return "text-amber-400";
  return "text-red-400";
}

function bandLabel(band: RecommendationItem["display_band"]) {
  if (band === "elite") return "Elite";
  if (band === "strong") return "Strong";
  if (band === "situational") return "Situational";
  return "Risky";
}

function signedTextClass(value: number) {
  if (value > 0) return "text-emerald-400";
  if (value < 0) return "text-red-400";
  return "text-zinc-400";
}

function relationLabel(detail: RecommendationRelationDetail) {
  if (detail.kind === "counter") return "Counter";
  if (detail.kind === "synergy") return "Synergy";
  if (detail.kind === "threat") return "Threat";
  return "Enemy combo";
}

function ScoreDetail({ component }: { component: RecommendationScoreComponent }) {
  return (
    <tr className="border-b border-zinc-800 last:border-0">
      <td className="py-1.5 pr-3 text-xs text-zinc-400">{component.label}</td>
      <td className={`py-1.5 pr-3 text-right font-mono text-xs ${signedTextClass(component.value)}`}>{component.value.toFixed(2)}</td>
      <td className="py-1.5 pr-3 text-right font-mono text-xs text-zinc-500">x{component.weight.toFixed(2)}</td>
      <td className={`py-1.5 text-right font-mono text-xs ${signedTextClass(component.contribution)}`}>{component.contribution.toFixed(2)}</td>
    </tr>
  );
}

function RelationChip({ detail }: { detail: RecommendationRelationDetail }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-2.5">
      <div className="flex items-center gap-2">
        <span className="text-xs font-medium text-zinc-200">
          {detail.champion_name}{detail.role ? ` (${detail.role})` : ""}
        </span>
        <span className="text-[10px] text-zinc-600">{relationLabel(detail)}</span>
      </div>
      <div className="mt-1 text-[11px] text-zinc-500">
        {detail.metric_label} {detail.metric_value >= 0 ? "+" : ""}{detail.metric_value.toFixed(1)} | WR {detail.win_rate.toFixed(1)}% | {formatGames(detail.games)} games
      </div>
      <div className="mt-1 flex items-center gap-3 text-[10px] text-zinc-600">
        <span className={signedTextClass(detail.signed_edge)}>edge {detail.signed_edge >= 0 ? "+" : ""}{detail.signed_edge.toFixed(2)}</span>
        <span>weight {(detail.shrinkage_weight * 100).toFixed(0)}%</span>
        <span className={signedTextClass(detail.net_contribution)}>net {detail.net_contribution >= 0 ? "+" : ""}{detail.net_contribution.toFixed(2)}</span>
      </div>
    </div>
  );
}

function RecommendationCard({ item, rank, isBan }: { item: RecommendationItem; rank: number; isBan: boolean }) {
  const [open, setOpen] = useState(false);
  const scorePercent = Math.min(Math.max(item.total_score, 0), 100);
  const counterTitle = isBan ? "Threat edges" : "Counter edges";
  const synergyTitle = isBan ? "Enemy synergy" : "Synergy edges";

  return (
    <div className="rounded-[var(--radius-card)] border border-zinc-800 bg-zinc-900/40 p-3">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 shrink-0 font-mono text-xs font-bold text-zinc-600">#{rank}</span>

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-zinc-100">{item.champion_name}</span>
            <span className="text-xs capitalize text-zinc-500">{item.suggested_role}</span>
            <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] font-medium text-zinc-300">{bandLabel(item.display_band)}</span>
            {item.thin_evidence ? (
              <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-medium text-amber-400">thin evidence</span>
            ) : null}
          </div>

          <div className="mt-2 flex items-center gap-2">
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-zinc-800">
              <div
                className={`h-full rounded-full transition-all ${confidenceColor(scorePercent)}`}
                style={{ width: `${scorePercent}%` }}
              />
            </div>
            <span className={`shrink-0 font-mono text-xs font-bold ${confidenceTextColor(scorePercent)}`}>
              {item.total_score.toFixed(1)}
            </span>
          </div>

          <p className="mt-1.5 text-xs leading-relaxed text-zinc-500">
            {item.explanation.summary || item.reasons.join(" · ")}
          </p>

          <button
            type="button"
            className="mt-2 text-[11px] font-medium text-cyan-500 hover:text-cyan-400"
            onClick={() => setOpen(!open)}
          >
            {open ? "Hide details" : "Show details"}
          </button>

          {open ? (
            <div className="mt-3 space-y-4">
              {item.explanation.scenario_summary ? (
                <p className="text-xs italic text-zinc-500">{item.explanation.scenario_summary}</p>
              ) : null}

              {item.explanation.scoring.length > 0 ? (
                <div>
                  <h4 className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-600">Score breakdown</h4>
                  <table className="w-full">
                    <tbody>
                      {item.explanation.scoring.map((c) => (
                        <ScoreDetail component={c} key={c.key} />
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}

              {item.explanation.counters.length > 0 ? (
                <div>
                  <h4 className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-600">{counterTitle}</h4>
                  <div className="grid gap-1.5">
                    {item.explanation.counters.map((d) => (
                      <RelationChip detail={d} key={`${d.kind}-${d.champion_id}-${d.role ?? "none"}`} />
                    ))}
                  </div>
                </div>
              ) : null}

              {item.explanation.synergies.length > 0 ? (
                <div>
                  <h4 className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-600">{synergyTitle}</h4>
                  <div className="grid gap-1.5">
                    {item.explanation.synergies.map((d) => (
                      <RelationChip detail={d} key={`${d.kind}-${d.champion_id}-${d.role ?? "none"}`} />
                    ))}
                  </div>
                </div>
              ) : null}

              {item.explanation.penalties.length > 0 ? (
                <div>
                  <h4 className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-600">Penalties</h4>
                  {item.explanation.penalties.map((p) => (
                    <p key={p} className="text-xs text-zinc-500">{p}</p>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

type RecommendationTabsProps = {
  picks: RecommendationItem[];
  bans: RecommendationItem[];
  bundle: RecommendationBundle;
  defaultTab: "picks" | "bans";
};

function TrustDots({ bundle }: { bundle: RecommendationBundle }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className={`inline-block size-1.5 rounded-full ${bundle.patch_trusted ? "bg-emerald-400" : "bg-red-400"}`} />
      <span className={`inline-block size-1.5 rounded-full ${bundle.scope_complete ? "bg-emerald-400" : "bg-amber-400"}`} />
      <span className={`inline-block size-1.5 rounded-full ${bundle.scope_ready ? "bg-cyan-400" : "bg-zinc-600"}`} />
    </div>
  );
}

export function RecommendationPanel({ picks, bans, bundle, defaultTab }: RecommendationTabsProps) {
  const [activeTab, setActiveTab] = useState<"picks" | "bans">(defaultTab);
  const items = activeTab === "picks" ? picks : bans;
  const isBan = activeTab === "bans";

  return (
    <section>
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-1">
          <button
            type="button"
            className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
              activeTab === "picks"
                ? "bg-zinc-800 text-zinc-100"
                : "text-zinc-500 hover:text-zinc-300"
            }`}
            onClick={() => setActiveTab("picks")}
          >
            Picks ({picks.length})
          </button>
          <button
            type="button"
            className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
              activeTab === "bans"
                ? "bg-zinc-800 text-zinc-100"
                : "text-zinc-500 hover:text-zinc-300"
            }`}
            onClick={() => setActiveTab("bans")}
          >
            Bans ({bans.length})
          </button>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-[11px] text-zinc-600">
            {bundle.region ?? "?"} / {bundle.rank_tier?.replace(/_/g, " ") ?? "?"} / {bundle.patch ?? "?"}
          </span>
          <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-zinc-400">
            {bundle.scope_freshness}
          </span>
          {bundle.fallback_used_recently ? (
            <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-amber-400">
              fallback used
            </span>
          ) : null}
          <TrustDots bundle={bundle} />
        </div>
      </div>

      <div className="flex flex-col gap-2">
        {items.length === 0 ? (
          <p className="py-6 text-center text-xs text-zinc-600">No recommendations available yet.</p>
        ) : null}
        {items.map((item, i) => (
          <RecommendationCard
            key={`${activeTab}-${item.champion_id}-${i}`}
            item={item}
            rank={i + 1}
            isBan={isBan}
          />
        ))}
      </div>
    </section>
  );
}
