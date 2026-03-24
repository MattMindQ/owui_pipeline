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

Default behavior:
- traces normal assistant conversations
- stores OWUI metadata, model metadata, configured `skillIds`, configured `toolIds`
- stores used skills when `view_skill` is called
- stores assistant token usage from OWUI `usage`

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
