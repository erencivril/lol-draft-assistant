import { useState } from "react";
import type {
  BuildRecommendResponse,
  BuildSlot,
  ItemDefinition,
  ItemRecommendation,
} from "../types";

function formatGames(value: number) {
  return new Intl.NumberFormat("en-US").format(value);
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

function ItemCard({
  item,
  itemLookup,
}: {
  item: ItemRecommendation;
  itemLookup: Record<string, ItemDefinition>;
}) {
  const def = itemLookup[String(item.item_id)];
  const name = def?.name ?? `Item ${item.item_id}`;

  return (
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
  const slotLabel = slot.slot_name === "starter" ? "Start" : slot.slot_name === "boots" ? "Boots" : slot.slot_name.replace("item", "Item ");

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-2.5">
      <div className="flex items-center gap-2">
        <span className="w-12 shrink-0 text-[10px] font-semibold uppercase tracking-wider text-zinc-600">{slotLabel}</span>
        {slot.primary ? (
          <ItemCard item={slot.primary} itemLookup={itemLookup} />
        ) : (
          <span className="text-xs text-zinc-600">No data</span>
        )}
      </div>

      {slot.alternatives.length > 0 ? (
        <div className="mt-1 pl-14">
          <button
            type="button"
            className="text-[10px] text-cyan-500 hover:text-cyan-400"
            onClick={() => setShowAlts(!showAlts)}
          >
            {showAlts ? "Hide alternatives" : `+${slot.alternatives.length} alt${slot.alternatives.length > 1 ? "s" : ""}`}
          </button>
          {showAlts ? (
            <div className="mt-1.5 space-y-1.5">
              {slot.alternatives.map((alt) => (
                <ItemCard key={alt.item_id} item={alt} itemLookup={itemLookup} />
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

type BuildPanelProps = {
  data: BuildRecommendResponse | null;
  itemLookup: Record<string, ItemDefinition>;
  loading: boolean;
};

export function BuildPanel({ data, itemLookup, loading }: BuildPanelProps) {
  if (loading) {
    return <p className="py-6 text-center text-xs text-zinc-600">Loading build recommendations...</p>;
  }

  if (!data || data.slots.length === 0) {
    return <p className="py-6 text-center text-xs text-zinc-600">No build recommendations available. Game must be in progress.</p>;
  }

  return (
    <div className="flex flex-col gap-2">
      {data.fallback_used ? (
        <div className="rounded border border-amber-500/20 bg-amber-500/5 px-3 py-2">
          <p className="text-[11px] text-amber-400">Limited matchup data - showing general build</p>
        </div>
      ) : null}

      {data.keystone_filtered ? (
        <div className="rounded border border-cyan-500/20 bg-cyan-500/5 px-3 py-2">
          <p className="text-[11px] text-cyan-400">Filtered for your keystone</p>
        </div>
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
