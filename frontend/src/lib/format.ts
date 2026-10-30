/**
 * Formatting helpers.
 *
 * A console shows a lot of numbers, and the rules for them matter: counters are
 * exact and grouped, byte sizes are binary, durations read as a human would say
 * them, and a value the cluster did not report is shown as an em dash rather
 * than as zero.
 */

const INTEGER = new Intl.NumberFormat("en-GB");
const DECIMAL = new Intl.NumberFormat("en-GB", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const COMPACT = new Intl.NumberFormat("en-GB", {
  notation: "compact",
  maximumFractionDigits: 1,
});

/** An absent value. Never render a missing counter as 0. */
export const ABSENT = "—";

export function formatInteger(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return ABSENT;
  return INTEGER.format(value);
}

export function formatCompact(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return ABSENT;
  if (Math.abs(value) < 10_000) return INTEGER.format(value);
  return COMPACT.format(value);
}

export function formatDecimal(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return ABSENT;
  return DECIMAL.format(value);
}

/**
 * Money. The source dataset is a UK retailer's, so sterling is the correct
 * unit; it is stated rather than assumed by showing the symbol.
 */
export function formatCurrency(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return ABSENT;
  return `£${DECIMAL.format(value)}`;
}

export function formatPercent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return ABSENT;
  return `${value.toFixed(digits)}%`;
}

const BYTE_UNITS = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"] as const;

/** Binary byte sizes, because that is what HDFS reports. */
export function formatBytes(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return ABSENT;
  if (value === 0) return "0 B";
  const exponent = Math.min(
    BYTE_UNITS.length - 1,
    Math.floor(Math.log(Math.abs(value)) / Math.log(1024)),
  );
  const scaled = value / 1024 ** exponent;
  const unit = BYTE_UNITS[exponent] ?? "B";
  return `${scaled.toFixed(exponent === 0 ? 0 : scaled >= 100 ? 0 : 1)} ${unit}`;
}

export function formatDuration(milliseconds: number | null | undefined): string {
  if (milliseconds === null || milliseconds === undefined || Number.isNaN(milliseconds)) {
    return ABSENT;
  }
  if (milliseconds < 1000) return `${Math.round(milliseconds)} ms`;
  const totalSeconds = milliseconds / 1000;
  if (totalSeconds < 60) return `${totalSeconds.toFixed(1)} s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = Math.round(totalSeconds % 60);
  if (minutes < 60) return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${String(minutes % 60).padStart(2, "0")}m`;
}

export function formatTimestamp(value: string | null | undefined): string {
  if (!value) return ABSENT;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("en-GB", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function formatRelative(value: string | null | undefined): string {
  if (!value) return ABSENT;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (seconds < 10) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

/** Formats a value according to the unit the analysis registry declared. */
export function formatByUnit(
  value: unknown,
  unit: string | undefined,
  type: string | undefined,
): string {
  if (value === null || value === undefined || value === "") return ABSENT;
  if (typeof value !== "number") return String(value);
  switch (unit) {
    case "currency":
      return formatCurrency(value);
    case "percent":
      return formatPercent(value);
    case "quantity":
    case "count":
      return formatInteger(value);
    default:
      return type === "float" ? formatDecimal(value) : formatInteger(value);
  }
}

/** Shortens a long HDFS path for a narrow column, keeping both ends readable. */
export function shortenPath(path: string | null | undefined, keep = 34): string {
  if (!path) return ABSENT;
  if (path.length <= keep * 2) return path;
  return `${path.slice(0, keep)}…${path.slice(-keep)}`;
}
