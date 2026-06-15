"""
title: OpenAI Native PDF Input
author: open-webui community
version: 0.1.0
required_open_webui_version: 0.6.0
license: MIT
description: >
  Send uploaded PDFs to OpenAI-compatible models using the provider's built-in
  file input (a base64 data URL) instead of Open WebUI's local text extraction /
  RAG. This lets the model read page layout, scanned pages, tables and images
  inside the PDF — the same capability proposed in PR #15598, but as a Filter
  function that needs no core code changes.

How it works
------------
A Filter's `inlet` runs inside `process_chat_payload` *before* the file/RAG
handler. For every uploaded PDF this filter:
  1. loads the original file from storage and base64-encodes it,
  2. injects an OpenAI `{"type": "file", "file": {...}}` content part into the
     current user message, and
  3. removes that PDF from `body["files"]` so the default RAG pipeline does not
     also extract and inject its text.

Non-PDF files are left untouched and continue to flow through normal RAG.

Usage
-----
Admin Panel -> Functions -> Import / "+", paste this file, enable it. Then attach
it to your OpenAI / Azure OpenAI models (Workspace -> Models -> Filters), or
enable it globally. Use it only with models whose endpoint understands the
Chat Completions `file` content part (OpenAI `gpt-4o`/`gpt-4.1`/`o*`, Azure
OpenAI, and compatible gateways).

Notes / limitations
-------------------
- Works with both the OpenAI Chat Completions and Responses APIs. The filter
  always emits a Chat Completions `file` part; for Responses endpoints the
  router's `convert_to_responses_payload` translates it into an `input_file`
  part (requires Open WebUI built with that translation present).
- Large PDFs are skipped (see the `max_pdf_mb` valve) to stay under provider
  request-size limits.
- A PDF is only sent natively when the requester actually has access to it
  (direct ownership, admin, or a knowledge-base/shared grant). This blocks a
  forged API request from inlining an arbitrary file id off disk; legitimate
  but unverifiable files simply fall back to the default RAG pipeline.
"""

import base64
import logging
import mimetypes
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from open_webui.models.files import Files
from open_webui.models.users import UserModel
from open_webui.storage.provider import Storage
from open_webui.utils.access_control.files import has_access_to_file

log = logging.getLogger(__name__)

PDF_CONTENT_TYPE = "application/pdf"


class Filter:
    class Valves(BaseModel):
        priority: int = Field(
            default=0,
            description="Execution priority among filters (lower runs first).",
        )
        max_pdf_mb: float = Field(
            default=28.0,
            description="Skip PDFs larger than this size in MB (provider request limits).",
        )
        attach_to_last_message: bool = Field(
            default=True,
            description="Attach the PDF to the last user message (off = first user message).",
        )
        debug: bool = Field(
            default=False,
            description="Emit verbose logs about what the filter does.",
        )

    def __init__(self):
        self.valves = self.Valves()
        # NOTE: we intentionally do NOT set `file_handler = True`. That flag tells
        # Open WebUI to drop *all* uploaded files from RAG; instead we surgically
        # remove only the PDFs we successfully handle, so other file types still
        # get normal retrieval.

    # --- helpers ---------------------------------------------------------

    def _log(self, msg: str):
        if self.valves.debug:
            log.info(f"[openai_native_pdf] {msg}")

    def _is_pdf(self, item: dict) -> bool:
        if not isinstance(item, dict) or item.get("type") != "file":
            return False
        file_obj = item.get("file") or {}
        meta = file_obj.get("meta") or {}
        content_type = (meta.get("content_type") or "").lower()
        if content_type == PDF_CONTENT_TYPE:
            return True
        # Fall back to the filename extension when content_type is missing.
        name = meta.get("name") or file_obj.get("filename") or ""
        return mimetypes.guess_type(name)[0] == PDF_CONTENT_TYPE

    async def _can_access(self, file, user: Optional[dict]) -> bool:
        if not user:
            return False
        if file.user_id == user.get("id") or user.get("role") == "admin":
            return True
        # Group / knowledge-base / shared-chat grants (mirrors core behaviour).
        try:
            return await has_access_to_file(file.id, "read", UserModel(**user))
        except Exception as e:
            self._log(f"access check failed for {file.id}: {e}")
            return False

    async def _build_pdf_part(self, file_obj: dict, user: Optional[dict]) -> Optional[dict]:
        file_id = file_obj.get("id")
        meta = file_obj.get("meta") or {}
        name = meta.get("name") or file_obj.get("filename") or "document.pdf"
        if not file_id:
            return None

        file = await Files.get_file_by_id(file_id)
        if not file or not file.path:
            self._log(f"no stored file for id={file_id}")
            return None

        if not await self._can_access(file, user):
            self._log(f"user lacks access to {file_id}; leaving for default RAG")
            return None

        try:
            path = Path(Storage.get_file(file.path))
            if not path.is_file():
                self._log(f"file path missing on disk: {path}")
                return None
            data = path.read_bytes()
        except Exception as e:
            log.warning(f"[openai_native_pdf] cannot read {file_id}: {e}")
            return None

        if len(data) > self.valves.max_pdf_mb * 1024 * 1024:
            self._log(f"skipping {name}: exceeds max_pdf_mb={self.valves.max_pdf_mb}")
            return None

        encoded = base64.b64encode(data).decode("utf-8")
        return {
            "type": "file",
            "file": {
                "filename": name,
                "file_data": f"data:{PDF_CONTENT_TYPE};base64,{encoded}",
            },
        }

    def _pick_user_message(self, messages: list) -> Optional[dict]:
        order = range(len(messages))
        if self.valves.attach_to_last_message:
            order = reversed(order)
        for i in order:
            if isinstance(messages[i], dict) and messages[i].get("role") == "user":
                return messages[i]
        return None

    # --- filter entrypoint ----------------------------------------------

    async def inlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        files = body.get("files") or []
        pdf_items = [item for item in files if self._is_pdf(item)]
        if not pdf_items:
            return body

        parts = []
        handled = []
        for item in pdf_items:
            part = await self._build_pdf_part(item.get("file") or {}, __user__)
            if part:
                parts.append(part)
                handled.append(item)

        if not parts:
            return body

        target = self._pick_user_message(body.get("messages") or [])
        if target is None:
            self._log("no user message found to attach PDFs to")
            return body

        content = target.get("content")
        if isinstance(content, list):
            target["content"] = [*parts, *content]
        elif isinstance(content, str) and content:
            target["content"] = [*parts, {"type": "text", "text": content}]
        else:
            target["content"] = list(parts)

        # Remove the PDFs we handled so the default RAG/extraction pipeline does
        # not process them again. metadata["files"] is rebuilt from body["files"]
        # downstream, so editing body["files"] is what actually takes effect; we
        # also clear the current metadata copy defensively.
        handled_ids = {id(item) for item in handled}
        body["files"] = [item for item in files if id(item) not in handled_ids]
        metadata = body.get("metadata")
        if isinstance(metadata, dict) and isinstance(metadata.get("files"), list):
            metadata["files"] = [item for item in metadata["files"] if not self._is_pdf(item)]

        self._log(f"attached {len(parts)} PDF(s) natively; {len(body['files'])} file(s) left for RAG")
        return body
