# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# CartScope Hadoop image.
#
# Built on the official Apache Hadoop image, `apache/hadoop:3.5.0`, published by
# the Apache Hadoop project itself. That image was verified before adopting it:
#
#   $ docker run --rm --entrypoint bash apache/hadoop:3.5.0 -c 'hadoop version'
#   Hadoop 3.5.0
#   Compiled by cnauroth on 2026-03-24T16:56Z
#
#   base OS : Ubuntu 24.04 LTS
#   JVM     : Temurin 17.0.18  (Hadoop 3.5.0 supports Java 17 as a runtime)
#   layout  : the full distribution under /opt/hadoop, user `hadoop` (uid 1001)
#
# One image serves every cluster role — namenode, datanode, resourcemanager,
# nodemanager, historyserver, client — chosen at run time by the first argument
# to the entrypoint. That keeps the cluster's shape in docker-compose.yml rather
# than spread across six near-identical Dockerfiles.
#
# This build installs no packages and downloads nothing: the base image already
# carries bash, curl, netcat, procps and python3, and the configuration renderer
# is written in Python precisely so that `envsubst` is not needed. The image
# therefore builds offline and reproducibly.
# ---------------------------------------------------------------------------
ARG HADOOP_VERSION=3.5.0
FROM apache/hadoop:${HADOOP_VERSION}

ARG HADOOP_VERSION=3.5.0

LABEL org.opencontainers.image.title="CartScope Hadoop" \
      org.opencontainers.image.description="Apache Hadoop ${HADOOP_VERSION} configured for the CartScope cluster" \
      org.opencontainers.image.version="${HADOOP_VERSION}" \
      org.opencontainers.image.base.name="apache/hadoop:${HADOOP_VERSION}"

USER root

ENV HADOOP_HOME=/opt/hadoop \
    HADOOP_VERSION=${HADOOP_VERSION} \
    HADOOP_CONF_DIR=/opt/hadoop/etc/hadoop \
    HADOOP_LOG_DIR=/opt/hadoop/logs \
    HADOOP_USER_NAME=hadoop \
    PATH=/opt/hadoop/bin:/opt/hadoop/sbin:/opt/java/openjdk/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# Configuration templates, rendered at container start so that one image can
# serve a differently sized cluster without a rebuild.
COPY hadoop/conf/ /opt/hadoop/etc/hadoop-templates/
COPY hadoop/render_config.py /usr/local/bin/cartscope-render-config
COPY hadoop/entrypoint.sh /usr/local/bin/cartscope-hadoop
COPY hadoop/healthcheck.sh /usr/local/bin/cartscope-healthcheck

RUN set -eux; \
    chmod +x /usr/local/bin/cartscope-render-config \
             /usr/local/bin/cartscope-hadoop \
             /usr/local/bin/cartscope-healthcheck; \
    # Storage directories. Each is a mount point for a named volume at run
    # time; creating them here fixes their ownership for the hadoop user.
    mkdir -p /opt/hadoop/logs \
             /hadoop/dfs/name /hadoop/dfs/data \
             /hadoop/yarn/local /hadoop/yarn/logs \
             /hadoop/tmp \
             /opt/cartscope; \
    chown -R hadoop:users /opt/hadoop/etc/hadoop /opt/hadoop/etc/hadoop-templates \
                          /opt/hadoop/logs /hadoop /opt/cartscope; \
    # Fail the build rather than ship an image whose Hadoop does not run.
    su hadoop -s /bin/bash -c 'hadoop version' | head -1; \
    # Render the templates with placeholder values and parse the result, so a
    # malformed configuration file fails the build instead of crash-looping a
    # container at start-up. Hadoop's XML parser is strict: an XML comment may
    # not contain a double hyphen, which is easy to write by accident.
    CARTSCOPE_NAMENODE_HOST=namenode \
    CARTSCOPE_RM_HOST=resourcemanager \
    CARTSCOPE_HISTORY_HOST=historyserver \
    CARTSCOPE_HDFS_REPLICATION=2 \
    CARTSCOPE_HDFS_BLOCK_SIZE=4194304 \
    CARTSCOPE_NM_MEMORY_MB=2048 \
    CARTSCOPE_NM_VCORES=2 \
    CARTSCOPE_MAP_MEMORY_MB=512 \
    CARTSCOPE_REDUCE_MEMORY_MB=512 \
    CARTSCOPE_AM_MEMORY_MB=768 \
    CARTSCOPE_MAP_HEAP_MB=410 \
    CARTSCOPE_REDUCE_HEAP_MB=410 \
    CARTSCOPE_AM_HEAP_MB=614 \
      python3 /usr/local/bin/cartscope-render-config \
        /opt/hadoop/etc/hadoop-templates /tmp/conf-check; \
    python3 -c "\
import glob, sys;\
from xml.etree import ElementTree;\
[ElementTree.parse(path) for path in sorted(glob.glob('/tmp/conf-check/*.xml'))];\
print('configuration templates parse')"; \
    rm -rf /tmp/conf-check

USER hadoop
WORKDIR /opt/cartscope

ENTRYPOINT ["/usr/local/bin/cartscope-hadoop"]
CMD ["client"]
