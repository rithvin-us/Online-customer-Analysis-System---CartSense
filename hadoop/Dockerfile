# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# CartScope Hadoop base image.
#
# A single image serves every cluster role (namenode, datanode,
# resourcemanager, nodemanager, historyserver, client). The role is chosen at
# runtime by the first argument to the entrypoint, which keeps the cluster
# definition in docker-compose.yml instead of spread across six Dockerfiles.
#
# Hadoop 3.5.0 officially supports Java 17 as a runtime, so the image is built
# on the Temurin 17 JDK (the JDK rather than the JRE, because the MapReduce
# tooling and jps-based health checks expect a full JDK).
# ---------------------------------------------------------------------------
FROM eclipse-temurin:17-jdk-noble AS hadoop-dist

ARG HADOOP_VERSION=3.5.0
ARG HADOOP_SHA512=04ab94496cc00c8b7a28d03f6308eff8d2a4e7f37a9da5e8e086e4d6fc990e7a94d661908f6a6136039536efb362614b8aecdef185b5fb8ed588f0b152c7aa16
ARG HADOOP_URL=https://dlcdn.apache.org/hadoop/common/hadoop-${HADOOP_VERSION}/hadoop-${HADOOP_VERSION}.tar.gz
ARG HADOOP_ARCHIVE_URL=https://archive.apache.org/dist/hadoop/common/hadoop-${HADOOP_VERSION}/hadoop-${HADOOP_VERSION}.tar.gz

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl; \
    rm -rf /var/lib/apt/lists/*; \
    # The primary CDN only keeps current releases; fall back to the archive.
    curl -fsSL -o /tmp/hadoop.tar.gz "${HADOOP_URL}" \
      || curl -fsSL -o /tmp/hadoop.tar.gz "${HADOOP_ARCHIVE_URL}"; \
    echo "${HADOOP_SHA512}  /tmp/hadoop.tar.gz" | sha512sum -c -; \
    mkdir -p /opt/hadoop; \
    tar -xzf /tmp/hadoop.tar.gz -C /opt/hadoop --strip-components=1; \
    rm -f /tmp/hadoop.tar.gz; \
    # Trim the distribution: documentation, sources and the bundled
    # cloud-connector jars are not used by this project.
    rm -rf /opt/hadoop/share/doc \
           /opt/hadoop/share/hadoop/*/sources \
           /opt/hadoop/share/hadoop/tools/lib/aws-java-sdk-bundle-*.jar \
           /opt/hadoop/share/hadoop/tools/lib/azure-storage-*.jar

# ---------------------------------------------------------------------------
FROM eclipse-temurin:17-jdk-noble

ARG HADOOP_VERSION=3.5.0

LABEL org.opencontainers.image.title="CartScope Hadoop" \
      org.opencontainers.image.description="Apache Hadoop ${HADOOP_VERSION} base image for the CartScope cluster" \
      org.opencontainers.image.version="${HADOOP_VERSION}"

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        bash ca-certificates curl gettext-base netcat-openbsd procps tini; \
    rm -rf /var/lib/apt/lists/*; \
    groupadd -r hadoop --gid 1100; \
    useradd -r -g hadoop --uid 1100 --create-home --shell /bin/bash hadoop

COPY --from=hadoop-dist --chown=hadoop:hadoop /opt/hadoop /opt/hadoop

ENV HADOOP_HOME=/opt/hadoop \
    HADOOP_VERSION=${HADOOP_VERSION} \
    HADOOP_CONF_DIR=/opt/hadoop/etc/hadoop \
    HADOOP_LOG_DIR=/opt/hadoop/logs \
    HADOOP_USER_NAME=hadoop \
    JAVA_HOME=/opt/java/openjdk \
    PATH=/opt/hadoop/bin:/opt/hadoop/sbin:/opt/java/openjdk/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# Configuration templates. envsubst renders them at container start so that a
# single image can serve a differently sized cluster without a rebuild.
COPY hadoop/conf/ /opt/hadoop/etc/hadoop-templates/
COPY hadoop/entrypoint.sh /usr/local/bin/cartscope-hadoop
COPY hadoop/healthcheck.sh /usr/local/bin/cartscope-healthcheck

RUN set -eux; \
    chmod +x /usr/local/bin/cartscope-hadoop /usr/local/bin/cartscope-healthcheck; \
    mkdir -p /opt/hadoop/logs /hadoop/dfs/name /hadoop/dfs/data /hadoop/yarn/local /hadoop/yarn/logs /opt/cartscope; \
    chown -R hadoop:hadoop /opt/hadoop /hadoop /opt/cartscope

USER hadoop
WORKDIR /opt/cartscope

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/cartscope-hadoop"]
CMD ["client"]
