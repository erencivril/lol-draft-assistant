import { rankOptions, regionOptions, roleOptions } from "../constants/filters";

export type AnalysisFilters = {
  region: string;
  rank_tier: string;
  role: string;
};

type AnalysisFiltersPanelProps = {
  filters: AnalysisFilters;
  disabled?: boolean;
  onChange: (filters: AnalysisFilters) => void;
};

const selectClass =
  "rounded-xl border border-zinc-700 bg-zinc-900/80 px-3 py-2 text-sm text-zinc-100 outline-none transition-colors focus:border-cyan-500 disabled:cursor-not-allowed disabled:opacity-60";

export function AnalysisFiltersPanel({ filters, disabled = false, onChange }: AnalysisFiltersPanelProps) {
  return (
    <section className="rounded-[var(--radius-panel)] border border-zinc-800 bg-zinc-900/55 p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-cyan-400">Filters</p>
          <h2 className="text-lg font-semibold text-zinc-100">Analysis scope</h2>
        </div>
        <span className="rounded-full border border-zinc-800 bg-zinc-950/80 px-3 py-1 text-[11px] uppercase tracking-[0.18em] text-zinc-400">
          Manual control
        </span>
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        <label className="grid gap-1.5 text-xs font-medium text-zinc-400">
          Region
          <select
            aria-label="Analysis region"
            className={selectClass}
            disabled={disabled}
            value={filters.region}
            onChange={(event) => onChange({ ...filters, region: event.target.value })}
          >
            {regionOptions.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>

        <label className="grid gap-1.5 text-xs font-medium text-zinc-400">
          Rank
          <select
            aria-label="Analysis rank"
            className={selectClass}
            disabled={disabled}
            value={filters.rank_tier}
            onChange={(event) => onChange({ ...filters, rank_tier: event.target.value })}
          >
            {rankOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label className="grid gap-1.5 text-xs font-medium text-zinc-400">
          Role
          <select
            aria-label="Analysis role"
            className={selectClass}
            disabled={disabled}
            value={filters.role}
            onChange={(event) => onChange({ ...filters, role: event.target.value })}
          >
            {roleOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>
    </section>
  );
}
