/**
 * Collapses a two-column metric/value result into a lookup.
 *
 * The loyalty summary is emitted one metric per row, because that is the shape
 * a reducer naturally writes. The UI wants it keyed.
 */
export function summariseMetrics(
  rows: Record<string, string | number | null>[],
): Record<string, number | null> {
  const summary: Record<string, number | null> = {};
  for (const row of rows) {
    const metric = row.metric;
    if (metric === null || metric === undefined) continue;
    const value = row.value;
    summary[String(metric)] = typeof value === "number" ? value : null;
  }
  return summary;
}
