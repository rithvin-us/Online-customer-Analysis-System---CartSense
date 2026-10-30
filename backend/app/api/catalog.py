"""The analysis catalogue, served from the registry."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.schemas import AnalysisOut, analysis_to_schema
from app.services import registry

router = APIRouter(prefix="/analyses", tags=["catalogue"])


@router.get("", response_model=list[AnalysisOut])
def list_analyses() -> list[AnalysisOut]:
    return [analysis_to_schema(analysis) for analysis in registry.all_analyses()]


@router.get("/{key}", response_model=AnalysisOut)
def get_analysis(key: str) -> AnalysisOut:
    try:
        return analysis_to_schema(registry.get_analysis(key))
    except KeyError as unknown:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(unknown)) from unknown
