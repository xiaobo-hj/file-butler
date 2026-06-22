"""Agent suggestions for analyzed files."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_QWEN_MODEL = "qwen3.7-max"
_LOCAL_ENV_LOADED = False


@dataclass(frozen=True)
class OrganizationPlan:
    summary: str
    folder_path: str
    new_file_name: str
    tags: list[str]
    key_info: dict[str, str]
    reason: str
    confidence: float
    extractor: str


def build_organization_plan(
    *,
    file_name: str,
    mime_type: str | None,
    text_preview: str,
    library_context: dict[str, Any] | None = None,
) -> OrganizationPlan:
    plan = _call_qwen(
        file_name=file_name,
        mime_type=mime_type,
        text_preview=text_preview,
        library_context=library_context,
    )
    if plan is not None:
        return plan

    return _build_fallback_plan(file_name=file_name, mime_type=mime_type, text_preview=text_preview)


def _call_qwen(
    *,
    file_name: str,
    mime_type: str | None,
    text_preview: str,
    library_context: dict[str, Any] | None,
) -> OrganizationPlan | None:
    _load_local_env()
    api_key = os.environ.get("QWEN_API_KEY")
    if not api_key:
        return None

    base_url = os.environ.get("QWEN_BASE_URL", DEFAULT_QWEN_BASE_URL).rstrip("/")
    model = os.environ.get("QWEN_MODEL", DEFAULT_QWEN_MODEL)
    endpoint = f"{base_url}/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是 FileButler 的文件整理 Agent。"
                    "只返回一个 JSON 对象，不要 Markdown。"
                    "字段必须包含 summary, folderPath, newFileName, tags, keyInfo, "
                    "reason, confidence。"
                    "folderPath 使用中文路径层级，层级之间用 ' / ' 分隔。"
                    "优先从 existingFolders 中选择最合适的目录；"
                    "只有明显没有合适目录时才新建 folderPath。"
                    "判断目录时要参考 existingFiles 的 fileName、folderPath、summary，"
                    "保持同类文件放在同一目录。"
                    "newFileName 保留原文件扩展名，避免路径分隔符。"
                    "confidence 是 0 到 1 的数字。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "fileName": file_name,
                        "mimeType": mime_type,
                        "textPreview": text_preview[:6000],
                        "existingFolders": (library_context or {}).get("folders", []),
                        "existingFiles": (library_context or {}).get("files", []),
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }

    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError):
        return None

    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None

    if not isinstance(content, str):
        return None

    try:
        raw_plan = json.loads(_strip_json_fence(content))
    except json.JSONDecodeError:
        return None

    return _normalize_plan(raw_plan, file_name, extractor=f"qwen:{model}")


def _normalize_plan(
    raw_plan: dict[str, Any],
    original_file_name: str,
    extractor: str,
) -> OrganizationPlan:
    tags = raw_plan.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    key_info = raw_plan.get("keyInfo", {})
    if not isinstance(key_info, dict):
        key_info = {}

    reason = str(raw_plan.get("reason") or "根据文件名和可提取内容生成整理建议。")

    return OrganizationPlan(
        summary=str(raw_plan.get("summary") or "已导入文件，等待确认整理。")[:1200],
        folder_path=_clean_folder_path(str(raw_plan.get("folderPath") or "未分类")),
        new_file_name=_safe_file_name(str(raw_plan.get("newFileName") or original_file_name)),
        tags=[str(tag)[:24] for tag in tags if str(tag).strip()][:8],
        key_info={str(key)[:32]: str(value)[:160] for key, value in key_info.items() if value},
        reason=reason[:1200],
        confidence=_clamp_confidence(raw_plan.get("confidence")),
        extractor=extractor,
    )


def _build_fallback_plan(
    *,
    file_name: str,
    mime_type: str | None,
    text_preview: str,
) -> OrganizationPlan:
    suffix = Path(file_name).suffix
    summary = (
        text_preview.strip().replace("\n", " ")[:240]
        if text_preview.strip()
        else "已导入文件，等待确认整理。"
    )

    return OrganizationPlan(
        summary=summary,
        folder_path="未分类",
        new_file_name=_safe_file_name(file_name),
        tags=["待确认"],
        key_info={"文件类型": mime_type or suffix.lstrip(".") or "未知"},
        reason="模型未返回有效建议，先放入未分类目录供你确认。",
        confidence=0.0,
        extractor="fallback",
    )


def _strip_json_fence(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped


def _clean_folder_path(folder_path: str) -> str:
    parts = [_safe_path_part(part) for part in folder_path.split("/")]
    cleaned = [part for part in parts if part]
    return " / ".join(cleaned) or "未分类"


def _safe_file_name(file_name: str) -> str:
    name = Path(file_name.replace("\\", "/")).name.strip()
    return re.sub(r"[\x00-\x1f]", "", name) or "文件"


def _safe_path_part(part: str) -> str:
    return re.sub(r"[\x00-\x1f:/\\]+", " ", part).strip()


def _clamp_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.7
    return min(max(confidence, 0.0), 1.0)


def _load_local_env() -> None:
    global _LOCAL_ENV_LOADED
    if _LOCAL_ENV_LOADED:
        return

    _LOCAL_ENV_LOADED = True
    candidates = [
        Path.cwd() / ".env",
        Path.cwd().parent / ".env",
        Path(__file__).resolve().parents[4] / ".env",
    ]
    for env_path in candidates:
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", maxsplit=1)
            key = key.strip()
            value = value.strip().strip("\"'")
            if key and key not in os.environ:
                os.environ[key] = value
