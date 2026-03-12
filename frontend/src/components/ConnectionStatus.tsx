import type { StatusPayload } from "../types";

export type LcuConnectionState = {
  connected: boolean;
  status: string;
  lastUpdatedAt: string | null;
};

type ConnectionStatusProps = {
  apiBaseUrl: string;
  status: StatusPayload | null;
  lcu: LcuConnectionState;
};

function Dot({ tone }: { tone: "online" | "warn" | "offline" }) {
  const className =
    tone === "online" ? "bg-emerald-400" : tone === "warn" ? "bg-amber-400" : "bg-rose-400";
  return <span className={`inline-block size-2.5 rounded-full ${className}`} aria-hidden="true" />;
}

function formatHostLabel(value: string) {
  try {
    return new URL(value).host;
  } catch {
    return value;
  }
}

function formatTime(value: string | null) {
  if (!value) {
    return "No events yet";
  }
  return new Date(value).toLocaleTimeString("tr-TR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function ConnectionStatus({ apiBaseUrl, status, lcu }: ConnectionStatusProps) {
  const serverTone = status ? "online" : "offline";
  const dataTone = status?.exact_data_available
    ? "online"
    : status
      ? "warn"
      : "offline";
  const lcuTone = lcu.connected ? "online" : "warn";

  return (
    <section className="grid gap-4 lg:grid-cols-3">
      <article className="rounded-[var(--radius-panel)] border border-zinc-800 bg-zinc-900/55 p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-zinc-500">Server</p>
            <h2 className="text-lg font-semibold text-zinc-100">Hetzner API</h2>
          </div>
          <div className="flex items-center gap-2 text-xs text-zinc-300">
            <Dot tone={serverTone} />
            {status ? "Reachable" : "Offline"}
          </div>
        </div>
        <p className="mt-3 text-sm text-zinc-400">{formatHostLabel(apiBaseUrl)}</p>
        <div className="mt-4 grid gap-2 text-xs text-zinc-500">
          <div className="flex items-center justify-between">
            <span>Patch</span>
            <span className="text-zinc-300">{status?.latest_patch ?? "-"}</span>
          </div>
          <div className="flex items-center justify-between">
            <span>Scope</span>
            <span className="text-zinc-300">{status?.scope_freshness ?? "unknown"}</span>
          </div>
        </div>
      </article>

      <article className="rounded-[var(--radius-panel)] border border-zinc-800 bg-zinc-900/55 p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-zinc-500">Client</p>
            <h2 className="text-lg font-semibold text-zinc-100">Local LCU</h2>
          </div>
          <div className="flex items-center gap-2 text-xs text-zinc-300">
            <Dot tone={lcuTone} />
            {lcu.connected ? "Connected" : "Waiting"}
          </div>
        </div>
        <p className="mt-3 text-sm text-zinc-400">{lcu.status}</p>
        <div className="mt-4 flex items-center justify-between text-xs text-zinc-500">
          <span>Last update</span>
          <span className="text-zinc-300">{formatTime(lcu.lastUpdatedAt)}</span>
        </div>
      </article>

      <article className="rounded-[var(--radius-panel)] border border-zinc-800 bg-zinc-900/55 p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-zinc-500">Data</p>
            <h2 className="text-lg font-semibold text-zinc-100">Recommendation health</h2>
          </div>
          <div className="flex items-center gap-2 text-xs text-zinc-300">
            <Dot tone={dataTone} />
            {status?.exact_data_available ? "Exact" : status ? "Partial" : "Unknown"}
          </div>
        </div>
        <div className="mt-4 grid gap-2 text-xs text-zinc-500">
          <div className="flex items-center justify-between">
            <span>Region / rank</span>
            <span className="text-zinc-300">
              {status?.effective_region ?? "-"} / {status?.effective_rank_tier ?? "-"}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span>Warnings</span>
            <span className="text-zinc-300">{status?.recommendation_warnings.length ?? 0}</span>
          </div>
          <div className="flex items-center justify-between">
            <span>Trusted patch</span>
            <span className="text-zinc-300">{status?.patch_trusted ? "Yes" : "No"}</span>
          </div>
        </div>
      </article>
    </section>
  );
}
