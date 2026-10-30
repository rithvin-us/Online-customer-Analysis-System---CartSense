import { AlertTriangle, CircleAlert, Info } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Field, FieldGrid } from "./field";
import { formatBytes, formatInteger, formatPercent } from "@/lib/format";
import type { QualityIssue, QualityReport } from "@/lib/types";

const ICONS = {
  error: CircleAlert,
  warning: AlertTriangle,
  info: Info,
} as const;

const VARIANTS = {
  error: "danger",
  warning: "warning",
  info: "info",
} as const;

/**
 * The data quality report produced while reading the upload.
 *
 * Its scope is deliberately narrow and stated on screen: it describes the file.
 * Transaction classification and every analytical figure come from the Hadoop
 * jobs, which are reported separately.
 */
export function QualityReportPanel({ report }: { report: QualityReport }) {
  const sorted = [...report.issues].sort((left, right) => rank(right) - rank(left));

  return (
    <div className="space-y-4">
      <FieldGrid>
        <Field label="Data rows">{formatInteger(report.data_rows)}</Field>
        <Field label="Distinct rows">{formatInteger(report.distinct_rows)}</Field>
        <Field
          label="Duplicate rows"
          hint="Exact duplicates of an earlier row; the Hadoop validation job collapses them."
        >
          {formatInteger(report.duplicate_rows)}
          {report.data_rows > 0 && (
            <span className="pl-1.5 text-2xs text-muted-foreground">
              {formatPercent((100 * report.duplicate_rows) / report.data_rows, 2)}
            </span>
          )}
        </Field>
        <Field label="Wrong field count">
          {formatInteger(report.wrong_field_count_rows)}
        </Field>
        <Field
          label="Multi-line records"
          hint="Records with a newline inside a quoted field. Hadoop's TextInputFormat splits on newlines, so these are rejected rather than mis-parsed."
        >
          {formatInteger(report.multiline_records)}
        </Field>
        <Field label="File size">{formatBytes(report.size_bytes)}</Field>
        <Field label="SHA-256" className="col-span-2">
          <span className="block truncate font-mono text-2xs" title={report.sha256}>
            {report.sha256}
          </span>
        </Field>
      </FieldGrid>

      <div>
        <p className="pb-2 text-xs font-medium">
          Findings
          {sorted.length > 0 && (
            <span className="pl-1.5 text-2xs font-normal text-muted-foreground">
              {sorted.length}
            </span>
          )}
        </p>
        {sorted.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            Nothing to report: the schema matched and every value parsed.
          </p>
        ) : (
          <ul className="space-y-1.5">
            {sorted.map((issue, index) => {
              const Icon = ICONS[issue.severity];
              return (
                <li
                  key={`${issue.code}-${index}`}
                  className="flex items-start gap-2.5 rounded-md border border-border bg-surface-sunken px-3 py-2"
                >
                  <Icon
                    className={`mt-0.5 size-3.5 shrink-0 ${
                      issue.severity === "error"
                        ? "text-destructive"
                        : issue.severity === "warning"
                          ? "text-warning"
                          : "text-info"
                    }`}
                    aria-hidden
                  />
                  <div className="min-w-0 flex-1">
                    <p className="text-xs">{issue.message}</p>
                  </div>
                  <Badge variant={VARIANTS[issue.severity]} className="shrink-0">
                    {issue.code}
                  </Badge>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <p className="border-t border-border pt-3 text-2xs leading-relaxed text-muted-foreground">
        {report.scope_note}
      </p>
    </div>
  );
}

function rank(issue: QualityIssue): number {
  return issue.severity === "error" ? 3 : issue.severity === "warning" ? 2 : 1;
}
