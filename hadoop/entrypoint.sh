#!/usr/bin/env bash
#
# CartScope Hadoop container entrypoint.
#
# Usage: cartscope-hadoop <role> [args...]
#   roles: namenode | datanode | resourcemanager | nodemanager
#          historyserver | client
#
# The entrypoint renders the configuration templates in
# /opt/hadoop/etc/hadoop-templates into the live configuration directory and
# then execs the requested daemon in the foreground.
set -euo pipefail

ROLE="${1:-client}"
shift || true

: "${HADOOP_HOME:=/opt/hadoop}"
: "${HADOOP_CONF_DIR:=/opt/hadoop/etc/hadoop}"

# --- Configuration defaults -------------------------------------------------
# Every value may be overridden from docker-compose.yml / .env so that the
# cluster can be resized without rebuilding the image.
: "${CARTSCOPE_NAMENODE_HOST:=namenode}"
: "${CARTSCOPE_RM_HOST:=resourcemanager}"
: "${CARTSCOPE_HISTORY_HOST:=historyserver}"
: "${CARTSCOPE_HDFS_REPLICATION:=2}"
: "${CARTSCOPE_HDFS_BLOCK_SIZE:=4194304}"
: "${CARTSCOPE_NM_MEMORY_MB:=2048}"
: "${CARTSCOPE_NM_VCORES:=2}"
: "${CARTSCOPE_MAP_MEMORY_MB:=512}"
: "${CARTSCOPE_REDUCE_MEMORY_MB:=512}"
: "${CARTSCOPE_AM_MEMORY_MB:=768}"
: "${CARTSCOPE_MAP_HEAP_MB:=410}"
: "${CARTSCOPE_REDUCE_HEAP_MB:=410}"
: "${CARTSCOPE_AM_HEAP_MB:=614}"

export CARTSCOPE_NAMENODE_HOST CARTSCOPE_RM_HOST CARTSCOPE_HISTORY_HOST \
       CARTSCOPE_HDFS_REPLICATION CARTSCOPE_HDFS_BLOCK_SIZE \
       CARTSCOPE_NM_MEMORY_MB CARTSCOPE_NM_VCORES \
       CARTSCOPE_MAP_MEMORY_MB CARTSCOPE_REDUCE_MEMORY_MB \
       CARTSCOPE_AM_MEMORY_MB CARTSCOPE_MAP_HEAP_MB \
       CARTSCOPE_REDUCE_HEAP_MB CARTSCOPE_AM_HEAP_MB

log() { printf '[cartscope-hadoop][%s] %s\n' "$ROLE" "$*" >&2; }

render_config() {
  # The renderer substitutes an explicit allowlist of CartScope variables and
  # leaves every other $ alone, because Hadoop configuration values
  # legitimately contain $HADOOP_HOME and $HADOOP_CONF_DIR and Hadoop expands
  # those itself at runtime.
  python3 /usr/local/bin/cartscope-render-config \
    "$HADOOP_HOME/etc/hadoop-templates" "$HADOOP_CONF_DIR"
  log "configuration rendered (replication=${CARTSCOPE_HDFS_REPLICATION}, block=${CARTSCOPE_HDFS_BLOCK_SIZE} bytes)"
}

wait_for_port() {
  local host="$1" port="$2" label="$3" tries=0
  until nc -z "$host" "$port" 2>/dev/null; do
    tries=$((tries + 1))
    if [ "$tries" -gt 150 ]; then
      log "timed out waiting for $label at $host:$port"
      return 1
    fi
    sleep 2
  done
  log "$label is reachable at $host:$port"
}

# The CartScope HDFS layout. Created once, by the NameNode container, after
# HDFS leaves safe mode. Analytical output lives under /cartscope/results and
# is never overwritten: each run writes into its own run_id directory.
bootstrap_hdfs_layout() {
  wait_for_port "$CARTSCOPE_NAMENODE_HOST" 8020 'NameNode RPC' || return 1
  log 'waiting for HDFS to leave safe mode'
  hdfs dfsadmin -safemode wait >/dev/null 2>&1 || true

  hdfs dfs -mkdir -p \
    /cartscope/datasets \
    /cartscope/jobs \
    /cartscope/results \
    /cartscope/manifests \
    /cartscope/benchmarks \
    /cartscope/staging \
    /cartscope/yarn-logs \
    /cartscope/mr-history/tmp \
    /cartscope/mr-history/done \
    /tmp/hadoop-yarn 2>/dev/null || true

  # Directory permissions: the analytical tree is owned by the hadoop user,
  # the YARN/MapReduce service directories are group writable because the
  # NodeManagers and the JobHistoryServer write there.
  hdfs dfs -chmod -R 755 /cartscope 2>/dev/null || true
  hdfs dfs -chmod 1777 /cartscope/yarn-logs /cartscope/mr-history/tmp /tmp/hadoop-yarn 2>/dev/null || true
  hdfs dfs -chmod 775 /cartscope/mr-history/done 2>/dev/null || true
  log 'HDFS layout ready'
}

render_config

case "$ROLE" in
  namenode)
    if [ ! -f /hadoop/dfs/name/current/VERSION ]; then
      log 'no filesystem image found; formatting NameNode'
      hdfs namenode -format -nonInteractive -force -clusterId cartscope
    else
      log 'existing NameNode metadata found; skipping format'
    fi
    # Create the directory layout once the NameNode is accepting RPCs.
    ( bootstrap_hdfs_layout || log 'layout bootstrap failed; see NameNode logs' ) &
    exec hdfs --config "$HADOOP_CONF_DIR" namenode "$@"
    ;;

  datanode)
    wait_for_port "$CARTSCOPE_NAMENODE_HOST" 8020 'NameNode RPC'
    exec hdfs --config "$HADOOP_CONF_DIR" datanode "$@"
    ;;

  resourcemanager)
    wait_for_port "$CARTSCOPE_NAMENODE_HOST" 8020 'NameNode RPC'
    exec yarn --config "$HADOOP_CONF_DIR" resourcemanager "$@"
    ;;

  nodemanager)
    wait_for_port "$CARTSCOPE_RM_HOST" 8032 'ResourceManager RPC'
    exec yarn --config "$HADOOP_CONF_DIR" nodemanager "$@"
    ;;

  historyserver)
    wait_for_port "$CARTSCOPE_NAMENODE_HOST" 8020 'NameNode RPC'
    exec mapred --config "$HADOOP_CONF_DIR" historyserver "$@"
    ;;

  client)
    # A long-lived container holding a configured Hadoop client, used for
    # manual inspection during a demonstration:
    #   docker compose exec client hdfs dfs -ls /cartscope
    if [ "$#" -gt 0 ]; then
      exec "$@"
    fi
    log 'client container ready; exec into it to run hdfs/yarn/mapred commands'
    exec tail -f /dev/null
    ;;

  render-config-only)
    # Used by the backend image, which shares this entrypoint to obtain a
    # configured Hadoop client without starting a daemon.
    exec "$@"
    ;;

  *)
    log "unknown role '$ROLE'"
    exit 64
    ;;
esac
