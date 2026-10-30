# ---------------------------------------------------------------------------
# CartScope
#
# Build order matters: the backend image is built FROM the Hadoop image, so the
# Hadoop image has to exist first. `make build` does this in the right order;
# `docker compose build` on its own does not guarantee it.
# ---------------------------------------------------------------------------
SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

COMPOSE := docker compose
HADOOP_VERSION := $(shell grep -E '^HADOOP_VERSION=' .env | cut -d= -f2)

CLUSTER_SERVICES := namenode datanode1 datanode2 datanode3 \
                    resourcemanager nodemanager1 nodemanager2 nodemanager3 \
                    historyserver hadoop-client
APP_SERVICES := postgres redis api worker frontend

## help: list the available targets
help:
	@echo "CartScope — distributed retail intelligence platform"
	@echo
	@grep -E '^## ' $(MAKEFILE_LIST) | sed -e 's/## //' | awk -F': ' '{printf "  \033[1m%-22s\033[0m %s\n", $$1, $$2}'
	@echo

## build: build every image, in dependency order
build: pull-base build-hadoop build-app

## build-hadoop: build the CartScope Hadoop image
build-hadoop:
	$(COMPOSE) build namenode

## build-app: build the backend and frontend images
build-app:
	$(COMPOSE) build api frontend

## pull-base: pull the official Apache Hadoop base image
pull-base:
	docker pull apache/hadoop:$(HADOOP_VERSION)

## up: start the whole stack
up:
	$(COMPOSE) up -d
	@echo
	@echo "  API        http://localhost:$$(grep -E '^API_HOST_PORT=' .env | cut -d= -f2)/api/docs"
	@echo "  Workbench  http://localhost:$$(grep -E '^FRONTEND_HOST_PORT=' .env | cut -d= -f2)"
	@echo "  NameNode   http://localhost:$$(grep -E '^NAMENODE_UI_PORT=' .env | cut -d= -f2)"
	@echo "  YARN       http://localhost:$$(grep -E '^RESOURCEMANAGER_UI_PORT=' .env | cut -d= -f2)"
	@echo "  History    http://localhost:$$(grep -E '^HISTORYSERVER_UI_PORT=' .env | cut -d= -f2)"

## up-cluster: start only the Hadoop cluster
up-cluster:
	$(COMPOSE) up -d $(CLUSTER_SERVICES)

## down: stop the stack, keeping all data
down:
	$(COMPOSE) down

## destroy: stop the stack AND delete every volume, including HDFS
destroy:
	@echo "This deletes the NameNode metadata, all HDFS block storage and the database."
	@read -r -p "Type 'destroy' to confirm: " answer; \
	 if [ "$$answer" = "destroy" ]; then $(COMPOSE) down -v; else echo "cancelled"; fi

## status: show container state and health
status:
	$(COMPOSE) ps

## wait: block until the cluster reports healthy
wait:
	@scripts/wait_for_cluster.sh

## logs: follow the logs of the application tier
logs:
	$(COMPOSE) logs -f api worker

## logs-cluster: follow the Hadoop daemon logs
logs-cluster:
	$(COMPOSE) logs -f namenode resourcemanager nodemanager1

## test-java: run the MapReduce unit tests
test-java:
	docker run --rm -v "$(CURDIR)/mapreduce":/src -v cartscope-m2:/root/.m2 \
	  -w /src maven:3.9-eclipse-temurin-17 mvn -B test

## test-api: run the backend test suite
test-api:
	$(COMPOSE) exec -T api python -m pytest -q

## test-e2e: run the end-to-end check against the running stack
test-e2e:
	scripts/e2e_check.sh

## typecheck-web: typecheck the frontend
typecheck-web:
	docker run --rm -v "$(CURDIR)/frontend":/app -w /app -u "$$(id -u):$$(id -g)" \
	  -e HOME=/tmp node:22-alpine npx tsc --noEmit

## dataset: download the UCI Online Retail dataset and convert it to CSV
dataset:
	scripts/fetch_uci_dataset.sh

## seed: load the UCI dataset into the running stack and validate it
seed:
	scripts/seed_dataset.sh

## hdfs: list the CartScope tree in HDFS
hdfs:
	$(COMPOSE) exec hadoop-client hdfs dfs -ls -R /cartscope | head -60

## report: print the HDFS DataNode report
report:
	$(COMPOSE) exec hadoop-client hdfs dfsadmin -report

## shell-client: open a shell with a configured Hadoop client
shell-client:
	$(COMPOSE) exec hadoop-client bash

## shell-db: open a psql session
shell-db:
	$(COMPOSE) exec postgres psql -U "$$(grep -E '^POSTGRES_USER=' .env | cut -d= -f2)" \
	  -d "$$(grep -E '^POSTGRES_DB=' .env | cut -d= -f2)"

.PHONY: help build build-hadoop build-app vendor-hadoop up up-cluster down destroy \
        status wait logs logs-cluster test-java test-api test-e2e typecheck-web \
        dataset seed hdfs report shell-client shell-db pull-base
