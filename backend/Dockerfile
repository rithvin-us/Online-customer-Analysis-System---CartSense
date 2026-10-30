# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# CartScope backend image: FastAPI + Celery on top of a configured Hadoop
# client.
#
# The image is built FROM the CartScope Hadoop image rather than from a Python
# base image, and that is a deliberate architectural choice: the Celery worker
# submits jobs with the real `hadoop jar` and `hdfs dfs` commands, so it needs
# the genuine Hadoop client, the cluster's configuration files and a matching
# JVM. Reusing the cluster image guarantees the client is the same version as
# the daemons it talks to.
#
# Build order matters: `cartscope/hadoop:<version>` must exist first.
# `make build` does this in the right order.
# ---------------------------------------------------------------------------
ARG HADOOP_VERSION=3.5.0

# --- Stage 1: compile the MapReduce jar ------------------------------------
FROM maven:3.9-eclipse-temurin-17 AS mapreduce-build
WORKDIR /build
# Resolve dependencies against the POM alone first, so that editing Java
# sources does not re-download the Hadoop client libraries.
COPY mapreduce/pom.xml ./pom.xml
RUN mvn -B -q dependency:go-offline
COPY mapreduce/src ./src
RUN mvn -B package && ls -l target/cartscope-mapreduce.jar

# --- Stage 2: the runtime image --------------------------------------------
FROM cartscope/hadoop:${HADOOP_VERSION}

USER root

# Ubuntu Noble ships Python 3.12. The application lives in a virtual
# environment so that pip never fights the system package manager.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        python3 python3-venv python3-dev build-essential libpq5; \
    python3 -m venv /opt/venv; \
    /opt/venv/bin/pip install --no-cache-dir --upgrade pip setuptools wheel; \
    rm -rf /var/lib/apt/lists/*

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY backend/requirements.txt /tmp/requirements.txt
RUN set -eux; \
    /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt; \
    apt-get purge -y --auto-remove python3-dev build-essential; \
    rm -rf /var/lib/apt/lists/* /tmp/requirements.txt

COPY --from=mapreduce-build /build/target/cartscope-mapreduce.jar /opt/cartscope/cartscope-mapreduce.jar

WORKDIR /opt/cartscope
COPY backend/alembic.ini ./alembic.ini
COPY backend/alembic ./alembic
COPY backend/app ./app
COPY backend/entrypoint.sh /usr/local/bin/cartscope-backend

RUN set -eux; \
    chmod +x /usr/local/bin/cartscope-backend; \
    mkdir -p /var/lib/cartscope/uploads /var/lib/cartscope/joblogs; \
    chown -R hadoop:hadoop /opt/cartscope /var/lib/cartscope

USER hadoop

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/cartscope-backend"]
CMD ["api"]
