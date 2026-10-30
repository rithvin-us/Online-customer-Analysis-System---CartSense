"""HDFS access.

Two mechanisms, each used where it is the right tool:

* the ``hdfs dfs`` command line client for writes (upload, mkdir, chmod,
  delete), because it streams a local file straight into HDFS and applies the
  cluster's configuration without the backend having to restate it;
* WebHDFS over HTTP for reads and metadata, because it returns structured JSON
  — file status, content summaries, block locations — instead of text that
  would have to be scraped.

Nothing here parses human-readable CLI output into numbers.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

WEBHDFS_PREFIX = "/webhdfs/v1"
_DEFAULT_TIMEOUT = 120


class HdfsError(RuntimeError):
    """A HDFS operation failed. Carries the command output for diagnosis."""

    def __init__(self, message: str, *, command: list[str] | None = None, output: str = ""):
        super().__init__(message)
        self.command = command or []
        self.output = output


@dataclass(slots=True)
class FileStatus:
    path: str
    name: str
    is_directory: bool
    length: int
    block_size: int
    replication: int
    modification_time: int
    owner: str
    group: str
    permission: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "name": self.name,
            "is_directory": self.is_directory,
            "length": self.length,
            "block_size": self.block_size,
            "replication": self.replication,
            "modification_time": self.modification_time,
            "owner": self.owner,
            "group": self.group,
            "permission": self.permission,
        }


# ---------------------------------------------------------------------------
# Command line client
# ---------------------------------------------------------------------------

def _run(args: list[str], *, timeout: int = _DEFAULT_TIMEOUT) -> str:
    command = ["hdfs", "dfs", *args]
    log.debug("running %s", " ".join(command))
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise HdfsError(
            f"hdfs dfs {' '.join(args)} failed with exit code {completed.returncode}",
            command=command,
            output=(completed.stderr or completed.stdout or "").strip(),
        )
    return completed.stdout


def mkdirs(path: str) -> None:
    _run(["-mkdir", "-p", path])


def exists(path: str) -> bool:
    completed = subprocess.run(
        ["hdfs", "dfs", "-test", "-e", path],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return completed.returncode == 0


def remove(path: str, *, recursive: bool = True) -> None:
    """Deletes a path. Used only for scratch space and failed uploads."""
    args = ["-rm", "-r", "-f", path] if recursive else ["-rm", "-f", path]
    _run(args)


def chmod(path: str, mode: str, *, recursive: bool = False) -> None:
    args = ["-chmod"] + (["-R"] if recursive else []) + [mode, path]
    _run(args)


def upload(
    local_path: str,
    hdfs_path: str,
    *,
    block_size: int | None = None,
    replication: int | None = None,
    timeout: int = 1800,
) -> None:
    """Copies a local file into HDFS.

    The block size is passed per upload rather than relying on the cluster
    default, so that a dataset can be stored with the block size a particular
    experiment wants — which is how the benchmark feature varies the number of
    input splits over the same data.
    """
    overrides: list[str] = []
    if block_size:
        overrides += ["-D", f"dfs.blocksize={block_size}"]
    if replication:
        overrides += ["-D", f"dfs.replication={replication}"]
    _run([*overrides, "-put", "-f", local_path, hdfs_path], timeout=timeout)


# ---------------------------------------------------------------------------
# WebHDFS
# ---------------------------------------------------------------------------

def _webhdfs_url(path: str) -> str:
    if not path.startswith("/"):
        path = "/" + path
    return f"{settings.namenode_ui}{WEBHDFS_PREFIX}{path}"


def _webhdfs(path: str, op: str, **params: Any) -> dict[str, Any]:
    query = {"op": op, "user.name": settings.hadoop_user_name, **params}
    try:
        response = httpx.get(_webhdfs_url(path), params=query, timeout=30.0, follow_redirects=True)
    except httpx.HTTPError as transport_failure:
        raise HdfsError(f"WebHDFS {op} on {path} failed: {transport_failure}") from transport_failure
    if response.status_code == 404:
        raise FileNotFoundError(path)
    if response.status_code >= 400:
        raise HdfsError(f"WebHDFS {op} on {path} returned {response.status_code}",
                        output=response.text[:2000])
    return response.json()


def status(path: str) -> FileStatus:
    payload = _webhdfs(path, "GETFILESTATUS")["FileStatus"]
    return _to_status(path, payload, fallback_name=path.rsplit("/", 1)[-1])


def list_status(path: str) -> list[FileStatus]:
    """Direct children of a directory, or the file itself."""
    payload = _webhdfs(path, "LISTSTATUS")["FileStatuses"]["FileStatus"]
    base = path.rstrip("/")
    results = []
    for entry in payload:
        name = entry.get("pathSuffix") or base.rsplit("/", 1)[-1]
        results.append(_to_status(f"{base}/{name}" if entry.get("pathSuffix") else base, entry, name))
    return sorted(results, key=lambda item: (not item.is_directory, item.name))


def _to_status(path: str, entry: dict[str, Any], fallback_name: str) -> FileStatus:
    return FileStatus(
        path=path,
        name=entry.get("pathSuffix") or fallback_name,
        is_directory=entry.get("type") == "DIRECTORY",
        length=int(entry.get("length", 0)),
        block_size=int(entry.get("blockSize", 0)),
        replication=int(entry.get("replication", 0)),
        modification_time=int(entry.get("modificationTime", 0)),
        owner=entry.get("owner", ""),
        group=entry.get("group", ""),
        permission=entry.get("permission", ""),
    )


def content_summary(path: str) -> dict[str, Any]:
    """Recursive size, file count and directory count of a subtree."""
    summary = _webhdfs(path, "GETCONTENTSUMMARY")["ContentSummary"]
    return {
        "directory_count": summary.get("directoryCount", 0),
        "file_count": summary.get("fileCount", 0),
        "length": summary.get("length", 0),
        "space_consumed": summary.get("spaceConsumed", 0),
        "quota": summary.get("quota", -1),
    }


def block_locations(path: str) -> list[dict[str, Any]]:
    """Which DataNodes hold which block of a file.

    This is the evidence that HDFS really distributed and replicated the
    dataset: each entry names the hosts holding that block, and there are as
    many hosts as the replication factor.
    """
    try:
        payload = _webhdfs(path, "GETFILEBLOCKLOCATIONS")
    except HdfsError:
        return []
    blocks = payload.get("BlockLocations", {}).get("BlockLocation", [])
    return [
        {
            "offset": block.get("offset", 0),
            "length": block.get("length", 0),
            "hosts": block.get("hosts", []),
            "names": block.get("names", []),
            "cached_hosts": block.get("cachedHosts", []),
            "corrupt": block.get("corrupt", False),
        }
        for block in blocks
    ]


def read_text(path: str, *, max_bytes: int = 1_048_576, offset: int = 0) -> str:
    """Reads at most ``max_bytes`` of a file through WebHDFS."""
    query = {
        "op": "OPEN",
        "user.name": settings.hadoop_user_name,
        "offset": offset,
        "length": max_bytes,
    }
    try:
        response = httpx.get(_webhdfs_url(path), params=query, timeout=120.0, follow_redirects=True)
    except httpx.HTTPError as transport_failure:
        raise HdfsError(f"WebHDFS OPEN on {path} failed: {transport_failure}") from transport_failure
    if response.status_code == 404:
        raise FileNotFoundError(path)
    if response.status_code >= 400:
        raise HdfsError(f"WebHDFS OPEN on {path} returned {response.status_code}",
                        output=response.text[:2000])
    return response.text


def part_files(directory: str) -> list[FileStatus]:
    """The data files of a MapReduce output directory, in reducer order.

    ``_SUCCESS`` and the ``_logs`` directory are skipped: they are job
    bookkeeping, not results.
    """
    try:
        entries = list_status(directory)
    except FileNotFoundError:
        return []
    parts = [
        entry
        for entry in entries
        if not entry.is_directory
        and not entry.name.startswith("_")
        and not entry.name.startswith(".")
    ]
    return sorted(parts, key=lambda item: item.name)


def read_rows(
    directory: str,
    *,
    limit: int,
    skip: int = 0,
    max_bytes_per_part: int = 8_388_608,
) -> tuple[list[str], bool]:
    """Reads up to ``limit`` lines from a MapReduce output directory.

    Returns the lines and whether more remain. Reducer output files are read in
    name order, which for a single-reducer ranking stage means the rows arrive
    in rank order.

    A partial final line (the byte window landing mid-line) is discarded unless
    it is the end of the file, so a caller never sees a truncated record.
    """
    collected: list[str] = []
    skipped = 0
    more = False

    # Empty reducer outputs are skipped up front: a zero-length part must not
    # make the caller believe another page of rows exists.
    parts = [part for part in part_files(directory) if part.length > 0]

    for part in parts:
        if len(collected) >= limit:
            more = True
            break

        offset = 0
        while offset < part.length and len(collected) < limit:
            window = min(max_bytes_per_part, part.length - offset)
            chunk = read_text(part.path, max_bytes=window, offset=offset)
            reached_end = offset + window >= part.length
            lines = chunk.split("\n")
            if not reached_end and lines:
                # The last element is probably half a line; re-read it with the
                # next window rather than returning it.
                trailing = lines.pop()
                window -= len(trailing.encode("utf-8"))
                if window <= 0:
                    # One line is longer than the window; grow it and retry.
                    max_bytes_per_part *= 2
                    continue
            for line in lines:
                if not line:
                    continue
                if skipped < skip:
                    skipped += 1
                    continue
                if len(collected) >= limit:
                    more = True
                    break
                collected.append(line)
            offset += window

        if offset < part.length:
            more = True

    return collected, more


def count_rows(directory: str) -> int:
    """Exact line count of a result directory.

    Counting is done by the cluster, not by streaming the data to the backend:
    ``hdfs dfs -cat`` pipes through ``wc -l`` inside the container that already
    holds the Hadoop client.
    """
    pattern = f"{directory.rstrip('/')}/part-*"
    try:
        cat = subprocess.Popen(
            ["hdfs", "dfs", "-cat", pattern],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        counter = subprocess.run(
            ["wc", "-l"],
            stdin=cat.stdout,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        if cat.stdout:
            cat.stdout.close()
        cat.wait(timeout=600)
    except (OSError, subprocess.SubprocessError) as failure:
        raise HdfsError(f"could not count rows in {directory}: {failure}") from failure
    if counter.returncode != 0:
        return 0
    try:
        return int(counter.stdout.strip().split()[0])
    except (IndexError, ValueError):
        return 0
