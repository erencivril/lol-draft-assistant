import type { StatusPayload } from "../types";

type StatusBarProps = {
  status: StatusPayload | null;
  socketConnected: boolean;
  adminOpen: boolean;
  onToggleAdmin: () => void;
};

function ConnectionDot({ label, connected, warn }: { label: string; connected: boolean; warn?: boolean }) {
  const color = connected
    ? warn
      ? "bg-amber-400"
      : "bg-emerald-400"
    : "bg-red-400";
  return (
    <span className="flex items-center gap-1.5 text-xs text-zinc-400">
      <span className={`inline-block size-2 rounded-full ${color}`} />
      {label}
    </span>
  );
}

export function StatusBar({ status, socketConnected, adminOpen, onToggleAdmin }: StatusBarProps) {
  const region = status?.effective_region ?? "?";
  const rank = status?.effective_rank_tier?.replace(/_/g, " ") ?? "?";
  const role = status?.effective_role ?? "?";

  return (
    <header className="sticky top-0 z-40 flex h-12 items-center justify-between border-b border-zinc-800 bg-zinc-950/80 px-4 backdrop-blur-md">
      <span className="text-sm font-semibold tracking-tight text-zinc-100">
        Draft Assistant
      </span>

      <div className="flex items-center gap-2">
        <span className="rounded-full bg-zinc-800 px-2.5 py-0.5 text-xs font-medium text-zinc-300">
          {region}
        </span>
        <span className="rounded-full bg-zinc-800 px-2.5 py-0.5 text-xs font-medium capitalize text-zinc-300">
          {rank}
        </span>
        <span className="rounded-full bg-zinc-800 px-2.5 py-0.5 text-xs font-medium capitalize text-zinc-300">
          {role}
        </span>
      </div>

      <div className="flex items-center gap-3">
        <ConnectionDot label="Bridge" connected={status?.bridge_connected ?? false} warn={(status?.bridge_connected ?? false) && !(status?.lcu_connected ?? false)} />
        <ConnectionDot label="LCU" connected={status?.lcu_connected ?? false} />
        <ConnectionDot label="Socket" connected={socketConnected} warn={socketConnected && !status?.lcu_connected} />
        <button
          type="button"
          className={`rounded-lg border px-2.5 py-1 text-[11px] font-semibold transition-colors ${
            adminOpen
              ? "border-cyan-500/60 bg-cyan-500/15 text-cyan-300"
              : "border-zinc-700 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
          }`}
          onClick={onToggleAdmin}
        >
          {adminOpen ? "Close admin" : "Admin"}
        </button>
      </div>
    </header>
  );
}
