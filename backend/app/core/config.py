"""Application settings.

Every value is supplied by the environment, which is what lets the same image
run as the API and as the Celery worker, and lets the cluster be resized from
``.env`` without touching code.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CARTSCOPE_", extra="ignore")

    # --- Datastores --------------------------------------------------------
    database_url: str = "postgresql+psycopg://cartscope:cartscope@postgres:5432/cartscope"
    redis_url: str = "redis://redis:6379/0"

    # --- Hadoop endpoints --------------------------------------------------
    namenode_host: str = Field(default="namenode", alias="CARTSCOPE_NAMENODE_HOST")
    rm_host: str = Field(default="resourcemanager", alias="CARTSCOPE_RM_HOST")
    history_host: str = Field(default="historyserver", alias="CARTSCOPE_HISTORY_HOST")
    namenode_ui: str = "http://namenode:9870"
    rm_ui: str = "http://resourcemanager:8088"
    history_ui: str = "http://historyserver:19888"

    # --- Cluster profile, reported to the UI so the numbers can be explained
    hdfs_replication: int = 2
    hdfs_block_size: int = 4_194_304
    nm_memory_mb: int = 2048
    nm_vcores: int = 2
    map_memory_mb: int = 512
    reduce_memory_mb: int = 512
    am_memory_mb: int = 768

    # --- MapReduce submission ---------------------------------------------
    mr_jar: str = "/opt/cartscope/cartscope-mapreduce.jar"
    default_reducers: int = 3
    hadoop_user_name: str = Field(default="hadoop", alias="HADOOP_USER_NAME")
    #: Optional ceiling on the bytes per input split. Zero leaves Hadoop to
    #: split on HDFS block boundaries.
    split_maxsize: int = 0
    #: Wall-clock ceiling for one `hadoop jar` invocation.
    job_timeout_seconds: int = 3600

    # --- Storage -----------------------------------------------------------
    hdfs_root: str = "/cartscope"
    upload_dir: Path = Path("/var/lib/cartscope/uploads")
    joblog_dir: Path = Path("/var/lib/cartscope/joblogs")
    max_upload_mb: int = 512

    # --- Behaviour ---------------------------------------------------------
    log_level: str = "INFO"
    #: Rows returned by a result preview endpoint when no limit is given.
    default_result_limit: int = 100
    #: Hard ceiling on rows a single preview request may ask for.
    max_result_limit: int = 5000

    @property
    def psycopg_dsn(self) -> str:
        """The database URL in libpq form, for the readiness probe."""
        return self.database_url.replace("postgresql+psycopg://", "postgresql://")

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    # --- HDFS layout -------------------------------------------------------
    def dataset_dir(self, dataset_id: str) -> str:
        return f"{self.hdfs_root}/datasets/{dataset_id}"

    def version_dir(self, dataset_id: str, version_id: str) -> str:
        return f"{self.dataset_dir(dataset_id)}/versions/{version_id}"

    def raw_dir(self, dataset_id: str, version_id: str) -> str:
        return f"{self.version_dir(dataset_id, version_id)}/raw"

    def validated_dir(self, dataset_id: str, version_id: str) -> str:
        return f"{self.version_dir(dataset_id, version_id)}/validated"

    def rejected_dir(self, dataset_id: str, version_id: str) -> str:
        return f"{self.version_dir(dataset_id, version_id)}/rejected"

    def job_work_dir(self, run_id: str, analysis: str) -> str:
        return f"{self.hdfs_root}/jobs/{run_id}/{analysis}"

    def result_dir(self, run_id: str, analysis: str) -> str:
        return f"{self.hdfs_root}/results/{run_id}/{analysis}"

    def manifest_path(self, run_id: str, analysis: str) -> str:
        return f"{self.hdfs_root}/manifests/{run_id}/{analysis}.json"

    def benchmark_dir(self) -> str:
        return f"{self.hdfs_root}/benchmarks"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
