#!/usr/bin/env bash
#
# Role-aware Docker health check. Each role is probed through the interface
# that the rest of the cluster actually depends on, not just a TCP listener.
set -uo pipefail

ROLE="${1:-}"

case "$ROLE" in
  namenode)
    # Report OK only when the NameNode answers the HTTP JMX endpoint and has
    # left safe mode, because DataNode registration happens after that.
    curl -fsS --max-time 5 'http://localhost:9870/jmx?qry=Hadoop:service=NameNode,name=NameNodeStatus' \
      | grep -q '"State"' || exit 1
    hdfs dfsadmin -safemode get 2>/dev/null | grep -q 'Safe mode is OFF' || exit 1
    ;;
  datanode)
    curl -fsS --max-time 5 'http://localhost:9864/jmx?qry=Hadoop:service=DataNode,name=DataNodeInfo' >/dev/null || exit 1
    ;;
  resourcemanager)
    curl -fsS --max-time 5 'http://localhost:8088/ws/v1/cluster/info' | grep -q '"STARTED"' || exit 1
    ;;
  nodemanager)
    curl -fsS --max-time 5 'http://localhost:8042/ws/v1/node/info' | grep -q '"nodeHealthy":true' || exit 1
    ;;
  historyserver)
    curl -fsS --max-time 5 'http://localhost:19888/ws/v1/history/info' >/dev/null || exit 1
    ;;
  *)
    exit 1
    ;;
esac
exit 0
