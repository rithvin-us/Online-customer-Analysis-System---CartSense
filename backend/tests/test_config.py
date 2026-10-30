"""The HDFS layout the whole product depends on."""

from __future__ import annotations

from app.core.config import Settings


def test_paths_follow_the_documented_layout() -> None:
    settings = Settings(hdfs_root="/cartscope")

    assert settings.dataset_dir("d1") == "/cartscope/datasets/d1"
    assert settings.version_dir("d1", "v1") == "/cartscope/datasets/d1/versions/v1"
    assert settings.raw_dir("d1", "v1") == "/cartscope/datasets/d1/versions/v1/raw"
    assert settings.validated_dir("d1", "v1") == "/cartscope/datasets/d1/versions/v1/validated"
    assert settings.rejected_dir("d1", "v1") == "/cartscope/datasets/d1/versions/v1/rejected"
    assert settings.job_work_dir("run-1", "monthly_sales") == "/cartscope/jobs/run-1/monthly_sales"
    assert settings.result_dir("run-1", "monthly_sales") == "/cartscope/results/run-1/monthly_sales"
    assert settings.manifest_path("run-1", "monthly_sales") == (
        "/cartscope/manifests/run-1/monthly_sales.json"
    )


def test_results_and_work_never_share_a_directory() -> None:
    # Intermediate stage output is scratch and gets cleared; a result is never
    # overwritten. They must not be able to collide.
    settings = Settings()
    assert settings.job_work_dir("r", "a") != settings.result_dir("r", "a")


def test_upload_limit_is_expressed_in_bytes() -> None:
    assert Settings(max_upload_mb=2).max_upload_bytes == 2 * 1024 * 1024


def test_psycopg_dsn_drops_the_sqlalchemy_driver() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://user:pass@postgres:5432/cartscope"
    )
    assert settings.psycopg_dsn == "postgresql://user:pass@postgres:5432/cartscope"
