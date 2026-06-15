# Open WebUI Functions

Drop-in [Filter / Function plugins](https://docs.openwebui.com/features/plugin/functions/)
for Open WebUI. These are *not* part of the backend package — import them from
**Admin Panel → Functions** (or **Workspace → Functions**), then enable and (for
filters) attach them to the relevant models.

## `openai_native_pdf.py` — OpenAI Native PDF Input

A **Filter** that sends uploaded PDFs to OpenAI-compatible models via the
provider's built-in file input (a base64 `data:` URL) instead of Open WebUI's
local text extraction / RAG. The model can then read page layout, scanned pages,
tables and images inside the PDF.

This is a no-core-change alternative to PR #15598 ("Enable OpenAI Built-in PDF
Support").

**How it works:** the filter's `inlet` runs before the RAG file handler. For each
uploaded PDF it base64-encodes the original file, injects an OpenAI
`{"type": "file", "file": {...}}` content part into the current user message, and
removes that PDF from `body["files"]` so RAG does not also process it. Non-PDF
files are left to normal retrieval.

**Setup**

1. Admin Panel → Functions → `+` / Import, paste `openai_native_pdf.py`, save and
   enable it.
2. Attach it to your OpenAI / Azure OpenAI models (Workspace → Models → Filters),
   or enable it globally.
3. Start a chat with that model, upload a PDF, and ask away.

**Use only** with models whose endpoint understands the Chat Completions `file`
content part (OpenAI `gpt-4o` / `gpt-4.1` / `o*`, Azure OpenAI, compatible
gateways).

**Valves**

| Valve | Default | Purpose |
| --- | --- | --- |
| `priority` | `0` | Order among filters (lower runs first). |
| `max_pdf_mb` | `28.0` | Skip PDFs larger than this (provider request limits). |
| `attach_to_last_message` | `true` | Attach to the last user message (off = first). |
| `debug` | `false` | Verbose logging. |

**Works with** both the OpenAI Chat Completions and Responses APIs. The filter
emits a Chat Completions `file` part; for Responses endpoints the router's
`convert_to_responses_payload` translates it to an `input_file` part.

**Limitations**

- Large PDFs are skipped (`max_pdf_mb`) to stay under provider request limits.
- A PDF is sent natively only when the requester has access to it (ownership,
  admin, or a knowledge-base/shared grant); otherwise it falls back to default
  RAG. This blocks a forged API request from inlining an arbitrary file id.
