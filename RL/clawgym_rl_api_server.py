import asyncio
import json
import logging
import math
import os
import queue
import threading
import time
from itertools import count
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from slime.utils.processing_utils import load_tokenizer
from slime.utils.types import Sample

logger = logging.getLogger(__name__)

_NON_STANDARD_BODY_KEYS: set[str] = set()


def _require_dict(value, field_name: str) -> dict:
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be a dict")
    return value


def _require_list(value, field_name: str) -> list:
    if not isinstance(value, list):
        raise TypeError(f"{field_name} must be a list")
    return value


def _require_string(value, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    return value


def _require_bool(value, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be a bool")
    return value


def _parse_request_model(value) -> tuple[str, str]:
    model_value = _require_string(value, "model")
    parts = model_value.split("__", 1)
    if len(parts) != 2:
        raise TypeError("model must be '<turn_type>__<session_id>'")
    turn_type = _require_string(parts[0], "turn_type").strip().lower()
    session_id = _require_string(parts[1], "session_id")
    return turn_type, session_id


def _flatten_message_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and "type" in item and item["type"] == "text" and "text" in item:
                parts.append(str(item["text"]))
        return " ".join(parts)
    if content is None:
        return ""
    return str(content)


def _normalize_messages_for_template(messages: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    for message in messages:
        item = dict(message)
        if "role" in item and item["role"] == "developer":
            item["role"] = "system"
        if "content" in item and not isinstance(item["content"], str):
            item["content"] = _flatten_message_content(item["content"])
        # Parse tool_calls arguments from JSON string to dict to match SGLang behavior.
        # SGLang does json.loads on arguments before passing to apply_chat_template,
        # which changes formatting (e.g. adds spaces after colons). We must do the same
        # to keep training tokens consistent with inference tokens.
        if "tool_calls" in item and isinstance(item["tool_calls"], list):
            new_tool_calls = []
            for tc in item["tool_calls"]:
                tc = dict(tc)
                if "function" in tc and isinstance(tc["function"], dict):
                    tc["function"] = dict(tc["function"])
                    args = tc["function"].get("arguments")
                    if isinstance(args, str):
                        try:
                            tc["function"]["arguments"] = json.loads(args)
                        except (json.JSONDecodeError, ValueError):
                            pass
                new_tool_calls.append(tc)
            item["tool_calls"] = new_tool_calls
        normalized.append(item)
    return normalized


def _extract_logprobs_from_chat_response(choice: dict[str, Any]) -> list[float]:
    if "logprobs" not in choice:
        return []
    logprobs_obj = choice["logprobs"]
    if not isinstance(logprobs_obj, dict) or "content" not in logprobs_obj:
        return []
    content = logprobs_obj["content"]
    if not isinstance(content, list):
        return []
    values: list[float] = []
    for item in content:
        if isinstance(item, dict) and "logprob" in item:
            values.append(float(item["logprob"]))
    return values


def _extract_generate_output_logprobs(output: dict[str, Any]) -> tuple[list[int], list[float]]:
    meta_info = _require_dict(output["meta_info"], "meta_info")
    pairs = _require_list(meta_info["output_token_logprobs"], "meta_info.output_token_logprobs")
    token_ids: list[int] = []
    logprobs: list[float] = []
    for pair in pairs:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            raise TypeError("output_token_logprobs items must be [logprob, token_id]")
        logprobs.append(float(pair[0]))
        token_ids.append(int(pair[1]))
    return token_ids, logprobs


def _reward_score(sample: Sample) -> float:
    reward = _require_dict(sample.reward, "sample.reward")
    return float(reward["score"])


async def reward_func(args, sample_or_samples, **kwargs):
    if isinstance(sample_or_samples, list):
        rewards = []
        for sample in sample_or_samples:
            rewards.append({"score": _reward_score(sample)})
        return rewards

    sample = sample_or_samples
    return {"score": _reward_score(sample)}


async def generate(args, sample: Sample, sampling_params, evaluation: bool = False) -> Sample:
    tokenizer = load_tokenizer(args.hf_checkpoint, trust_remote_code=True)
    if isinstance(sample.prompt, list):
        messages = sample.prompt
    else:
        messages = [{"role": "user", "content": str(sample.prompt)}]

    input_ids = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True)
    payload = {
        "input_ids": input_ids,
        "sampling_params": sampling_params,
        "return_logprob": True,
    }
    url = f"http://{args.sglang_router_ip}:{args.sglang_router_port}/generate"
    async with httpx.AsyncClient(timeout=None) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        output = response.json()

    text = str(output["text"])
    token_ids, logprobs = _extract_generate_output_logprobs(output)

    sample.tokens = input_ids + token_ids
    sample.response = text
    sample.response_length = len(token_ids)
    sample.rollout_log_probs = logprobs
    sample.loss_mask = [1] * len(token_ids)
    sample.status = Sample.Status.COMPLETED
    return sample


class ClawGymRLAPIServer:
    def __init__(self, args, output_queue: queue.Queue, submission_enabled: threading.Event):
        self.args = args
        self.output_queue = output_queue
        self.submission_enabled = submission_enabled
        self.tokenizer = load_tokenizer(args.hf_checkpoint, trust_remote_code=True)
        self.sglang_chat_url = f"http://{args.sglang_router_ip}:{args.sglang_router_port}/v1/chat/completions"
        self.sglang_health_url = f"http://{args.sglang_router_ip}:{args.sglang_router_port}/health"
        self.expected_api_key = os.getenv("SGLANG_API_KEY", "")
        self.host = os.getenv("HOST", "0.0.0.0")
        self.port = int(os.getenv("PORT", "30000"))
        self.served_model_name = os.getenv("SERVED_MODEL_NAME", "qwen3-4b")
        self._record_file = ""
        if os.getenv("OPENCLAW_RECORD_ENABLED", "0") == "1":
            self._record_file = os.environ["OPENCLAW_RECORD_FILE"]

        self._index_counter = count(0)
        self._group_counter = count(0)
        self._step_counts: dict[str, int] = {}
        self._pending_step_data: dict[str, dict[int, dict[str, Any]]] = {}
        self._pending_records: dict[str, dict[str, Any]] = {}
        self._conversation_logs: dict[str, list[dict[str, Any]]] = {}
        self._session_raw_prompts: dict[str, dict[str, str]] = {}
        self._eval_scores: list[float] = []
        self._eval_scores_lock = threading.Lock()
        self._sglang_ready = threading.Event()
        self._full_prompt_logged = False

        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self.app = self._build_app()

        if self._record_file:
            os.makedirs(os.path.dirname(self._record_file), exist_ok=True)
            open(self._record_file, "w").close()

    def _build_app(self) -> FastAPI:
        app = FastAPI(title="ClawGym-RL Proxy")
        app.state.owner = self

        @app.get("/healthz")
        async def healthz():
            return {"ok": True}

        @app.post("/reset_sessions")
        async def reset_sessions(request: Request):
            owner: ClawGymRLAPIServer = request.app.state.owner
            owner._step_counts.clear()
            owner._pending_step_data.clear()
            owner._pending_records.clear()
            owner._conversation_logs.clear()
            owner._session_raw_prompts.clear()
            return {"ok": True}

        @app.post("/get_conversation_log")
        async def get_conversation_log(request: Request):
            owner: ClawGymRLAPIServer = request.app.state.owner
            body = await request.json()
            target_sid = _require_string(body["session_id"], "session_id")
            if target_sid not in owner._conversation_logs:
                raise HTTPException(status_code=404, detail=f"conversation log not found: {target_sid}")
            steps = owner._conversation_logs.pop(target_sid)
            raw_prompts = owner._session_raw_prompts.pop(target_sid, {})
            return {"ok": True, "session_id": target_sid, "steps": steps, "raw_prompts": raw_prompts}

        @app.post("/set_reward")
        async def set_reward(request: Request):
            owner: ClawGymRLAPIServer = request.app.state.owner
            body = await request.json()
            reward_value = float(body["reward"])
            # Sanitize NaN/Inf reward (e.g. reward.sh divide-by-zero, math-verify
            # exception in __mul__) so the whole GRPO group's mean/std doesn't
            # become NaN and silently kill that group's gradient.
            if not math.isfinite(reward_value):
                logger.warning(f"non-finite reward {reward_value!r} for session {body.get('session_id')!r}, clamping to 0.0")
                reward_value = 0.0
            target_sid = _require_string(body["session_id"], "session_id")
            group_index_override = int(body["group_index"])

            if target_sid not in owner._pending_step_data:
                raise HTTPException(status_code=404, detail=f"pending session not found: {target_sid}")

            # Clean up step tracking for this session
            if target_sid in owner._step_counts:
                del owner._step_counts[target_sid]
            owner._flush_pending_record(target_sid, None)

            step_details: list[dict[str, Any]] = []
            pending = owner._pending_step_data.pop(target_sid)
            sorted_steps = sorted(pending)

            for step_num in sorted_steps:
                step_data = pending[step_num]
                user_messages = []
                for message in step_data["messages"]:
                    if message["role"] in {"user", "system", "tool"}:
                        user_messages.append({
                            "role": message["role"],
                            "content": _flatten_message_content(message["content"])[:500],
                        })
                step_details.append({
                    "step": step_num,
                    "input": user_messages,
                    "response": step_data["response_text"],
                    "tool_calls": step_data["tool_calls"],
                    "prompt_tokens": len(step_data["prompt_ids"]),
                    "response_tokens": len(step_data["response_ids"]),
                })

            all_tokens: list[int] = []
            all_loss_mask: list[int] = []
            all_logprobs: list[float] = []
            prompt_text = ""
            response_text = ""

            # Context-aware splitting: detect if OpenClaw modified the previous
            # step's output in the next step's input.  If the context changed
            # (e.g. thinking was stripped), flush the current trajectory as a
            # Sample and start a new one with the new prompt.  If unchanged,
            # append response to current trajectory (skip redundant prompt).
            #
            # All split samples from the SAME rollout share one traj_index so
            # slime's --dynamic-history GRPO normalization treats them as one
            # trajectory (one vote per traj in group baseline) instead of N
            # independent samples (which would over-weight long trajs that
            # split into many pieces).
            traj_index = next(owner._index_counter)
            samples_to_submit: list[Sample] = []
            prev_response_text: str | None = None

            for index, step_num in enumerate(sorted_steps):
                step_data = pending[step_num]
                prompt_ids = step_data["prompt_ids"]
                response_ids = step_data["response_ids"]
                response_logprobs = step_data["response_logprobs"]

                if index == 0:
                    # First step: start new trajectory
                    all_tokens.extend(prompt_ids)
                    prompt_text = step_data["prompt_text"]
                else:
                    # Check if previous response is preserved in this step's prompt
                    context_changed = True
                    if prev_response_text:
                        current_prompt = step_data["prompt_text"]
                        if prev_response_text.strip() in current_prompt:
                            context_changed = False

                    if context_changed:
                        # Context was modified — flush current trajectory as a Sample
                        if all_loss_mask:  # has response tokens
                            sample = Sample()
                            sample.prompt = prompt_text
                            sample.response = response_text
                            sample.tokens = list(all_tokens)
                            sample.response_length = len(all_loss_mask)
                            sample.loss_mask = list(all_loss_mask)
                            sample.rollout_log_probs = list(all_logprobs)
                            sample.status = Sample.Status.COMPLETED
                            sample.index = traj_index
                            sample.group_index = group_index_override
                            sample.reward = {"score": reward_value}
                            samples_to_submit.append(sample)

                        # Start new trajectory with new prompt
                        all_tokens = list(prompt_ids)
                        all_loss_mask = []
                        all_logprobs = []
                        prompt_text = step_data["prompt_text"]
                        response_text = ""
                    else:
                        # Context unchanged — skip redundant prompt, add delta only (token-level)
                        # But if accumulated tokens exceed context window, flush and start new sample
                        max_tokens = int(os.environ.get("OPENCLAW_CONTEXT_WINDOW", "65536"))
                        if len(all_tokens) + len(response_ids) > max_tokens:
                            # Flush current sample
                            if all_loss_mask:
                                sample = Sample()
                                sample.prompt = prompt_text
                                sample.response = response_text
                                sample.tokens = list(all_tokens)
                                sample.response_length = len(all_loss_mask)
                                sample.loss_mask = list(all_loss_mask)
                                sample.rollout_log_probs = list(all_logprobs)
                                sample.status = Sample.Status.COMPLETED
                                sample.index = traj_index
                                sample.group_index = group_index_override
                                sample.reward = {"score": reward_value}
                                samples_to_submit.append(sample)
                            # Start new sample with this step's full prompt
                            all_tokens = list(prompt_ids)
                            all_loss_mask = []
                            all_logprobs = []
                            prompt_text = step_data["prompt_text"]
                            response_text = ""
                        else:
                            prev_token_count = len(all_tokens)
                            shared = 0
                            while shared < min(prev_token_count, len(prompt_ids)) and all_tokens[shared] == prompt_ids[shared]:
                                shared += 1
                            delta_ids = prompt_ids[shared:]
                            if delta_ids:
                                all_tokens.extend(delta_ids)
                                all_loss_mask.extend([0] * len(delta_ids))
                                all_logprobs.extend([0.0] * len(delta_ids))

                all_tokens.extend(response_ids)
                all_loss_mask.extend([1] * len(response_ids))
                all_logprobs.extend(response_logprobs)
                response_text += step_data["response_text"]
                prev_response_text = step_data["response_text"]

            # Flush the last trajectory
            max_ctx = int(os.environ.get("OPENCLAW_CONTEXT_WINDOW", "65536"))
            if all_loss_mask:
                if len(all_tokens) <= max_ctx:
                    sample = Sample()
                    sample.prompt = prompt_text
                    sample.response = response_text
                    sample.tokens = list(all_tokens)
                    sample.response_length = len(all_loss_mask)
                    sample.loss_mask = list(all_loss_mask)
                    sample.rollout_log_probs = list(all_logprobs)
                    sample.status = Sample.Status.COMPLETED
                    sample.index = traj_index
                    sample.group_index = group_index_override
                    sample.reward = {"score": reward_value}
                    samples_to_submit.append(sample)
                else:
                    logger.warning(
                        f"[ClawGym-RL] dropping oversized sample: {len(all_tokens)} tokens > {max_ctx}, "
                        f"session={target_sid}, steps={len(sorted_steps)}"
                    )

            # Also filter any mid-trajectory samples that exceeded the limit
            samples_to_submit = [
                s for s in samples_to_submit if len(s.tokens) <= max_ctx
            ]

            for s in samples_to_submit:
                await asyncio.to_thread(owner.output_queue.put, (s.group_index, [s]))

            return {"ok": True, "reward": reward_value, "submitted": len(samples_to_submit), "steps": step_details}

        @app.post("/v1/chat/completions")
        async def chat_completions(
            request: Request,
            authorization: str | None = Header(default=None),
        ):
            owner: ClawGymRLAPIServer = request.app.state.owner
            await owner._check_auth(authorization)
            if not owner.submission_enabled.is_set():
                raise HTTPException(status_code=503, detail="submission paused for weight update")

            body = await request.json()
            turn_type, session_id = _parse_request_model(body["model"])
            stream = _require_bool(body["stream"], "stream")
            result = await owner._handle_request(body, session_id=session_id, turn_type=turn_type)
            if stream:
                return StreamingResponse(owner._stream_response(result), media_type="text/event-stream")
            return JSONResponse(content=result["response"])

        return app

    async def _check_auth(self, authorization: str | None):
        if not self.expected_api_key:
            return
        if authorization is None or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        token = authorization.split(" ", 1)[1].strip()
        if token != self.expected_api_key:
            raise HTTPException(status_code=401, detail="invalid api key")

    def _buffer_record(
        self,
        session_id: str,
        step_num: int,
        messages: list[dict[str, Any]],
        prompt_text: str,
        response_text: str,
        tool_calls: list[dict[str, Any]],
    ):
        if not self._record_file:
            return
        self._pending_records[session_id] = {
            "session_id": session_id,
            "step": step_num,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "messages": messages,
            "prompt_text": prompt_text,
            "response_text": response_text,
            "tool_calls": tool_calls,
        }

    def _flush_pending_record(self, session_id: str, next_state: dict[str, Any] | None):
        if session_id not in self._pending_records:
            return
        record = self._pending_records.pop(session_id)
        record["next_state"] = next_state
        if not self._record_file:
            return
        with open(self._record_file, "a", encoding="utf-8") as file_handle:
            file_handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    async def _handle_request(self, body: dict[str, Any], session_id: str, turn_type: str):
        messages = _require_list(body["messages"], "messages")
        tools = body["tools"] if "tools" in body else None

        # Store raw system/user prompts on the first request per session
        if session_id not in self._session_raw_prompts:
            raw = {}
            for msg in messages:
                role = msg.get("role", "")
                if role == "system":
                    raw["system_prompt"] = _flatten_message_content(msg.get("content", ""))
                elif role == "user" and "user_prompt" not in raw:
                    raw["user_prompt"] = _flatten_message_content(msg.get("content", ""))
            if tools:
                raw["tools"] = json.dumps(tools, ensure_ascii=False)
            self._session_raw_prompts[session_id] = raw

        # Dump the raw prompt on the first session only (full), subsequent sessions only log user prompt
        if session_id not in self._step_counts:
            if not self._full_prompt_logged:
                self._full_prompt_logged = True
                logger.info("[ClawGym-RL] === FULL SYSTEM PROMPT (logged once) ===")
                for i, msg in enumerate(messages):
                    role = msg.get("role", "?")
                    content = msg.get("content", "")
                    preview = content if isinstance(content, str) else str(content)
                    logger.info("[ClawGym-RL]   message[%d] role=%s content=%s", i, role, preview)
                if tools:
                    logger.info("[ClawGym-RL]   tools=%s", json.dumps(tools, ensure_ascii=False))
                logger.info("[ClawGym-RL] === END FULL SYSTEM PROMPT ===")
            else:
                user_content = ""
                for msg in messages:
                    if msg.get("role") == "user":
                        user_content = _flatten_message_content(msg.get("content", ""))[:500]
                        break
                logger.info("[ClawGym-RL] session=%s user_prompt=%s", session_id, user_content)

        forward_body = {key: value for key, value in body.items() if key not in _NON_STANDARD_BODY_KEYS}
        forward_body["stream"] = False
        forward_body["logprobs"] = True
        forward_body["top_logprobs"] = 1
        forward_body.pop("stream_options", None)
        _require_string(forward_body["model"], "model")

        async with httpx.AsyncClient(timeout=None) as client:
            # Retry on 503 (KV cache full) — usually transient, clears in a few seconds
            max_retries = 5
            retry_delay = 2.0
            for attempt in range(max_retries + 1):
                sglang_response = await client.post(self.sglang_chat_url, json=forward_body)
                if sglang_response.status_code != 503 or attempt == max_retries:
                    break
                logger.info("[ClawGym-RL] SGLang 503 for session=%s, retry %d/%d", session_id, attempt + 1, max_retries)
                await asyncio.sleep(retry_delay * (attempt + 1))
            if sglang_response.status_code != 200:
                logger.warning(
                    "[ClawGym-RL] SGLang returned %s for session=%s",
                    sglang_response.status_code, session_id,
                )
                raise HTTPException(
                    status_code=sglang_response.status_code,
                    detail=f"upstream SGLang error: {sglang_response.text[:500]}",
                )
            output = sglang_response.json()

        choice = _require_dict(_require_list(output["choices"], "choices")[0], "choice")
        assistant_msg = _require_dict(choice["message"], "choice.message")
        tool_calls = assistant_msg["tool_calls"]
        if tool_calls is None:
            tool_calls = []
        else:
            tool_calls = _require_list(tool_calls, "choice.message.tool_calls")
            if len(tool_calls) > 1:
                tool_calls = tool_calls[:1]
        content = assistant_msg["content"]
        if content is None:
            content = ""
        else:
            content = _flatten_message_content(content)
        reasoning_content = assistant_msg.get("reasoning_content") or ""
        assistant_msg["tool_calls"] = tool_calls
        assistant_msg["content"] = content

        # Collect only NEW tool observations from this request.
        # OpenClaw sends full history each time, so we only want tool messages
        # that appear after the last assistant message (= results of the previous step's tool calls).
        observations: list[str] = []
        for message in reversed(messages):
            if message["role"] == "tool":
                observations.append(_flatten_message_content(message["content"]))
            elif message["role"] == "assistant":
                break  # Stop at the most recent assistant message; everything before is old history
        observations.reverse()  # Restore original order
        if session_id not in self._conversation_logs:
            self._conversation_logs[session_id] = []

        # Attach observations from this request to the PREVIOUS step (they are the result of that step's tool calls)
        if observations and self._conversation_logs[session_id]:
            prev_step = self._conversation_logs[session_id][-1]
            prev_step["observations"] = observations

        step_record = {
            "step": len(self._conversation_logs[session_id]) + 1,
            "content": content.strip(),
            "reasoning_content": reasoning_content.strip() if reasoning_content else "",
            "tool_calls": [
                {
                    "name": tool_call["function"]["name"],
                    "arguments": tool_call["function"]["arguments"],
                }
                for tool_call in tool_calls
            ],
            "observations": [],
        }
        self._conversation_logs[session_id].append(step_record)

        if turn_type == "main":
            prev_step_num = 0
            if session_id in self._step_counts:
                prev_step_num = self._step_counts[session_id]
            if prev_step_num > 0 and messages:
                self._flush_pending_record(session_id, messages[-1])

            response_msg = dict(assistant_msg)
            normalized_messages = _normalize_messages_for_template(messages)
            normalized_response = _normalize_messages_for_template([response_msg])[0]
            full_normalized = normalized_messages + [normalized_response]

            prompt_text = self.tokenizer.apply_chat_template(
                normalized_messages,
                tools=tools,
                tokenize=False,
                add_generation_prompt=True,
            )
            full_text = self.tokenizer.apply_chat_template(
                full_normalized,
                tools=tools,
                tokenize=False,
                add_generation_prompt=False,
            )
            if not full_text.startswith(prompt_text):
                raise ValueError("chat template output must start with prompt_text")
            response_text = full_text[len(prompt_text):]
            prompt_ids = self.tokenizer(prompt_text, add_special_tokens=False)["input_ids"]
            response_ids = self.tokenizer(response_text, add_special_tokens=False)["input_ids"]

            if not response_ids and not response_text.strip() and not tool_calls:
                output["session_id"] = session_id
                return {"response": output}

            response_logprobs = _extract_logprobs_from_chat_response(choice)
            if len(response_logprobs) > len(response_ids):
                response_logprobs = response_logprobs[: len(response_ids)]
            elif len(response_logprobs) < len(response_ids):
                response_logprobs = response_logprobs + [0.0] * (len(response_ids) - len(response_logprobs))

            step_num = prev_step_num + 1
            self._step_counts[session_id] = step_num
            step_data = {
                "prompt_ids": prompt_ids,
                "response_ids": response_ids,
                "response_logprobs": response_logprobs,
                "prompt_text": prompt_text,
                "response_text": response_text,
                "messages": messages,
                "tool_calls": tool_calls,
            }
            if session_id not in self._pending_step_data:
                self._pending_step_data[session_id] = {}
            self._pending_step_data[session_id][step_num] = step_data
            self._buffer_record(session_id, step_num, messages, prompt_text, response_text, tool_calls)

        output["session_id"] = session_id
        return {"response": output}

    async def _stream_response(self, result: dict[str, Any]):
        payload = result["response"]
        choice = payload["choices"][0]
        message = choice["message"]
        delta = {"role": "assistant", "content": message["content"]}
        if message["tool_calls"]:
            delta["tool_calls"] = message["tool_calls"]

        chunk_base = {
            "id": payload["id"],
            "object": "chat.completion.chunk",
            "created": payload["created"],
            "model": payload["model"],
            "session_id": payload["session_id"],
        }
        first = {**chunk_base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}
        final = {**chunk_base, "choices": [{"index": 0, "delta": {}, "finish_reason": choice["finish_reason"]}]}
        yield f"data: {json.dumps(first, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps(final, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    def drain_eval_scores(self) -> list[float]:
        with self._eval_scores_lock:
            scores = list(self._eval_scores)
            self._eval_scores.clear()
            return scores

    def reset_eval_scores(self):
        with self._eval_scores_lock:
            self._eval_scores.clear()

    def purge_record_files(self):
        if self._record_file:
            open(self._record_file, "w").close()

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._sglang_ready.clear()
        config = uvicorn.Config(self.app, host=self.host, port=self.port, log_level="info")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        readiness_thread = threading.Thread(target=self._wait_for_sglang_ready, daemon=True)
        readiness_thread.start()

    def wait_until_ready(self, timeout: float):
        if not self._sglang_ready.wait(timeout=timeout):
            raise TimeoutError("SGLang chat endpoint did not become ready in time")

    def _wait_for_sglang_ready(self):
        while True:
            try:
                response = httpx.get(
                    self.sglang_health_url,
                    timeout=5,
                )
                if response.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(3)
        self._sglang_ready.set()
        logger.info("[ClawGym-RL] policy server ready")

    def stop(self):
        self._sglang_ready.clear()
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5)