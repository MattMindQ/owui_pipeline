# Custom OWUI Langfuse Pipeline

File:
- `langfuse_owui_custom_pipeline.py`

Purpose:
- current Langfuse v3 integration for OpenWebUI
- capture configured skills and tools from OWUI model metadata
- capture available skills from the injected `<available_skills>` block
- capture actual skill use via `view_skill` tool calls
- capture actual tool calls and tool outputs
- suppress OWUI background tasks by default:
  - `title_generation`
  - `tags_generation`
  - `follow_up_generation`

Recent improvements:
- fixed Langfuse client initialization compatibility across environments that expect either `base_url` or `host`
- fixed root span lifecycle so traces are explicitly ended and flushed
- fixed skill usage capture when OWUI serializes tool execution into HTML `<details type="tool_calls"...>` blocks
- fixed tool-call capture for HTML-serialized tool calls, not just structured `tool_calls`
- added tool output capture for HTML-serialized tool calls
- added result summaries for HTML-serialized tool calls:
  - result type
  - keys
  - preview
  - content hash when applicable

Default behavior:
- traces normal assistant conversations
- stores OWUI metadata, model metadata, configured `skillIds`, configured `toolIds`
- stores used skills when `view_skill` is called
- stores assistant token usage from OWUI `usage`, preferring assistant-message usage and falling back to compatible OWUI body usage locations when needed
- stores actual tool calls used during a run, including cases where OWUI only exposes them in assistant message content
- stores tool outputs when available

Observed behavior validated against your Langfuse Cloud project:
- traces are created successfully for main chat turns
- configured tools and configured skills are recorded in trace metadata
- used skills are recorded when a `view_skill` call occurs
- actual tool calls such as `retrieve` and `list_knowledge_bases` are recorded as observations
- background OWUI tasks remain excluded by default

Required environment variables:
- `LANGFUSE_PUBLIC_KEY`
- `LANGFUSE_SECRET_KEY`
- `LANGFUSE_HOST`

Optional valves:
- `trace_background_tasks`
- `capture_full_inputs`
- `capture_full_outputs`
- `capture_tool_outputs`
- `include_skill_content_preview`
- `debug`

Notes:
- This pipeline is built around the payload shape observed on your OpenWebUI `v0.8.10`.
- It does not require modifying OWUI core code.
- It uses `base_url=` for the Langfuse client and `usage_details=` for generation usage updates.
- Some OWUI runs expose tool execution as structured arrays, others serialize them into assistant HTML/details blocks. This pipeline handles both.
- OWUI usage can appear in different response locations depending on route/provider shape; this pipeline checks the assistant message first, then compatible body-level fallbacks.
