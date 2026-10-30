import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Field, FieldGrid } from "./field";
import { formatBytes, formatInteger } from "@/lib/format";
import type { VersionStorage } from "@/lib/types";

/**
 * How a dataset version is physically stored.
 *
 * The block table is the point of this panel: it shows each block of the raw
 * upload and the DataNodes holding it, so the replication factor is visible as
 * a fact about the data rather than as a configuration value.
 */
export function StoragePanel({ storage }: { storage: VersionStorage }) {
  const blocks = storage.raw_block_locations ?? [];
  const hosts = new Set(blocks.flatMap((block) => block.hosts));

  return (
    <div className="space-y-5">
      <FieldGrid>
        <Field label="Configured replication">{storage.replication}</Field>
        <Field label="Configured block size">{formatBytes(storage.block_size)}</Field>
        <Field label="Blocks in the raw file">{formatInteger(blocks.length)}</Field>
        <Field label="DataNodes holding them">{formatInteger(hosts.size)}</Field>
      </FieldGrid>

      {Object.entries(storage.subtrees).map(([label, subtree]) => (
        <section key={label} className="space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs font-medium capitalize">{label}</p>
            <code className="truncate font-mono text-2xs text-muted-foreground">
              {subtree.path ?? "not written yet"}
            </code>
          </div>
          {!subtree.exists ? (
            <p className="text-2xs text-muted-foreground">
              {subtree.error ?? "This subtree has not been written yet."}
            </p>
          ) : (
            <>
              {subtree.summary && (
                <p className="text-2xs tabular text-muted-foreground">
                  {formatInteger(subtree.summary.file_count)} files ·{" "}
                  {formatBytes(subtree.summary.length)} logical ·{" "}
                  {formatBytes(subtree.summary.space_consumed)} consumed after replication
                </p>
              )}
              {subtree.files && subtree.files.length > 0 && (
                <div className="overflow-x-auto scrollbar-slim rounded-md border border-border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>File</TableHead>
                        <TableHead className="text-right">Size</TableHead>
                        <TableHead className="text-right">Block size</TableHead>
                        <TableHead className="text-right">Replication</TableHead>
                        <TableHead>Permissions</TableHead>
                        <TableHead>Owner</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {subtree.files.map((file) => (
                        <TableRow key={file.path}>
                          <TableCell className="max-w-[20rem] truncate font-mono text-2xs">
                            {file.name}
                          </TableCell>
                          <TableCell className="text-right tabular">
                            {formatBytes(file.length)}
                          </TableCell>
                          <TableCell className="text-right tabular">
                            {file.is_directory ? "—" : formatBytes(file.block_size)}
                          </TableCell>
                          <TableCell className="text-right tabular">
                            {file.is_directory ? "—" : file.replication}
                          </TableCell>
                          <TableCell className="font-mono text-2xs">
                            {file.permission}
                          </TableCell>
                          <TableCell className="text-muted-foreground">
                            {file.owner}:{file.group}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </>
          )}
        </section>
      ))}

      {blocks.length > 0 && (
        <section className="space-y-2">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="text-xs font-medium">Block placement of the raw upload</p>
            <p className="text-2xs text-muted-foreground">
              Each block is held by {storage.replication} DataNodes. These blocks are also
              what Hadoop turns into map input splits.
            </p>
          </div>
          <div className="max-h-72 overflow-auto scrollbar-slim rounded-md border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="text-right">Block</TableHead>
                  <TableHead className="text-right">Offset</TableHead>
                  <TableHead className="text-right">Length</TableHead>
                  <TableHead>DataNodes</TableHead>
                  <TableHead>Healthy</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {blocks.map((block, index) => (
                  <TableRow key={`${block.offset}-${index}`}>
                    <TableCell className="text-right tabular text-muted-foreground">
                      {index + 1}
                    </TableCell>
                    <TableCell className="text-right tabular">
                      {formatBytes(block.offset)}
                    </TableCell>
                    <TableCell className="text-right tabular">
                      {formatBytes(block.length)}
                    </TableCell>
                    <TableCell className="font-mono text-2xs">
                      {block.hosts.join(", ")}
                    </TableCell>
                    <TableCell>
                      {block.corrupt ? (
                        <Badge variant="danger">corrupt</Badge>
                      ) : (
                        <Badge variant="success">ok</Badge>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </section>
      )}

      {storage.raw_block_locations_error && (
        <p className="text-2xs text-destructive">{storage.raw_block_locations_error}</p>
      )}
    </div>
  );
}
