"""
title: Langfuse OWUI Custom Pipeline
author: codex
date: 2026-03-24
version: 0.1.1
license: MIT
description: Langfuse v3 filter pipeline for OpenWebUI with skill and tool capture.
requirements: langfuse>=3.0.0
"""

from typing import Any, Dict, List, Optional
import hashlib
import json
import os
import re
import uuid

from langfuse import Langfuse
from pydantic import BaseModel


def get_last_assistant_message(messages: List[dict]) -> Optional[dict]:
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "assistant":
            return message
    return None


def safe_json(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): safe_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [safe_json(item) for item in value]
    if hasattr(value, "model_dump"):
        try:
            return safe_json(value.model_dump())
        except Exception:
            return repr(value)
    return repr(value)


def parse_available_skills(messages: List[dict]) -> List[dict]:
    skills: List[dict] = []
    pattern = re.compile(
        r"<skill>\s*<name>(?P<name>.*?)</name>\s*<description>(?P<description>.*?)</description>\s*</skill>",
        re.DOTALL,
    )

    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, str) or "<available_skills>" not in content:
            continue

        for match in pattern.finditer(content):
            name = match.group("name").strip()
            description = match.group("description").strip()
            if name:
                skills.append({"name": name, "description": description})

    deduped: List[dict] = []
    seen = set()
    for skill in skills:
        key = skill["name"].lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(skill)
    return deduped


def extract_usage(message: Optional[dict]) -> Optional[dict]:
    if not message:
        return None

    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None

    input_tokens = usage.get("input_tokens") or usage.get("prompt_tokens")
    output_tokens = usage.get("output_tokens") or usage.get("completion_tokens")

    usage_details = {}
    if isinstance(input_tokens, int):
        usage_details["input"] = input_tokens
    if isinstance(output_tokens, int):
        usage_details["output"] = output_tokens
    if isinstance(usage.get("total_tokens"), int):
        usage_details["total"] = usage["total_tokens"]

    prompt_details = usage.get("prompt_tokens_details")
    if isinstance(prompt_details, dict):
        cached = prompt_details.get("cached_tokens")
        if isinstance(cached, int):
            usage_details["cached_input"] = cached

    reasoning_details = usage.get("completion_tokens_details")
    if isinstance(reasoning_details, dict):
        reasoning = reasoning_details.get("reasoning_tokens")
        if isinstance(reasoning, int):
            usage_details["reasoning"] = reasoning

    return usage_details or None


class Pipeline:
    class Valves(BaseModel):
        pipelines: list[str] = ["*"]
        priority: int = 0
        secret_key: str = os.getenv("LANGFUSE_SECRET_KEY", "")
        public_key: str = os.getenv("LANGFUSE_PUBLIC_KEY", "")
        base_url: str = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
        debug: bool = os.getenv("DEBUG_MODE", "false").lower() == "true"
        trace_background_tasks: bool = False
        capture_full_inputs: bool = True
        capture_full_outputs: bool = True
        capture_tool_outputs: bool = True
        include_skill_content_preview: bool = False

    def __init__(self):
        self.type = "filter"
        self.name = "Langfuse OWUI Custom"
        self.valves = self.Valves()
        self.langfuse: Optional[Langfuse] = None
        self.chat_state: Dict[str, Dict[str, Any]] = {}

        self.background_tasks = {
            "title_generation",
            "tags_generation",
            "follow_up_generation",
        }

    def log(self, message: str) -> None:
        if self.valves.debug:
            print(f"[LANGFUSE_OWUI_CUSTOM] {message}")

    def log_always(self, message: str) -> None:
        print(f"[LANGFUSE_OWUI_CUSTOM] {message}")

    async def on_startup(self):
        self.set_langfuse()

    async def on_shutdown(self):
        if self.langfuse:
            self.langfuse.flush()

    async def on_valves_updated(self):
        self.set_langfuse()

    def set_langfuse(self) -> None:
        if not self.valves.secret_key or not self.valves.public_key:
            self.log_always("Langfuse keys not configured")
            self.langfuse = None
            return

        try:
            client_kwargs = {
                "public_key": self.valves.public_key,
                "secret_key": self.valves.secret_key,
                "debug": self.valves.debug,
            }
            try:
                self.langfuse = Langfuse(
                    base_url=self.valves.base_url,
                    **client_kwargs,
                )
            except TypeError as exc:
                if "base_url" not in str(exc):
                    raise
                self.langfuse = Langfuse(
                    host=self.valves.base_url,
                    **client_kwargs,
                )
            self.langfuse.auth_check()
            self.log_always(f"Langfuse ready base_url={self.valves.base_url}")
        except Exception as exc:
            self.log_always(f"Langfuse init failed: {exc}")
            self.langfuse = None

    def should_trace_task(self, task_name: str) -> bool:
        return self.valves.trace_background_tasks or task_name not in self.background_tasks

    def get_chat_id(self, body: dict, __metadata__: Optional[dict], __chat_id__: Optional[str]) -> str:
        metadata = __metadata__ or body.get("metadata") or {}
        return (
            __chat_id__
            or body.get("chat_id")
            or metadata.get("chat_id")
            or f"local-{uuid.uuid4()}"
        )

    def get_state_key(self, body: dict, __metadata__: Optional[dict], __chat_id__: Optional[str]) -> str:
        metadata = __metadata__ or body.get("metadata") or {}
        chat_id = self.get_chat_id(body, __metadata__, __chat_id__)
        message_id = body.get("id") or body.get("message_id") or metadata.get("message_id")
        task_name = self.get_task_name(body, __metadata__, "chat")
        if message_id:
            return f"{chat_id}:{message_id}:{task_name}"
        return f"{chat_id}:{task_name}"

    def get_task_name(self, body: dict, __metadata__: Optional[dict], default: str) -> str:
        metadata = __metadata__ or body.get("metadata") or {}
        return metadata.get("task", default)

    def get_model_info(self, body: dict, __metadata__: Optional[dict], __model__: Optional[dict]) -> dict:
        metadata = __metadata__ or body.get("metadata") or {}
        metadata_model = metadata.get("model") if isinstance(metadata, dict) else None
        model = __model__ or metadata_model or {}
        if not isinstance(model, dict):
            model = {}

        info = model.get("info", {}) if isinstance(model.get("info"), dict) else {}
        meta = info.get("meta", {}) if isinstance(info.get("meta"), dict) else {}

        return {
            "model_id": body.get("model") or model.get("id"),
            "model_name": model.get("name") or body.get("model"),
            "base_model_id": info.get("base_model_id"),
            "configured_tool_ids": meta.get("toolIds", []),
            "configured_skill_ids": meta.get("skillIds", []),
            "configured_filter_ids": meta.get("filterIds", []),
            "builtin_tools": meta.get("builtinTools", {}),
            "capabilities": meta.get("capabilities", {}),
        }

    def build_trace_tags(self, task_name: str, model_info: dict, used_skill_names: List[str]) -> List[str]:
        tags = ["open-webui", "langfuse-custom"]
        if task_name:
            tags.append(f"task:{task_name}")
        if model_info.get("base_model_id"):
            tags.append(f"base-model:{model_info['base_model_id']}")
        for skill_name in used_skill_names:
            tags.append(f"skill-used:{skill_name.lower().replace(' ', '-')}")
        return tags

    def build_trace_metadata(
        self,
        body: dict,
        __metadata__: Optional[dict],
        __user__: Optional[dict],
        __model__: Optional[dict],
        model_info: dict,
        available_skills: List[dict],
        task_name: str,
    ) -> dict:
        metadata = safe_json(__metadata__ or body.get("metadata") or {})
        user = safe_json(__user__ or {})

        return {
            "owui": {
                "task": task_name,
                "chat_id": metadata.get("chat_id"),
                "session_id": metadata.get("session_id"),
                "message_id": metadata.get("message_id"),
                "parent_message_id": metadata.get("parent_message_id"),
                "tool_ids": metadata.get("tool_ids"),
                "features": metadata.get("features"),
                "variables": metadata.get("variables"),
                "params": metadata.get("params"),
                "direct": metadata.get("direct"),
                "files_present": bool(metadata.get("files")),
            },
            "model": safe_json(model_info),
            "available_skills": safe_json(available_skills),
            "user": {
                "id": user.get("id") or metadata.get("user_id"),
                "email": user.get("email"),
                "name": user.get("name"),
                "role": user.get("role"),
            },
            "raw_metadata": metadata,
            "raw_model": safe_json(__model__),
        }

    def get_or_create_state(self, state_key: str) -> dict:
        if state_key not in self.chat_state:
            self.chat_state[state_key] = {
                "trace": None,
                "seen_tool_call_ids": set(),
                "used_skill_names": set(),
            }
        return self.chat_state[state_key]

    def maybe_full_input(self, body: dict) -> Any:
        return safe_json(body) if self.valves.capture_full_inputs else None

    def maybe_full_output(self, body: dict) -> Any:
        return safe_json(body) if self.valves.capture_full_outputs else None

    def summarize_tool_output(self, output_text: str) -> dict:
        summary = {"preview": output_text[:500]}
        summary["sha256"] = hashlib.sha256(output_text.encode("utf-8")).hexdigest()
        return summary

    def capture_tool_calls(self, trace: Any, state: dict, body: dict) -> None:
        messages = body.get("messages", [])
        for message in messages:
            if not isinstance(message, dict):
                continue

            for tool_call in message.get("tool_calls", []) or []:
                call_id = tool_call.get("id")
                if not call_id or call_id in state["seen_tool_call_ids"]:
                    continue

                fn = tool_call.get("function", {}) if isinstance(tool_call.get("function"), dict) else {}
                tool_name = fn.get("name") or "unknown_tool"
                arguments_raw = fn.get("arguments")
                arguments = arguments_raw
                if isinstance(arguments_raw, str):
                    try:
                        arguments = json.loads(arguments_raw)
                    except Exception:
                        arguments = arguments_raw

                metadata = {
                    "tool_type": "call",
                    "tool_name": tool_name,
                    "tool_call_id": call_id,
                }
                observation = trace.start_generation(
                    name=f"tool_call:{tool_name}",
                    model=tool_name,
                    input=safe_json(arguments),
                    metadata=metadata,
                )
                observation.end()
                state["seen_tool_call_ids"].add(call_id)

                if tool_name == "view_skill" and isinstance(arguments, dict):
                    skill_name = arguments.get("name")
                    if skill_name:
                        state["used_skill_names"].add(skill_name)

        outputs = body.get("output", [])
        for item in outputs:
            if not isinstance(item, dict):
                continue

            item_type = item.get("type")
            call_id = item.get("call_id")
            if item_type != "function_call_output" or not call_id:
                continue

            output_payload = item.get("output")
            normalized_output = safe_json(output_payload)

            metadata = {
                "tool_type": "output",
                "tool_call_id": call_id,
            }

            if (
                isinstance(output_payload, list)
                and output_payload
                and isinstance(output_payload[0], dict)
                and isinstance(output_payload[0].get("text"), str)
            ):
                text = output_payload[0]["text"]
                if self.valves.capture_tool_outputs:
                    metadata["output"] = self.summarize_tool_output(text)

                if '"name": "LinkedIn Message Writer"' in text or '"name":"' in text:
                    try:
                        maybe_skill = json.loads(text)
                        if isinstance(maybe_skill, dict) and maybe_skill.get("name"):
                            metadata["skill_name"] = maybe_skill["name"]
                            if self.valves.include_skill_content_preview and isinstance(
                                maybe_skill.get("content"), str
                            ):
                                metadata["skill_content_preview"] = maybe_skill["content"][:500]
                            state["used_skill_names"].add(maybe_skill["name"])
                    except Exception:
                        pass

            observation = trace.start_span(
                name="tool_output",
                input=normalized_output if self.valves.capture_tool_outputs else None,
                metadata=metadata,
            )
            observation.end()

    async def inlet(
        self,
        body: dict,
        __user__: Optional[dict] = None,
        __metadata__: Optional[dict] = None,
        __chat_id__: Optional[str] = None,
        __model__: Optional[dict] = None,
        user: Optional[dict] = None,
    ) -> dict:
        if not self.langfuse:
            return body

        task_name = self.get_task_name(body, __metadata__, "chat")
        if not self.should_trace_task(task_name):
            return body

        chat_id = self.get_chat_id(body, __metadata__, __chat_id__)
        state_key = self.get_state_key(body, __metadata__, __chat_id__)
        state = self.get_or_create_state(state_key)
        model_info = self.get_model_info(body, __metadata__, __model__)
        available_skills = parse_available_skills(body.get("messages", []))

        trace_metadata = self.build_trace_metadata(
            body=body,
            __metadata__=__metadata__,
            __user__=(__user__ or user),
            __model__=__model__,
            model_info=model_info,
            available_skills=available_skills,
            task_name=task_name,
        )

        if state["trace"] is None:
            trace = self.langfuse.start_span(
                name=f"owui.chat:{chat_id}",
                input=self.maybe_full_input(body),
                metadata=trace_metadata,
            )
            trace.update_trace(
                user_id=(__user__ or user or {}).get("id") or trace_metadata["user"].get("email"),
                session_id=trace_metadata["owui"].get("session_id") or chat_id,
                metadata=trace_metadata,
                input=self.maybe_full_input(body),
                tags=self.build_trace_tags(task_name, model_info, []),
            )
            state["trace"] = trace
        else:
            state["trace"].update_trace(
                metadata=trace_metadata,
                input=self.maybe_full_input(body),
            )

        state["model_info"] = model_info
        state["task_name"] = task_name
        state["available_skills"] = available_skills
        state["trace_metadata"] = trace_metadata
        state["state_key"] = state_key
        state["chat_id"] = chat_id
        return body

    async def outlet(
        self,
        body: dict,
        __user__: Optional[dict] = None,
        __metadata__: Optional[dict] = None,
        __chat_id__: Optional[str] = None,
        __model__: Optional[dict] = None,
        user: Optional[dict] = None,
    ) -> dict:
        if not self.langfuse:
            return body

        task_name = self.get_task_name(body, __metadata__, "chat")
        if not self.should_trace_task(task_name):
            return body

        chat_id = self.get_chat_id(body, __metadata__, __chat_id__)
        state_key = self.get_state_key(body, __metadata__, __chat_id__)
        state = self.get_or_create_state(state_key)
        trace = state.get("trace")
        if trace is None:
            return body

        model_info = state.get("model_info") or self.get_model_info(body, __metadata__, __model__)
        self.capture_tool_calls(trace, state, body)

        assistant_message = get_last_assistant_message(body.get("messages", []))
        usage_details = extract_usage(assistant_message)
        used_skill_names = sorted(state["used_skill_names"])

        generation_metadata = {
            "task": task_name,
            "chat_id": chat_id,
            "configured_skills": model_info.get("configured_skill_ids", []),
            "configured_tools": model_info.get("configured_tool_ids", []),
            "available_skills": state.get("available_skills", []),
            "used_skills": used_skill_names,
            "status_history": safe_json((assistant_message or {}).get("statusHistory")),
            "sources": safe_json((assistant_message or {}).get("sources")),
        }

        generation = trace.start_generation(
            name=f"assistant_response:{task_name}",
            model=model_info.get("base_model_id") or model_info.get("model_id") or "unknown-model",
            input=safe_json(body.get("messages", [])),
            output=safe_json((assistant_message or {}).get("content")),
            metadata=generation_metadata,
        )

        if usage_details:
            generation.update(usage_details=usage_details)

        generation.end()

        trace_metadata = {
            **safe_json(state.get("trace_metadata") or {}),
            "used_skills": used_skill_names,
        }
        trace.update_trace(
            output=self.maybe_full_output(body),
            metadata=trace_metadata,
            tags=self.build_trace_tags(task_name, model_info, used_skill_names),
        )
        trace.end()
        state["trace_metadata"] = trace_metadata

        self.langfuse.flush()
        self.chat_state.pop(state_key, None)
        return body


Pipeline.Valves.model_rebuild()
