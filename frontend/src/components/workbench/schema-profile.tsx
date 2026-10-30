import { CheckCircle2, XCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatInteger, formatPercent } from "@/lib/format";
import type { SchemaReport } from "@/lib/types";

/** Column-by-column profile of the upload, plus its first few rows. */
export function SchemaProfile({ report }: { report: SchemaReport }) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {report.schema_matches ? (
          <Badge variant="success">
            <CheckCircle2 className="size-3" aria-hidden />
            Schema matches
          </Badge>
        ) : (
          <Badge variant="danger">
            <XCircle className="size-3" aria-hidden />
            Schema mismatch
          </Badge>
        )}
        <Badge variant="outline">encoding {report.encoding}</Badge>
        <Badge variant="outline">
          delimiter {report.delimiter === "\t" ? "tab" : `"${report.delimiter}"`}
        </Badge>
        {report.missing_columns.length > 0 && (
          <span className="text-2xs text-destructive">
            missing: {report.missing_columns.join(", ")}
          </span>
        )}
        {report.unexpected_columns.length > 0 && (
          <span className="text-2xs text-warning">
            unexpected: {report.unexpected_columns.join(", ")}
          </span>
        )}
      </div>

      <div className="overflow-x-auto scrollbar-slim rounded-md border border-border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Column</TableHead>
              <TableHead>Declared type</TableHead>
              <TableHead className="text-right">Non-empty</TableHead>
              <TableHead className="text-right">Empty</TableHead>
              <TableHead className="text-right">Unparseable</TableHead>
              <TableHead className="text-right">Minimum</TableHead>
              <TableHead className="text-right">Maximum</TableHead>
              <TableHead>Sample values</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {report.columns.map((column) => (
              <TableRow key={column.name}>
                <TableCell className="font-medium">{column.name}</TableCell>
                <TableCell className="text-muted-foreground">
                  {column.declared_type}
                </TableCell>
                <TableCell className="text-right tabular">
                  {formatInteger(column.non_empty)}
                </TableCell>
                <TableCell className="text-right tabular">
                  {formatInteger(column.empty)}
                  {column.empty > 0 && (
                    <span className="pl-1 text-2xs text-muted-foreground">
                      {formatPercent(column.empty_percent, 2)}
                    </span>
                  )}
                </TableCell>
                <TableCell
                  className={`text-right tabular ${
                    column.type_mismatches > 0 ? "text-warning" : ""
                  }`}
                >
                  {formatInteger(column.type_mismatches)}
                </TableCell>
                <TableCell className="text-right tabular">
                  {column.min === null ? "—" : String(column.min)}
                </TableCell>
                <TableCell className="text-right tabular">
                  {column.max === null ? "—" : String(column.max)}
                </TableCell>
                <TableCell className="max-w-[18rem] truncate text-muted-foreground">
                  {column.distinct_sample.slice(0, 4).join(" · ") || "—"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {report.sample_rows.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
            First {report.sample_rows.length} rows as parsed
          </summary>
          <div className="mt-2 overflow-x-auto scrollbar-slim rounded-md border border-border">
            <table className="w-full text-2xs">
              <thead className="bg-surface-sunken">
                <tr className="text-left text-muted-foreground">
                  {report.header.map((heading, index) => (
                    <th key={`${heading}-${index}`} className="px-2 py-1.5 font-medium">
                      {heading}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {report.sample_rows.map((row, rowIndex) => (
                  <tr key={rowIndex} className="border-t border-border/60">
                    {row.map((value, cellIndex) => (
                      <td
                        key={cellIndex}
                        className="max-w-[14rem] truncate px-2 py-1 font-mono"
                        title={value}
                      >
                        {value || "—"}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  );
}
