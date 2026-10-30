"use client";

import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Download } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatByUnit, formatInteger } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { ResultColumn, ResultPage } from "@/lib/types";

/**
 * Renders a page of reducer output.
 *
 * The columns, their types and their units come from the analysis registry, so
 * this one component renders every result the platform produces without
 * knowing anything about any particular analysis.
 *
 * Sorting here reorders the rows on screen only, and says so: the authoritative
 * ordering is the one the ranking stage computed in Hadoop, which is why a
 * ranked result opens in its own order with the rank visible.
 */
export function ResultTable({
  page,
  offset,
  pageSize,
  onOffsetChange,
  exportUrls,
  busy,
}: {
  page: ResultPage;
  offset: number;
  pageSize: number;
  onOffsetChange?: (offset: number) => void;
  exportUrls?: { csv: string; json: string; tsv: string };
  busy?: boolean;
}) {
  const [sort, setSort] = useState<{ column: string; direction: "asc" | "desc" } | null>(null);

  const rows = useMemo(() => {
    if (!sort) return page.rows;
    const column = page.columns.find((candidate) => candidate.name === sort.column);
    if (!column) return page.rows;
    const factor = sort.direction === "asc" ? 1 : -1;
    return [...page.rows].sort((left, right) => {
      const a = left[sort.column];
      const b = right[sort.column];
      if (a === null || a === undefined) return 1;
      if (b === null || b === undefined) return -1;
      if (typeof a === "number" && typeof b === "number") return (a - b) * factor;
      return String(a).localeCompare(String(b)) * factor;
    });
  }, [page.rows, page.columns, sort]);

  function toggleSort(column: ResultColumn) {
    setSort((current) => {
      if (current?.column !== column.name) {
        return { column: column.name, direction: column.type === "string" ? "asc" : "desc" };
      }
      if (current.direction === "desc") return { column: column.name, direction: "asc" };
      return null;
    });
  }

  const from = page.returned === 0 ? 0 : offset + 1;
  const to = offset + page.returned;

  return (
    <div className="flex min-h-0 flex-col">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-2.5">
        <div className="min-w-0">
          <p className="truncate text-xs font-medium">{page.title}</p>
          <p className="truncate text-2xs text-muted-foreground">{page.description}</p>
        </div>
        <div className="flex items-center gap-2">
          {exportUrls && (
            <div className="flex items-center gap-1">
              {(["csv", "tsv", "json"] as const).map((format) => (
                <Button key={format} variant="ghost" size="xs" asChild>
                  <a href={exportUrls[format]} download>
                    <Download aria-hidden />
                    {format.toUpperCase()}
                  </a>
                </Button>
              ))}
            </div>
          )}
          {onOffsetChange && (
            <div className="flex items-center gap-1">
              <Button
                variant="secondary"
                size="xs"
                disabled={offset === 0 || busy}
                onClick={() => onOffsetChange(Math.max(0, offset - pageSize))}
                aria-label="Previous page"
              >
                <ChevronLeft aria-hidden />
              </Button>
              <Button
                variant="secondary"
                size="xs"
                disabled={!page.has_more || busy}
                onClick={() => onOffsetChange(offset + pageSize)}
                aria-label="Next page"
              >
                <ChevronRight aria-hidden />
              </Button>
            </div>
          )}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto scrollbar-slim">
        <Table>
          <TableHeader>
            <TableRow>
              {page.columns.map((column) => {
                const active = sort?.column === column.name;
                const numeric = column.type !== "string";
                return (
                  <TableHead
                    key={column.name}
                    className={cn("whitespace-nowrap", numeric && "text-right")}
                    title={column.description || undefined}
                    aria-sort={
                      active ? (sort!.direction === "asc" ? "ascending" : "descending") : "none"
                    }
                  >
                    <button
                      type="button"
                      onClick={() => toggleSort(column)}
                      className={cn(
                        "inline-flex items-center gap-1 hover:text-foreground",
                        numeric && "flex-row-reverse",
                        active && "text-foreground",
                      )}
                    >
                      {column.label}
                      {active &&
                        (sort!.direction === "asc" ? (
                          <ArrowUp className="size-3" aria-hidden />
                        ) : (
                          <ArrowDown className="size-3" aria-hidden />
                        ))}
                    </button>
                  </TableHead>
                );
              })}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row, index) => (
              <TableRow key={`${offset}-${index}`}>
                {page.columns.map((column) => {
                  const value = row[column.name];
                  const numeric = column.type !== "string";
                  return (
                    <TableCell
                      key={column.name}
                      className={cn(
                        "whitespace-nowrap",
                        numeric ? "text-right tabular" : "max-w-[22rem] truncate",
                        column.name === "rank" && "text-muted-foreground",
                      )}
                      title={numeric ? undefined : String(value ?? "")}
                    >
                      {formatByUnit(value, column.unit, column.type)}
                    </TableCell>
                  );
                })}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-4 py-2 text-2xs text-muted-foreground">
        <span className="tabular">
          Rows {formatInteger(from)}–{formatInteger(to)}
          {page.row_count !== null && ` of ${formatInteger(page.row_count)}`}
        </span>
        <span className="truncate font-mono" title={page.hdfs_path}>
          {page.hdfs_path}
        </span>
      </div>
    </div>
  );
}
