# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# CartScope backend image: FastAPI + Celery on top of a configured Hadoop
# client.
#
# The image is built FROM the CartScope Hadoop image rather than from a Python
# base image, and that is a deliberate architectural choice: the Celery worker
# submits jobs with the real `hadoop jar` and `hdfs dfs` commands, so it needs
# the genuine Hadoop client, the cluster's configuration files and a matching
# JVM. Reusing the cluster image guarantees the client is exactly the version
# the daemons are.
#
# Build order matters: `cartscope/hadoop:<version>` must exist first.
# `make build` does this in the right order.
# ---------------------------------------------------------------------------
ARG HADOOP_VERSION=3.5.0

# --- Stage 1: compile the MapReduce jar ------------------------------------
FROM maven:3.9-eclipse-temurin-17 AS mapreduce-build
WORKDIR /build
# Resolve dependencies against the POM alone first, so that editing a Java
# source file does not re-download the Hadoop client libraries.
COPY mapreduce/pom.xml ./pom.xml
RUN mvn -B -q dependency:go-offline
COPY mapreduce/src ./src
# The unit tests run here, so an image is never built from code that fails them.
RUN mvn -B package && ls -l target/cartscope-mapreduce.jar

# --- Stage 2: the runtime image --------------------------------------------
FROM cartscope/hadoop:${HADOOP_VERSION}

USER root

# The base image already carries Python 3.12 with venv, so no system packages
# are installed here: the only build-time network access is PyPI. The
# application lives in a virtual environment so that pip never fights the
# system package manager.
COPY backend/requirements.txt /tmp/requirements.txt
RUN set -eux; \
    python3 -m venv /opt/venv; \
    /opt/venv/bin/pip install --no-cache-dir --upgrade pip setuptools wheel; \
    /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt; \
    rm -f /tmp/requirements.txt

ENV PATH=/opt/venv/bin:/opt/hadoop/bin:/opt/hadoop/sbin:/opt/java/openjdk/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --from=mapreduce-build /build/target/cartscope-mapreduce.jar /opt/cartscope/cartscope-mapreduce.jar

WORKDIR /opt/cartscope
COPY backend/alembic.ini ./alembic.ini
COPY backend/pytest.ini ./pytest.ini
COPY backend/alembic ./alembic
COPY backend/app ./app
COPY backend/tests ./tests
COPY backend/entrypoint.sh /usr/local/bin/cartscope-backend

RUN set -eux; \
    chmod +x /usr/local/bin/cartscope-backend; \
    mkdir -p /var/lib/cartscope/uploads /var/lib/cartscope/joblogs; \
    # The base image's hadoop user is in the `users` group, not a `hadoop` one.
    chown -R hadoop:users /opt/cartscope /opt/venv /var/lib/cartscope; \
    # Fail the build rather than ship an image whose application cannot even be
    # imported. This needs no database: importing only builds the app object.
    su hadoop -s /bin/bash -c 'cd /opt/cartscope && /opt/venv/bin/python3 -c "import app.main"'

USER hadoop

ENTRYPOINT ["/usr/local/bin/cartscope-backend"]
CMD ["api"]
