"""FastAPI application for the File Butler backend."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from file_butler_server.core.database import initialize_database
from file_butler_server.services.dashboard import get_overview_dashboard
from file_butler_server.services.file_picker import select_local_file_paths
from file_butler_server.services.library import get_library_page
from file_butler_server.services.settings import (
    get_storage_root_setting,
    update_storage_root_setting,
)
from file_butler_server.services.suggestions import decide_suggestion, get_suggestions_page
from file_butler_server.services.uploads import (
    analyze_file_path,
    analyze_selected_file,
    get_analysis_page,
    register_analysis_metadata,
)


class AnalysisMetadataRequest(BaseModel):
    file_name: str = Field(min_length=1)
    size_bytes: int = Field(default=0, ge=0)
    mime_type: str | None = None


class AnalyzeFileRequest(BaseModel):
    file_name: str | None = None
    content_base64: str | None = None
    mime_type: str | None = None
    source_path: str | None = None


class StorageRootRequest(BaseModel):
    root_path: str = Field(min_length=1)


class SuggestionDecisionRequest(BaseModel):
    decision: str


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    initialize_database()
    yield


app = FastAPI(title="File Butler API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/dashboard/overview")
def dashboard_overview() -> dict[str, object]:
    return get_overview_dashboard()


@app.get("/api/uploads")
def upload_page() -> dict[str, object]:
    return get_analysis_page()


@app.post("/api/uploads/register")
def register_upload(request: AnalysisMetadataRequest) -> dict[str, object]:
    return register_analysis(request)


@app.post("/api/uploads")
def upload_file(request: AnalyzeFileRequest) -> dict[str, object]:
    return analyze_file(request)


@app.get("/api/analysis")
def analysis_page() -> dict[str, object]:
    return get_analysis_page()


@app.post("/api/analysis/register")
def register_analysis(request: AnalysisMetadataRequest) -> dict[str, object]:
    try:
        return register_analysis_metadata(
            file_name=request.file_name,
            size_bytes=request.size_bytes,
            mime_type=request.mime_type,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/analysis")
def analyze_file(request: AnalyzeFileRequest) -> dict[str, object]:
    try:
        if request.source_path:
            return analyze_file_path(source_path=request.source_path)
        if not request.file_name or not request.content_base64:
            raise ValueError("请选择文件，或提供本机文件路径。")
        return analyze_selected_file(
            file_name=request.file_name,
            content_base64=request.content_base64,
            mime_type=request.mime_type,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/analysis/select-local-files")
def select_local_files() -> dict[str, object]:
    try:
        return {"paths": select_local_file_paths()}
    except RuntimeError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/suggestions")
def suggestions_page() -> dict[str, object]:
    return get_suggestions_page()


@app.get("/api/library")
def library_page() -> dict[str, object]:
    return get_library_page()


@app.get("/api/settings/storage-root")
def storage_root_setting() -> dict[str, object]:
    return get_storage_root_setting()


@app.patch("/api/settings/storage-root")
def update_storage_root(request: StorageRootRequest) -> dict[str, object]:
    try:
        return update_storage_root_setting(root_path=request.root_path)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/suggestions/{suggestion_id}/decision")
def suggestion_decision(
    suggestion_id: str,
    request: SuggestionDecisionRequest,
) -> dict[str, object]:
    try:
        return decide_suggestion(suggestion_id, request.decision)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
