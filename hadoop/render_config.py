#!/usr/bin/env python3
"""Render the CartScope Hadoop configuration templates.

Hadoop's own configuration values legitimately contain ``$HADOOP_HOME`` and
``$HADOOP_CONF_DIR``, which Hadoop expands itself at runtime. A general-purpose
substitution would destroy them, so this renderer replaces an explicit
allowlist of CartScope variables and leaves every other ``$`` alone.

Usage: render_config.py <template_dir> <output_dir>
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

#: The only placeholders the templates may use. Anything else is left as-is.
VARIABLES: tuple[str, ...] = (
    "CARTSCOPE_NAMENODE_HOST",
    "CARTSCOPE_RM_HOST",
    "CARTSCOPE_HISTORY_HOST",
    "CARTSCOPE_HDFS_REPLICATION",
    "CARTSCOPE_HDFS_BLOCK_SIZE",
    "CARTSCOPE_NM_MEMORY_MB",
    "CARTSCOPE_NM_VCORES",
    "CARTSCOPE_MAP_MEMORY_MB",
    "CARTSCOPE_REDUCE_MEMORY_MB",
    "CARTSCOPE_AM_MEMORY_MB",
    "CARTSCOPE_MAP_HEAP_MB",
    "CARTSCOPE_REDUCE_HEAP_MB",
    "CARTSCOPE_AM_HEAP_MB",
)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 64

    template_dir = Path(argv[1])
    output_dir = Path(argv[2])
    output_dir.mkdir(parents=True, exist_ok=True)

    missing = [name for name in VARIABLES if name not in os.environ]
    if missing:
        print(
            "these configuration variables are not set: " + ", ".join(missing),
            file=sys.stderr,
        )
        return 1

    rendered_count = 0
    for template in sorted(template_dir.glob("*.xml")):
        text = template.read_text(encoding="utf-8")
        for name in VARIABLES:
            text = text.replace("${" + name + "}", os.environ[name])
        (output_dir / template.name).write_text(text, encoding="utf-8")
        rendered_count += 1

    print(
        f"rendered {rendered_count} configuration files into {output_dir}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
