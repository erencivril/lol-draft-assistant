import { startTransition, useDeferredValue, useMemo, useState } from "react";
import type { ChampionCatalogItem } from "../api/client";

type ChampionPickerProps = {
  open: boolean;
  title: string;
  champions: ChampionCatalogItem[];
  disabledChampionIds?: number[];
  selectedChampionId?: number;
  onClose: () => void;
  onSelect: (championId: number) => void;
};

function normalizeChampionImageUrl(url: string) {
  return url.replace(".png.png", ".png");
}

export function ChampionPicker({
  open,
  title,
  champions,
  disabledChampionIds = [],
  selectedChampionId = 0,
  onClose,
  onSelect,
}: ChampionPickerProps) {
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query);
  const disabledIds = useMemo(() => new Set(disabledChampionIds), [disabledChampionIds]);
  const filteredChampions = useMemo(() => {
    const needle = deferredQuery.trim().toLowerCase();
    const items = !needle
      ? champions
      : champions.filter((champion) => {
          const haystack = `${champion.name} ${champion.key} ${champion.roles.join(" ")}`.toLowerCase();
          return haystack.includes(needle);
        });
    return items.slice(0, 80);
  }, [champions, deferredQuery]);

  if (!open) {
    return null;
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-950/80 p-4 backdrop-blur-sm"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-5xl flex-col overflow-hidden rounded-[28px] border border-zinc-800 bg-zinc-950 shadow-[0_28px_90px_rgba(0,0,0,0.45)]"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-3 border-b border-zinc-800 px-5 py-4">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-cyan-400">Champion Picker</p>
            <h2 className="text-lg font-semibold text-zinc-100">{title}</h2>
          </div>
          <button
            type="button"
            className="rounded-full border border-zinc-700 px-3 py-1.5 text-xs font-medium text-zinc-300 transition-colors hover:border-zinc-500 hover:text-zinc-100"
            onClick={onClose}
          >
            Close
          </button>
        </div>

        <div className="flex items-center gap-3 border-b border-zinc-900 px-5 py-4">
          <input
            autoFocus
            type="search"
            value={query}
            onChange={(event) => startTransition(() => setQuery(event.target.value))}
            placeholder="Search Ahri, Syndra, support..."
            className="w-full rounded-xl border border-zinc-700 bg-zinc-900 px-4 py-3 text-sm text-zinc-100 outline-none transition-colors placeholder:text-zinc-500 focus:border-cyan-500"
          />
          <button
            type="button"
            className="rounded-xl border border-zinc-700 px-3 py-2 text-xs font-medium text-zinc-300 transition-colors hover:border-zinc-500 hover:text-zinc-100"
            onClick={() => {
              onSelect(0);
              onClose();
            }}
          >
            Clear
          </button>
        </div>

        <div className="grid flex-1 gap-3 overflow-y-auto p-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {filteredChampions.map((champion) => {
            const disabled = disabledIds.has(champion.champion_id) && champion.champion_id !== selectedChampionId;
            return (
              <button
                key={champion.champion_id}
                type="button"
                disabled={disabled}
                className={`group flex items-center gap-3 rounded-2xl border px-3 py-3 text-left transition-all ${
                  champion.champion_id === selectedChampionId
                    ? "border-cyan-500/70 bg-cyan-500/10"
                    : "border-zinc-800 bg-zinc-900/70 hover:border-zinc-600 hover:bg-zinc-900"
                } disabled:cursor-not-allowed disabled:opacity-40`}
                onClick={() => {
                  onSelect(champion.champion_id);
                  onClose();
                }}
              >
                <img
                  alt={champion.name}
                  src={normalizeChampionImageUrl(champion.image_url)}
                  className="size-14 rounded-xl border border-zinc-700 object-cover"
                />
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-zinc-100">{champion.name}</p>
                  <p className="mt-0.5 text-[11px] uppercase tracking-[0.18em] text-zinc-500">{champion.key}</p>
                  <p className="mt-1 text-xs capitalize text-zinc-400">{champion.roles.join(" / ")}</p>
                </div>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
