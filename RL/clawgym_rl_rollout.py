import asyncio
import atexit
import json
import os
import queue
import random
import shutil
import socket
import string
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import requests

from clawgym_rl_api_server import ClawGymRLAPIServer
from slime.rollout.base_types import RolloutFnEvalOutput, RolloutFnTrainOutput
from slime.rollout.sglang_rollout import eval_rollout
from slime.utils.async_utils import run
from slime.utils.types import Sample


_CHAT_READY_TIMEOUT_SECONDS = 120
# Per-turn HTTP read timeout for chat/completions. Small models (4B) loop on
# malformed tool-call JSON and can push a single task past 900s; override via
# OPENCLAW_CHAT_TURN_TIMEOUT env so this only bumps for the runs that need it.
_CHAT_TURN_TIMEOUT_SECONDS = int(os.environ.get("OPENCLAW_CHAT_TURN_TIMEOUT", "900"))
_REWARD_TIMEOUT_SECONDS = 120
_CHAT_READY_POLL_SECONDS = 3
_GATEWAY_IMAGE = os.environ.get("OPENCLAW_GATEWAY_IMAGE", "clawgym-rl:v0.1")
_POLICY_READY_TIMEOUT_SECONDS = 600
_GLOBAL_WORKER = None
_GLOBAL_WORKER_LOCK = threading.Lock()
_TOOL_CALL_MARKER: str | None = None

# ── Train rollout metrics (reset each rollout step) ──────────────────────
_TRAIN_METRICS_LOCK = threading.Lock()
_TRAIN_METRICS: dict = {}


def _get_tool_call_marker() -> str:
    """Get the tool-call start token for the configured SGLang parser (cached).

    Different parsers expose it under different attribute names:
      - qwen25 / many others: ``bot_token`` (e.g. ``<tool_call>\\n``)
      - qwen3_coder: ``tool_call_start_token`` (``<tool_call>``); its
        ``bot_token`` is an empty string.
    We probe several attributes and fall back to ``<tool_call>``.
    """
    global _TOOL_CALL_MARKER
    if _TOOL_CALL_MARKER is not None:
        return _TOOL_CALL_MARKER
    parser_name = os.environ.get("TOOL_CALL_PARSER", "qwen25")
    marker = ""
    try:
        from sglang.srt.function_call.function_call_parser import FunctionCallParser
        parser_cls = FunctionCallParser.ToolCallParserEnum.get(parser_name)
        if parser_cls:
            inst = parser_cls()
            for attr in ("tool_call_start_token", "bot_token"):
                val = getattr(inst, attr, "") or ""
                val = val.strip()
                if val:
                    marker = val
                    break
    except Exception:
        marker = ""
    if not marker:
        marker = "<tool_call>"  # safe fallback
    _TOOL_CALL_MARKER = marker
    return _TOOL_CALL_MARKER


@dataclass(frozen=True)
class TaskSpec:
    task_dir: Path
    task_id: str
    user_query: str
    input_mount_dir: str | None
    metadata: dict


@dataclass(frozen=True)
class TaskSource:
    dataset_name: str
    tasks: list[TaskSpec]


@dataclass(frozen=True)
class ContainerRuntime:
    container_name: str
    gateway_url: str
    token: str
    config_dir: Path
    workspace_dir: Path
    session_id: str
    model_id: str
    use_chroot: bool = False
    chroot_rootfs: Path | None = None
    chroot_process: subprocess.Popen | None = field(default=None, hash=False, compare=False)
    chroot_log_path: Path | None = None


@dataclass(frozen=True)
class TaskRunResult:
    reward: float
    final_message: str
    react_steps: list[dict]
    raw_prompts: dict[str, str]


class AsyncRolloutWorker:
    def __init__(self, args, data_buffer):
        self.args = args
        self.data_buffer = data_buffer
        self.running = True
        self.output_queue = queue.Queue(maxsize=100000)
        self.worker_thread = None
        self.submission_enabled = threading.Event()
        self.server = ClawGymRLAPIServer(
            args=args,
            output_queue=self.output_queue,
            submission_enabled=self.submission_enabled,
        )

    async def _worker_loop(self):
        while self.running:
            await asyncio.sleep(1.0)

    def _thread_main(self):
        asyncio.run(self._worker_loop())

    def start(self):
        self.server.start()
        if self.worker_thread is None or not self.worker_thread.is_alive():
            self.worker_thread = threading.Thread(target=self._thread_main, daemon=True)
            self.worker_thread.start()

    def stop(self):
        self.running = False
        self.submission_enabled.clear()
        self.server.stop()
        if self.worker_thread is not None and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=5)

    def pause_submission(self):
        if self.submission_enabled.is_set():
            self.submission_enabled.clear()
            print("[ClawGym-RL] submission paused", flush=True)

    def resume_submission(self):
        if not self.submission_enabled.is_set():
            self.server.wait_until_ready(_POLICY_READY_TIMEOUT_SECONDS)
            self.submission_enabled.set()
            print("[ClawGym-RL] submission resumed", flush=True)

    def get_completed_groups(self) -> list[tuple[int, list[Sample]]]:
        completed: list[tuple[int, list[Sample]]] = []
        while True:
            try:
                completed.append(self.output_queue.get_nowait())
            except queue.Empty:
                break
        return completed

    def get_queue_size(self) -> int:
        return self.output_queue.qsize()


def _random_token(length: int) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(random.choice(alphabet) for _ in range(length))


_GATEWAY_PORT_BASE = 16000
_GATEWAY_PORT_STRIDE = 10
_GATEWAY_PORT_TRAIN_OFFSET = 5000
_GATEWAY_PORT_MAX_SLOTS = 4000  # 4000 slots × 10 stride = 40000 ports (16000-56000)


def _get_rootfs() -> str | None:
    val = os.environ.get("OPENCLAW_ROOTFS", "").strip()
    return val if val else None


def _setup_fake_proc(container_rootfs: Path):
    """Populate a static /proc inside the chroot for tools that need procfs."""
    proc_dir = container_rootfs / "proc"
    proc_dir.mkdir(exist_ok=True)
    for child in proc_dir.iterdir():
        if child.is_dir() and child.name.isdigit():
            shutil.rmtree(child, ignore_errors=True)
    self_dir = proc_dir / "self"
    if self_dir.exists():
        shutil.rmtree(self_dir)
    self_dir.mkdir()
    (self_dir / "status").write_text(
        "Name:\tbash\nState:\tS (sleeping)\nPid:\t1\nPPid:\t0\n"
        "Uid:\t0\t0\t0\t0\nGid:\t0\t0\t0\t0\nThreads:\t1\n"
    )
    (self_dir / "stat").write_text(
        "1 (bash) S 0 0 0 0 -1 0 0 0 0 0 0 0 0 0 20 0 1 0 0 8192000 1024 "
        "18446744073709551615 0 0 0 0 0 0 0 0 0 0 0 0 17 0 0 0 0 0 0\n"
    )
    (self_dir / "comm").write_text("bash\n")
    (self_dir / "cmdline").write_text("\x00")
    (self_dir / "maps").write_text("")
    (self_dir / "environ").write_bytes(
        b"HOME=/root\x00PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\x00"
    )
    (self_dir / "fd").mkdir(exist_ok=True)
    (self_dir / "exe").symlink_to("/bin/bash")
    (self_dir / "cwd").symlink_to("/root/.openclaw/workspace")
    mounts = proc_dir / "mounts"
    if not mounts.exists():
        mounts.write_text(
            "rootfs / rootfs rw 0 0\n"
            "proc /proc proc rw,nosuid,nodev,noexec,relatime 0 0\n"
            "tmpfs /tmp tmpfs rw,nosuid,nodev 0 0\n"
        )


def _gateway_port_for_task(task_index: int, is_train: bool = False) -> int:
    offset = _GATEWAY_PORT_TRAIN_OFFSET if is_train else 0
    slot = task_index % _GATEWAY_PORT_MAX_SLOTS
    return _GATEWAY_PORT_BASE + offset + slot * _GATEWAY_PORT_STRIDE


def _wait_for_port_free(port: int, timeout: float = 30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return
        try:
            subprocess.run(
                f"lsof -ti :{port} | xargs kill -9 2>/dev/null; true",
                shell=True, capture_output=True, timeout=5,
            )
        except Exception:
            pass
        time.sleep(1.0)
    raise TimeoutError(f"Port {port} still occupied after {timeout}s")


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


def _flatten_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and "type" in item and item["type"] == "text" and "text" in item:
                parts.append(_require_string(item["text"], "message content text"))
        return "".join(parts)
    if content is None:
        return ""
    return str(content)


def _task_sources_from_env(env_name: str) -> list[TaskSource]:
    if env_name not in os.environ:
        return []
    raw_value = os.environ[env_name].strip()
    if not raw_value:
        return []
    sources: list[TaskSource] = []
    for raw_path in raw_value.split(","):
        source_path = Path(raw_path.strip())
        if not source_path.exists():
            raise FileNotFoundError(f"task source not found: {source_path}")
        task_entries = _discover_task_entries(source_path)
        tasks = [_load_task_spec(entry_path) for entry_path in task_entries]
        dataset_name = source_path.name
        sources.append(TaskSource(dataset_name=dataset_name, tasks=tasks))
    return sources


def _discover_task_entries(source_path: Path) -> list[Path]:
    if not source_path.is_dir():
        raise ValueError(f"task source must be a dataset directory, got: {source_path}")

    entries: list[Path] = []
    for child in sorted(source_path.iterdir()):
        if not child.is_dir():
            raise ValueError(f"dataset directory must contain only task directories, got file: {child}")
        entry_path = child / "data_entry.json"
        if not entry_path.exists():
            raise ValueError(f"task directory missing data_entry.json: {child}")
        entries.append(entry_path)
    if not entries:
        raise ValueError(f"no task folders with data_entry.json found under: {source_path}")
    return entries


def _load_task_spec(entry_path: Path) -> TaskSpec:
    with entry_path.open(encoding="utf-8") as file_handle:
        entry = _require_dict(json.load(file_handle), str(entry_path))

    task_dir = entry_path.parent
    metadata = _require_dict(entry["metadata"], "metadata")

    input_mount_dir: str | None = None
    if "input_mount_dir" in entry:
        input_mount_dir = _require_string(entry["input_mount_dir"], "input_mount_dir")
        input_files_dir = task_dir / "input_files"
        if not input_files_dir.exists():
            raise FileNotFoundError(f"input_mount_dir is set but input_files/ not found: {input_files_dir}")

    reward_sh = task_dir / "reward" / "reward.sh"
    if not reward_sh.exists():
        raise FileNotFoundError(f"reward/reward.sh not found: {reward_sh}")

    return TaskSpec(
        task_dir=task_dir,
        task_id=_require_string(entry["task_id"], "task_id"),
        user_query=_require_string(entry["user_query"], "user_query"),
        input_mount_dir=input_mount_dir,
        metadata=metadata,
    )


def _container_path_to_host_path(workspace_dir: Path, container_path: str) -> Path:
    container_pure = PurePosixPath(container_path)
    working_pure = PurePosixPath("/root/.openclaw/workspace")
    if not str(container_pure).startswith(str(working_pure)):
        raise ValueError(f"path {container_path} is outside /root/.openclaw/workspace")
    if container_pure == working_pure:
        return workspace_dir
    relative = container_pure.relative_to(working_pure)
    return workspace_dir / Path(str(relative))


def _copy_tree_contents(source_dir: Path, target_dir: Path):
    target_dir.mkdir(parents=True, exist_ok=True)
    for child in source_dir.iterdir():
        destination = target_dir / child.name
        if child.is_dir():
            shutil.copytree(child, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(child, destination)


def _prepare_workspace(task: TaskSpec, workspace_dir: Path):
    workspace_dir.mkdir(parents=True, exist_ok=True)
    if task.input_mount_dir is not None:
        input_dir = _container_path_to_host_path(workspace_dir, task.input_mount_dir)
        input_dir.mkdir(parents=True, exist_ok=True)
        input_files_dir = task.task_dir / "input_files"
        _copy_tree_contents(input_files_dir, input_dir)


def _build_gateway_config(runtime: ContainerRuntime, rl_port: int):
    # Aligned with the reference SFT-data-gen gateway config:
    # - tools.profile = "coding" (was "full"; "full" exposes tools broken in RL chroot)
    # - tools.deny shrunk to web_search/memory_search only
    # - tools.exec kept at host=gateway, security=full (RL agent must run shell)
    # - added: agents.defaults.timeoutSeconds, heartbeat; top-level commands;
    #   session.dmScope; gateway.tailscale; gateway.nodes.denyCommands.
    config = {
        "gateway": {
            "port": int(runtime.gateway_url.rsplit(":", 1)[1]),
            "mode": "local",
            "bind": "loopback",
            "auth": {"mode": "token", "token": runtime.token},
            "http": {"endpoints": {"chatCompletions": {"enabled": True}}},
            "tailscale": {"mode": "off", "resetOnExit": False},
            "nodes": {
                "denyCommands": [
                    "camera.snap", "camera.clip", "screen.record",
                    "contacts.add", "calendar.add", "reminders.add", "sms.send",
                ],
            },
        },
        "models": {
            "mode": "merge",
            "providers": {
                "rl-server": {
                    "baseUrl": f"http://localhost:{rl_port}/v1",
                    "api": "openai-completions",
                    "models": [
                        {
                            "id": runtime.model_id,
                            "name": "RL Model",
                            "reasoning": False,
                            "input": ["text"],
                            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                            "contextWindow": int(os.environ.get("OPENCLAW_CONTEXT_WINDOW", "128000")),
                            "maxTokens": int(os.environ.get("OPENCLAW_MAX_TOKENS", "8192")),
                        }
                    ],
                }
            },
        },
        "agents": {
            "defaults": {
                "model": {"primary": f"rl-server/{runtime.model_id}"},
                "workspace": "/root/.openclaw/workspace",
                "maxConcurrent": 4,
                "subagents": {"maxConcurrent": 4},
                "timeoutSeconds": 1000,
                "llm": {"idleTimeoutSeconds": 0},
                "heartbeat": {"every": "3680000m"},
            }
        },
        "tools": {
            "profile": "coding",
            "deny": ["web_search", "memory_search"],
            "exec": {"host": "gateway", "security": "full"},
        },
        "commands": {
            "native": "auto",
            "nativeSkills": "auto",
            "restart": True,
            "ownerDisplay": "raw",
        },
        "session": {"dmScope": "per-channel-peer"},
    }
    with (runtime.config_dir / "openclaw.json").open("w", encoding="utf-8") as file_handle:
        json.dump(config, file_handle)


def _start_container(task: TaskSpec, rollout_id: int, task_index: int, rl_port: int, session_id: str, model_id: str, is_train: bool = False) -> ContainerRuntime:
    gateway_port = _gateway_port_for_task(task_index, is_train=is_train)
    token = _random_token(32)
    config_dir = Path(f"/tmp/clawgym-rl-{rollout_id}-{task_index}")
    workspace_dir = config_dir / "workspace"
    shutil.rmtree(config_dir, ignore_errors=True)
    workspace_dir.mkdir(parents=True, exist_ok=True)

    rootfs = _get_rootfs()
    use_chroot = rootfs is not None

    runtime = ContainerRuntime(
        container_name=f"clawgym-rl-{rollout_id}-{task_index}",
        gateway_url=f"http://127.0.0.1:{gateway_port}",
        token=token,
        config_dir=config_dir,
        workspace_dir=workspace_dir,
        session_id=session_id,
        model_id=model_id,
        use_chroot=use_chroot,
    )
    _prepare_workspace(task, workspace_dir)
    _build_gateway_config(runtime, rl_port)

    subprocess.run(["chmod", "-R", "777", str(config_dir)], check=True)
    _wait_for_port_free(gateway_port)

    if use_chroot:
        container_rootfs = config_dir / "rootfs"
        log_path = config_dir / "gateway.log"

        subprocess.run(
            ["cp", "-al", rootfs, str(container_rootfs)],
            check=True, capture_output=True, text=True,
        )
        for writable in ("tmp", "var/tmp", "var/log", "var/cache", "root", "run"):
            p = container_rootfs / writable
            if p.exists():
                shutil.rmtree(p)
            p.mkdir(parents=True, exist_ok=True)
        for apt_dir in ("var/cache/apt/archives/partial", "var/lib/apt/lists/partial"):
            (container_rootfs / apt_dir).mkdir(parents=True, exist_ok=True)
        for mutable_dir in (
            "var/lib/dpkg", "var/lib/apt",
            "usr/local/lib/python3.11/dist-packages", "usr/local/bin", "etc",
        ):
            p = container_rootfs / mutable_dir
            if p.is_dir():
                tmp = p.with_name(p.name + ".tmp")
                shutil.copytree(p, tmp, symlinks=True)
                shutil.rmtree(p)
                tmp.rename(p)
        etc_hosts = container_rootfs / "etc" / "hosts"
        if not etc_hosts.exists():
            etc_hosts.write_text("127.0.0.1 localhost\n::1 localhost\n")

        oc_home = container_rootfs / "root" / ".openclaw"
        oc_home.mkdir(parents=True, exist_ok=True)
        for f in config_dir.iterdir():
            if f.is_file():
                shutil.copy2(f, oc_home / f.name)

        oc_workspace = oc_home / "workspace"
        if oc_workspace.exists():
            shutil.rmtree(oc_workspace)
        shutil.copytree(workspace_dir, oc_workspace, dirs_exist_ok=True)
        object.__setattr__(runtime, "workspace_dir", oc_workspace)

        # Create /workspace symlink for backward compatibility
        legacy_workspace = container_rootfs / "workspace"
        if legacy_workspace.exists() and not legacy_workspace.is_symlink():
            shutil.rmtree(legacy_workspace)
        if not legacy_workspace.exists():
            legacy_workspace.symlink_to("/root/.openclaw/workspace")

        _setup_fake_proc(container_rootfs)

        log_file = open(log_path, "w")
        proc = subprocess.Popen(
            [
                "unshare", "--user", "--map-root-user", "--",
                "chroot", str(container_rootfs),
                "/bin/bash", "-c",
                f"export HOME=/root "
                f"PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin "
                f"OPENCLAW_GATEWAY_TOKEN={token} "
                f"LC_ALL=C.UTF-8; "
                f"cd /app && exec node dist/index.js gateway "
                f"--bind loopback --port {gateway_port} --token {token}",
            ],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        object.__setattr__(runtime, "chroot_rootfs", container_rootfs)
        object.__setattr__(runtime, "chroot_process", proc)
        object.__setattr__(runtime, "chroot_log_path", log_path)
    else:
        subprocess.run(["docker", "rm", "-f", runtime.container_name], capture_output=True, text=True)
        subprocess.run(
            [
                "docker", "run", "-d",
                "--name", runtime.container_name,
                "--network", "host",
                "--user", "root",
                "-e", f"OPENCLAW_GATEWAY_TOKEN={runtime.token}",
                "-e", "HOME=/root",
                "-v", f"{runtime.config_dir}:/root/.openclaw",
                "-v", f"{runtime.workspace_dir}:/root/.openclaw/workspace",
                _GATEWAY_IMAGE,
                "node", "dist/index.js", "gateway",
                "--bind", "loopback",
                "--port", str(gateway_port),
                "--token", runtime.token,
            ],
            check=True, capture_output=True, text=True,
        )
    return runtime


def _stop_container(runtime: ContainerRuntime, log_dir: Path | None):
    if runtime.use_chroot:
        proc = runtime.chroot_process
        if proc and proc.poll() is None:
            # NOTE: inside `unshare --user`, node becomes PID 1 of the user
            # namespace and the kernel ignores SIGTERM to PID-1-in-ns (no
            # default handler). Go straight to SIGKILL on the whole process
            # group; otherwise we wait 10s each rollout and accumulate
            # zombies when training dies before proc.wait() completes.
            try:
                subprocess.run(["kill", "-9", "--", f"-{proc.pid}"], capture_output=True, timeout=5)
                proc.wait(timeout=5)
            except Exception:
                pass
        # Reap defunct child to prevent zombie accumulation
        if proc is not None:
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
        # Fallback: pkill any leftover gateway procs identified by our config_dir path
        # (covers the case where the chroot parent died without reaping its children).
        try:
            subprocess.run(
                ["pkill", "-9", "-f", str(runtime.config_dir)],
                capture_output=True, timeout=5,
            )
        except Exception:
            pass
        if log_dir and runtime.chroot_log_path and runtime.chroot_log_path.exists():
            log_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(runtime.chroot_log_path, log_dir / f"{runtime.container_name}.log")
    else:
        if log_dir is not None:
            log_dir.mkdir(parents=True, exist_ok=True)
            logs_result = subprocess.run(
                ["docker", "logs", runtime.container_name],
                capture_output=True,
                text=True,
            )
            with (log_dir / f"{runtime.container_name}.log").open("w", encoding="utf-8") as file_handle:
                if logs_result.stdout:
                    file_handle.write(logs_result.stdout)
                if logs_result.stderr:
                    file_handle.write("\n--- STDERR ---\n")
                    file_handle.write(logs_result.stderr)
        subprocess.run(["docker", "rm", "-f", runtime.container_name], capture_output=True, text=True)
    shutil.rmtree(runtime.config_dir, ignore_errors=True)


def _wait_for_chat_ready(runtime: ContainerRuntime):
    deadline = time.time() + _CHAT_READY_TIMEOUT_SECONDS
    last_error = "no response"
    while time.time() < deadline:
        try:
            response = requests.get(
                f"{runtime.gateway_url}/health",
                timeout=3,
            )
            if response.status_code == 200:
                return
            last_error = f"health status={response.status_code}"
        except requests.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        time.sleep(_CHAT_READY_POLL_SECONDS)
    raise TimeoutError(f"OpenClaw chat endpoint not ready for {runtime.container_name}: {last_error}")


def _post_chat_turn(runtime: ContainerRuntime, turn_type: str, session_done: bool, messages: list[dict]) -> dict:
    response = requests.post(
        f"{runtime.gateway_url}/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {runtime.token}",
            "Content-Type": "application/json",
            "X-OpenClaw-Scopes": "operator.admin,operator.read,operator.write",
        },
        json={
            "model": "openclaw",
            "stream": False,
            "messages": messages,
        },
        timeout=_CHAT_TURN_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return _require_dict(response.json(), "chat response")


def _extract_final_message(chat_response: dict) -> str:
    choices = _require_list(chat_response["choices"], "chat response choices")
    if not choices:
        raise ValueError("chat response choices must not be empty")
    choice = _require_dict(choices[0], "chat response choice")
    message = _require_dict(choice["message"], "chat response message")
    return _flatten_content(message["content"]).strip()


def _run_turns(runtime: ContainerRuntime, task: TaskSpec, max_turns: int, turn_type: str) -> str:
    messages = [{"role": "user", "content": task.user_query}]
    final_message = ""
    for turn_index in range(max_turns):
        session_done = turn_index == max_turns - 1
        chat_response = _post_chat_turn(runtime, turn_type=turn_type, session_done=session_done, messages=messages)
        final_message = _extract_final_message(chat_response)
        if session_done:
            break
        messages = [{"role": "user", "content": "Continue working on the task."}]
    return final_message


def _fetch_react_steps(rl_port: int, session_id: str) -> tuple[list[dict], dict[str, str]]:
    response = requests.post(
        f"http://127.0.0.1:{rl_port}/get_conversation_log",
        json={"session_id": session_id},
        timeout=10,
    )
    response.raise_for_status()
    payload = _require_dict(response.json(), "conversation log response")
    steps = _require_list(payload["steps"], "conversation log steps")
    raw_prompts = payload.get("raw_prompts", {})
    return steps, raw_prompts


def _read_container_text_file(runtime: ContainerRuntime, container_path: str) -> str:
    target_path = runtime.config_dir / ".copied_output.txt"
    if target_path.exists():
        target_path.unlink()
    copy_result = subprocess.run(
        ["docker", "cp", f"{runtime.container_name}:{container_path}", str(target_path)],
        capture_output=True,
        text=True,
    )
    if copy_result.returncode != 0:
        return ""
    if not target_path.exists():
        return ""
    return target_path.read_text(encoding="utf-8").strip()


def _copy_reward_assets_to_container(task: TaskSpec, runtime: ContainerRuntime) -> str:
    source_path = task.task_dir / "reward"
    if runtime.use_chroot:
        reward_dst = runtime.workspace_dir / "reward"
        if reward_dst.exists():
            shutil.rmtree(reward_dst)
        shutil.copytree(source_path, reward_dst)
    else:
        subprocess.run(
            ["docker", "cp", str(source_path), f"{runtime.container_name}:/root/.openclaw/workspace"],
            check=True, capture_output=True, text=True,
        )
    return "/root/.openclaw/workspace/reward/reward.sh"


def _read_session_transcript(runtime: ContainerRuntime) -> list[dict]:
    """Read the OpenClaw agent session JSONL from inside the container."""
    if runtime.use_chroot:
        sessions_dir = runtime.chroot_rootfs / "root" / ".openclaw" / "agents" / "main" / "sessions"
    else:
        tmp_sessions = runtime.config_dir / ".sessions_copy"
        result = subprocess.run(
            ["docker", "cp",
             f"{runtime.container_name}:/root/.openclaw/agents/main/sessions",
             str(tmp_sessions)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return []
        sessions_dir = tmp_sessions

    if not sessions_dir.is_dir():
        return []

    transcript = []
    for jsonl_file in sorted(sessions_dir.glob("*.jsonl")):
        for line in jsonl_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    transcript.append(json.loads(line))
                except json.JSONDecodeError:
                    pass  # skip truncated/corrupt lines
    return transcript


def _write_reward_payload(
    task: TaskSpec,
    runtime: ContainerRuntime,
    final_message: str,
) -> str:
    transcript = _read_session_transcript(runtime)
    payload = {
        "final_message": final_message,
        "metadata": task.metadata,
        "transcript": transcript,
    }
    payload_path = runtime.workspace_dir / ".openclaw_reward_payload.json"
    with payload_path.open("w", encoding="utf-8") as file_handle:
        json.dump(payload, file_handle)
    return str(PurePosixPath("/root/.openclaw/workspace/.openclaw_reward_payload.json"))


def _reward_exec_command(container_script_path: str) -> list[str]:
    return ["bash", container_script_path]


def _parse_reward_stdout(stdout: str) -> float:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines:
        print("[ClawGym-RL] WARNING: reward script produced no stdout, treating as 0.0", flush=True)
        return 0.0
    try:
        return float(lines[-1])
    except ValueError:
        print(f"[ClawGym-RL] WARNING: reward script output not a number: {lines[-1]!r}, treating as 0.0", flush=True)
        return 0.0


def _run_reward(
    task: TaskSpec,
    runtime: ContainerRuntime,
    final_message: str,
) -> float:
    container_reward_path = _copy_reward_assets_to_container(task, runtime)
    container_payload_path = _write_reward_payload(task, runtime, final_message)

    if runtime.use_chroot:
        result = subprocess.run(
            [
                "unshare", "--user", "--map-root-user", "--",
                "chroot", str(runtime.chroot_rootfs),
                "bash", "-c",
                f"export OPENCLAW_REWARD_PAYLOAD={container_payload_path} "
                f"PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin "
                f"HOME=/root LC_ALL=C.UTF-8; "
                f"bash {container_reward_path}",
            ],
            capture_output=True, text=True, timeout=_REWARD_TIMEOUT_SECONDS,
        )
    else:
        result = subprocess.run(
            [
                "docker", "exec", "--user", "root",
                "-e", f"OPENCLAW_REWARD_PAYLOAD={container_payload_path}",
                runtime.container_name,
            ] + _reward_exec_command(container_reward_path),
            capture_output=True, text=True, timeout=_REWARD_TIMEOUT_SECONDS,
        )

    if result.returncode != 0:
        stderr_preview = (result.stderr or "").strip()[:500]
        print(
            f"[ClawGym-RL] reward.sh failed for {task.task_id} "
            f"(exit={result.returncode}): {stderr_preview}",
            flush=True,
        )
        return 0.0
    return _parse_reward_stdout(result.stdout)


def _submit_reward(rl_port: int, session_id: str, reward: float, group_index: int):
    # Retry transient network/server errors so a single blip doesn't drop the
    # sample from the GRPO group.  3 attempts, exponential backoff.
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.post(
                f"http://127.0.0.1:{rl_port}/set_reward",
                json={"session_id": session_id, "reward": reward, "group_index": group_index},
                timeout=5,
            )
            response.raise_for_status()
            return
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.HTTPError) as exc:
            last_exc = exc
            if attempt < 2:
                time.sleep(0.5 * (2 ** attempt))  # 0.5s, 1s
    assert last_exc is not None
    raise last_exc


def _build_log_lines(
    mode_label: str,
    task: TaskSpec,
    result: TaskRunResult,
    group_index: int | None,
) -> list[str]:
    lines = [f"=== {mode_label} Task {task.task_id} ==="]
    if group_index is not None:
        lines.append(f"Group Index: {group_index}")
    lines.append(f"Reward: {result.reward:.6f}")
    lines.append(f"User Query (from raw data): {task.user_query}")
    # lines.append(f"Final Message: {result.final_message}")
    lines.append("")
    if result.raw_prompts:
        if "system_prompt" in result.raw_prompts:
            first_line = result.raw_prompts["system_prompt"].split("\n", 1)[0]
            lines.append(f"System Prompt: {first_line} [truncated, see main log for full]")
        if "user_prompt" in result.raw_prompts:
            lines.append(f"User Prompt (from OpenClaw): {result.raw_prompts['user_prompt']}")
        lines.append("")
    lines.append(f"Steps: {len(result.react_steps)}")
    lines.append("")
    for step in result.react_steps:
        step_number = step["step"]
        lines.append(f"--- Step {step_number} ---")
        if step.get("reasoning_content"):
            lines.append(f"REASONING_CONTENT: {step['reasoning_content']}")
        lines.append(f"Content: {step['content']}")
        tool_calls = step["tool_calls"]
        observations = step["observations"]

        if tool_calls:
            for tool_call in tool_calls:
                tool_name = tool_call["name"]
                tool_arguments = tool_call["arguments"]
                lines.append(f"ACTION: {tool_name} {tool_arguments}")
        else:
            lines.append("ACTION: [none]")

        if observations:
            for observation in observations:
                lines.append(f"OBSERVATION: {observation}")
        else:
            lines.append("OBSERVATION: [none]")
        lines.append("")
    return lines


def _log_root(args, rollout_id: int) -> Path | None:
    if args.save:
        return Path(args.save) / "openclaw_logs" / f"rollout_{rollout_id}"
    if "SAVE_CKPT" in os.environ and os.environ["SAVE_CKPT"]:
        return Path(os.environ["SAVE_CKPT"]) / "openclaw_logs" / f"rollout_{rollout_id}"
    return None


def _write_instance_log(
    args,
    rollout_id: int,
    file_name: str,
    mode_label: str,
    task: TaskSpec,
    result: TaskRunResult,
    group_index: int | None,
):
    log_dir = _log_root(args, rollout_id)
    if log_dir is None:
        return
    log_dir.mkdir(parents=True, exist_ok=True)
    log_lines = _build_log_lines(mode_label, task, result, group_index)
    with (log_dir / file_name).open("w", encoding="utf-8") as file_handle:
        file_handle.write("\n".join(log_lines) + "\n")


def _run_single_task(
    args,
    task: TaskSpec,
    rollout_id: int,
    task_index: int,
    turn_type: str,
    max_turns: int,
    rl_port: int,
    group_index: int | None,
    log_prefix: str,
) -> TaskRunResult:
    task_start_time = time.time()
    session_id = f"task-{rollout_id}-{task_index}"
    runtime = _start_container(task, rollout_id, task_index, rl_port, session_id, f"{turn_type}__{session_id}", is_train=(turn_type == "main"))
    log_dir = _log_root(args, rollout_id)
    try:
        _wait_for_chat_ready(runtime)
        final_message = _run_turns(runtime, task, max_turns=max_turns, turn_type=turn_type)
        react_steps, raw_prompts = _fetch_react_steps(rl_port, session_id)
        reward = _run_reward(task, runtime, final_message)

        # Format penalty: if any step's content contains the tool call bot_token,
        # it means the model tried to make a tool call but SGLang failed to parse it.
        # We detect this by checking for the bot_token of the configured parser.
        #
        # Default DISABLED: previous runs shipped with a broken marker detector
        # (qwen3_coder's bot_token=''), so no penalty ever fired. Analysis showed
        # the fixed version mostly punishes successful trajectories with a trailing
        # `<tool_call>` sentinel (reward>0 → 0), which GRPO already handles via
        # group normalization. Set OPENCLAW_FORMAT_PENALTY=1 to opt in.
        _tool_call_marker = _get_tool_call_marker() if os.environ.get("OPENCLAW_FORMAT_PENALTY", "0") == "1" else ""
        if _tool_call_marker:
            for step in react_steps:
                if _tool_call_marker in step.get("content", ""):
                    print(
                        f"[ClawGym-RL] {log_prefix} {task.task_id}: format penalty "
                        f"(step {step.get('step')}: unparsed tool_call in content), reward {reward:.4f} → 0.0",
                        flush=True,
                    )
                    if log_prefix == "train":
                        with _TRAIN_METRICS_LOCK:
                            _TRAIN_METRICS["format_penalty"] = _TRAIN_METRICS.get("format_penalty", 0) + 1
                            if reward > 0:
                                _TRAIN_METRICS["format_penalty_nonzero_to_zero"] = _TRAIN_METRICS.get("format_penalty_nonzero_to_zero", 0) + 1
                    reward = 0.0
                    break

        if group_index is not None:
            _submit_reward(rl_port, session_id, reward, group_index)

        # Track per-trajectory metrics for wandb
        if log_prefix == "train":
            duration = time.time() - task_start_time
            with _TRAIN_METRICS_LOCK:
                m = _TRAIN_METRICS
                m["submitted"] = m.get("submitted", 0) + 1
                m.setdefault("rewards", []).append(reward)
                m["steps_total"] = m.get("steps_total", 0) + len(react_steps)
                m.setdefault("durations", []).append(duration)

        result = TaskRunResult(
            reward=reward,
            final_message=final_message,
            react_steps=react_steps,
            raw_prompts=raw_prompts,
        )
        _write_instance_log(
            args,
            rollout_id,
            f"instance-{log_prefix}-{task_index}.log",
            log_prefix.upper(),
            task,
            result,
            group_index,
        )
        return result
    finally:
        _stop_container(runtime, log_dir)


def _train_batch(args, tasks: list[TaskSpec], rollout_id: int) -> list[tuple[int, TaskSpec]]:
    """Compute the (group_index, task) batch for this rollout.

    Cursor is derived deterministically from rollout_id so that resume picks up
    where we left off (instead of restarting from task 0). This requires
    rollout_batch_size to stay constant across resume.
    """
    n_prompts = int(args.rollout_batch_size)
    n_samples = int(args.n_samples_per_prompt)
    n_tasks = len(tasks)
    base_seed = int(os.environ.get("OPENCLAW_TRAIN_SHUFFLE_SEED", "0"))
    batch: list[tuple[int, TaskSpec]] = []
    cursor = rollout_id * n_prompts
    for prompt_offset in range(n_prompts):
        global_idx = cursor + prompt_offset
        epoch, pos = divmod(global_idx, n_tasks)
        rng = random.Random(base_seed + epoch)
        perm = list(range(n_tasks))
        rng.shuffle(perm)
        task = tasks[perm[pos]]
        for _ in range(n_samples):
            batch.append((prompt_offset, task))
    return batch


def _run_openclaw_eval(args, rollout_id: int) -> dict[str, dict] | None:
    sources = _task_sources_from_env("OPENCLAW_EVAL_TASKS")
    if not sources:
        print("[ClawGym-RL] OPENCLAW_EVAL_TASKS not set, skipping eval", flush=True)
        return None

    if "PORT" not in os.environ or not os.environ["PORT"]:
        raise ValueError("PORT must be set for OpenClaw eval")
    rl_port = int(os.environ["PORT"])
    max_turns = int(os.environ["OPENCLAW_EVAL_MAX_TURNS"]) if "OPENCLAW_EVAL_MAX_TURNS" in os.environ else 1
    requested_workers = int(os.environ["OPENCLAW_EVAL_NUM_WORKERS"]) if "OPENCLAW_EVAL_NUM_WORKERS" in os.environ else 32
    n_eval_samples = int(os.environ.get("OPENCLAW_EVAL_N_SAMPLES", "1"))

    all_results: dict[str, dict] = {}
    for source in sources:
        n_tasks = len(source.tasks)
        n_total = n_tasks * n_eval_samples
        rewards = [0.0] * n_total
        worker_count = min(requested_workers, n_total)
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_to_index = {}
            for sample_idx in range(n_eval_samples):
                for task_index, task in enumerate(source.tasks):
                    flat_index = sample_idx * n_tasks + task_index
                    future = executor.submit(
                        _run_single_task,
                        args,
                        task,
                        rollout_id,
                        flat_index,
                        "side",
                        max_turns,
                        rl_port,
                        None,
                        "eval",
                    )
                    future_to_index[future] = (flat_index, task_index)

            n_skipped = 0
            for future in as_completed(future_to_index):
                flat_index, task_index = future_to_index[future]
                try:
                    result = future.result()
                    rewards[flat_index] = result.reward
                    print(
                        f"[ClawGym-RL] eval task {source.tasks[task_index].task_id}: reward={result.reward:.4f}",
                        flush=True,
                    )
                except (TimeoutError, requests.exceptions.HTTPError, requests.exceptions.ConnectionError, OSError, subprocess.CalledProcessError) as exc:
                    print(
                        f"[ClawGym-RL] eval task {source.tasks[task_index].task_id}: SKIPPED (env error: {type(exc).__name__}: {exc})",
                        flush=True,
                    )
                    rewards[flat_index] = 0.0
                    n_skipped += 1

        # Average rewards per task across n_eval_samples
        task_rewards = []
        for task_index in range(n_tasks):
            task_samples = [rewards[s * n_tasks + task_index] for s in range(n_eval_samples)]
            task_rewards.append(sum(task_samples) / len(task_samples))

        n_total_runs = n_tasks * n_eval_samples
        n_collected = n_total_runs - n_skipped
        average_reward = sum(task_rewards) / n_tasks
        avg_reward_collected_only = sum(rewards) / n_collected if n_collected > 0 else 0.0
        correct_count = sum(1 for r in task_rewards if r > 0.5)
        print(
            (
                f"[ClawGym-RL] eval dataset {source.dataset_name}: "
                f"{correct_count}/{n_tasks} correct, avg={average_reward:.4f}, "
                f"collected={n_collected}/{n_total_runs}, avg_collected_only={avg_reward_collected_only:.4f}"
                + (f", n_samples={n_eval_samples}" if n_eval_samples > 1 else "")
            ),
            flush=True,
        )
        all_results[source.dataset_name] = {
            "rewards": task_rewards,
            "n_collected": n_collected,
            "n_skipped": n_skipped,
            "avg_reward_collected_only": avg_reward_collected_only,
        }

    return all_results


def _build_eval_metrics(result: dict) -> dict | None:
    """Build wandb-ready eval metrics from _run_openclaw_eval result."""
    eval_metrics = {}
    for ds_name, ds_data in result.items():
        if "n_collected" in ds_data:
            eval_metrics[f"eval/{ds_name}-n_collected"] = ds_data["n_collected"]
            eval_metrics[f"eval/{ds_name}-n_skipped"] = ds_data["n_skipped"]
            eval_metrics[f"eval/{ds_name}-avg_reward_collected_only"] = ds_data["avg_reward_collected_only"]
    return eval_metrics or None


def _run_openclaw_train_tasks(args, rollout_id: int):
    """Run all train tasks synchronously. Blocks until all tasks complete."""
    sources = _task_sources_from_env("OPENCLAW_TRAIN_TASKS")
    if not sources:
        print("[ClawGym-RL] OPENCLAW_TRAIN_TASKS not set, no training data", flush=True)
        return

    if len(sources) < 1:
        print("[ClawGym-RL] OPENCLAW_TRAIN_TASKS has no valid sources", flush=True)
        return
    tasks = []
    for source in sources:
        tasks.extend(source.tasks)
    print(f"[ClawGym-RL] Loaded {len(tasks)} train tasks from {len(sources)} source(s)", flush=True)

    if "PORT" not in os.environ or not os.environ["PORT"]:
        raise ValueError("PORT must be set for OpenClaw training")
    rl_port = int(os.environ["PORT"])
    max_turns = int(os.environ["OPENCLAW_TRAIN_MAX_TURNS"]) if "OPENCLAW_TRAIN_MAX_TURNS" in os.environ else 1
    requested_workers = int(os.environ["OPENCLAW_TRAIN_NUM_WORKERS"]) if "OPENCLAW_TRAIN_NUM_WORKERS" in os.environ else 128
    batch = _train_batch(args, tasks, rollout_id)
    worker_count = min(requested_workers, len(batch))

    # Record how many we dispatched
    with _TRAIN_METRICS_LOCK:
        _TRAIN_METRICS["dispatched"] = len(batch)

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = []
        for task_index, batch_item in enumerate(batch):
            group_index, task = batch_item
            futures.append(
                executor.submit(
                    _run_single_task,
                    args,
                    task,
                    rollout_id,
                    task_index,
                    "main",
                    max_turns,
                    rl_port,
                    group_index,
                    "train",
                )
            )
        future_to_meta = {fut: (idx, batch[idx][0]) for idx, fut in enumerate(futures)}
        for future in as_completed(futures):
            task_index, group_index = future_to_meta[future]
            try:
                result = future.result()
                print(f"[ClawGym-RL] train reward submitted: {result.reward:.4f}", flush=True)
            except (TimeoutError, requests.exceptions.HTTPError, requests.exceptions.ConnectionError, OSError, subprocess.CalledProcessError) as exc:
                # Submit reward=0 so GRPO sees the failure (otherwise the group is
                # short and long-loop trajectories silently disappear from gradients).
                session_id = f"task-{rollout_id}-{task_index}"
                recovered = False
                try:
                    _submit_reward(rl_port, session_id, 0.0, group_index)
                    recovered = True
                    print(
                        f"[ClawGym-RL] train task SKIPPED reward=0 submitted (error: {type(exc).__name__}: {exc})",
                        flush=True,
                    )
                except Exception as submit_exc:
                    print(
                        f"[ClawGym-RL] train task SKIPPED and reward=0 submit FAILED "
                        f"(orig: {type(exc).__name__}: {exc}; submit: {type(submit_exc).__name__}: {submit_exc})",
                        flush=True,
                    )
                with _TRAIN_METRICS_LOCK:
                    _TRAIN_METRICS["skipped"] = _TRAIN_METRICS.get("skipped", 0) + 1
                    if recovered:
                        _TRAIN_METRICS["skipped_recovered"] = _TRAIN_METRICS.get("skipped_recovered", 0) + 1
                    else:
                        _TRAIN_METRICS["skipped_lost"] = _TRAIN_METRICS.get("skipped_lost", 0) + 1


def get_global_worker(args, data_buffer) -> AsyncRolloutWorker:
    global _GLOBAL_WORKER
    with _GLOBAL_WORKER_LOCK:
        if _GLOBAL_WORKER is None or _GLOBAL_WORKER.worker_thread is None or not _GLOBAL_WORKER.worker_thread.is_alive():
            _GLOBAL_WORKER = AsyncRolloutWorker(args, data_buffer)
            _GLOBAL_WORKER.start()
        return _GLOBAL_WORKER


def stop_global_worker():
    global _GLOBAL_WORKER
    with _GLOBAL_WORKER_LOCK:
        if _GLOBAL_WORKER is not None:
            _GLOBAL_WORKER.stop()
            _GLOBAL_WORKER = None


def _cleanup_rollout_resources(rollout_id: int):
    """Remove leftover containers (Docker or chroot) and temp dirs from this rollout step."""
    try:
        if _get_rootfs() is None:
            # Docker mode: kill leftover containers
            result = subprocess.run(
                ["docker", "ps", "-aq", "--filter", f"name=clawgym-rl-{rollout_id}-"],
                capture_output=True, text=True, timeout=10,
            )
            container_ids = result.stdout.strip().split()
            if container_ids:
                subprocess.run(
                    ["docker", "rm", "-f"] + container_ids,
                    capture_output=True, text=True, timeout=30,
                )
                print(f"[ClawGym-RL] cleaned up {len(container_ids)} stale containers from rollout {rollout_id}", flush=True)
        else:
            # Chroot mode: kill leftover gateway processes tied to THIS rollout's
            # temp dir pattern. unshare --user + PID-1-in-ns means SIGTERM is
            # ignored; we go straight to SIGKILL.
            subprocess.run(
                ["pkill", "-9", "-f", f"clawgym-rl-{rollout_id}-"],
                capture_output=True, text=True, timeout=10,
            )

        # Remove temp dirs
        import glob
        tmp_dirs = glob.glob(f"/tmp/clawgym-rl-{rollout_id}-*")
        for d in tmp_dirs:
            shutil.rmtree(d, ignore_errors=True)
        if tmp_dirs:
            print(f"[ClawGym-RL] cleaned up {len(tmp_dirs)} temp dirs from rollout {rollout_id}", flush=True)

        if _get_rootfs() is None:
            # Prune stopped containers to reclaim Docker disk/overlay resources
            subprocess.run(
                ["docker", "container", "prune", "-f"],
                capture_output=True, text=True, timeout=30,
            )

        # Gateway census: if alive (non-zombie) gateway procs exceed expected,
        # force-kill strays. This catches gateways whose parent died without
        # reaping them and which are still holding ports / hung on a request.
        try:
            ps_out = subprocess.run(
                ["ps", "-eo", "pid,stat,comm"],
                capture_output=True, text=True, timeout=10,
            ).stdout
            alive_gateways = 0
            for line in ps_out.splitlines():
                parts = line.split(None, 2)
                if len(parts) < 3:
                    continue
                _, stat, comm = parts
                if "openclaw-gatewa" in comm and "Z" not in stat:
                    alive_gateways += 1
            # Expected upper bound: 2x concurrent workers (eval + train overlap)
            eval_workers = int(os.environ.get("OPENCLAW_EVAL_NUM_WORKERS", "16"))
            train_workers = int(os.environ.get("OPENCLAW_TRAIN_NUM_WORKERS", "32"))
            expected_max = (eval_workers + train_workers) * 2
            if alive_gateways > expected_max:
                subprocess.run(
                    ["pkill", "-9", "-f", "openclaw-gatewa"],
                    capture_output=True, timeout=10,
                )
                print(
                    f"[ClawGym-RL] gateway census: {alive_gateways} alive "
                    f"(expected <= {expected_max}), force-killed all",
                    flush=True,
                )
            elif alive_gateways > 0:
                print(
                    f"[ClawGym-RL] gateway census: {alive_gateways} alive (ok, <= {expected_max})",
                    flush=True,
                )
        except Exception as exc:
            print(f"[ClawGym-RL] gateway census warning: {exc}", flush=True)
    except Exception as exc:
        print(f"[ClawGym-RL] cleanup warning: {exc}", flush=True)


def generate_rollout_clawgym_rl(args, rollout_id, data_buffer, evaluation=False):
    worker = get_global_worker(args, data_buffer)

    if evaluation:
        worker.resume_submission()
        try:
            result = _run_openclaw_eval(args, rollout_id)
        finally:
            worker.pause_submission()
        _cleanup_rollout_resources(rollout_id)
        if result is not None:
            return RolloutFnEvalOutput(data=result, metrics=_build_eval_metrics(result))
        eval_output, _ = run(eval_rollout(args, rollout_id))
        return eval_output

    # Reset per-step train metrics
    with _TRAIN_METRICS_LOCK:
        _TRAIN_METRICS.clear()

    worker.server.reset_eval_scores()
    worker.resume_submission()
    worker.server._step_counts.clear()
    worker.server._pending_step_data.clear()
    stale_items = worker.get_completed_groups()
    if stale_items:
        print(f"[ClawGym-RL] purged {len(stale_items)} stale queue items", flush=True)

    # Run all train tasks synchronously — blocks until every container finishes
    _run_openclaw_train_tasks(args, rollout_id)

    # All tasks done, pause submission and collect all samples from queue
    worker.pause_submission()

    # Collect all completed samples from the queue
    n_groups = int(args.rollout_batch_size)
    n_per_group = int(args.n_samples_per_prompt)
    groups: dict[int, list[Sample]] = {}
    for group_id, samples in worker.get_completed_groups():
        if group_id not in groups:
            groups[group_id] = []
        for sample in samples:
            if sample.status != Sample.Status.ABORTED:
                groups[group_id].append(sample)

    completed_samples: list[list[Sample]] = []
    for group_id in sorted(groups):
        group_samples = groups[group_id]
        if len(group_samples) >= 4:
            completed_samples.append(group_samples)
        else:
            print(
                f"[ClawGym-RL] dropping group {group_id}: only {len(group_samples)} sample(s), need >=4 for GRPO",
                flush=True,
            )

    if completed_samples:
        group_sizes = [len(g) for g in completed_samples]
        print(
            f"[ClawGym-RL] collected {len(completed_samples)} groups, "
            f"group sizes: min={min(group_sizes)}, max={max(group_sizes)}, "
            f"total={sum(group_sizes)} samples",
            flush=True,
        )

    # Cleanup stale Docker containers and temp dirs from this rollout step
    _cleanup_rollout_resources(rollout_id)

    eval_scores = worker.server.drain_eval_scores()

    # ── Build metrics dict for wandb ─────────────────────────────────────
    metrics = _build_train_metrics(args, completed_samples, eval_scores)

    return RolloutFnTrainOutput(samples=completed_samples, metrics=metrics or None)


def _build_train_metrics(args, completed_samples, eval_scores=None):
    """Build openclaw/ wandb metrics from _TRAIN_METRICS and completed samples."""
    n_target = int(args.rollout_batch_size) * int(args.n_samples_per_prompt)
    with _TRAIN_METRICS_LOCK:
        m = dict(_TRAIN_METRICS)
        _TRAIN_METRICS.clear()
    rewards = m.get("rewards", [])
    n_submitted = m.get("submitted", 0)
    n_skipped = m.get("skipped", 0)
    steps_total = m.get("steps_total", 0)
    n_groups_used = len(completed_samples)

    metrics = {}
    if eval_scores:
        metrics["rollout/prm_eval_score"] = sum(eval_scores) / len(eval_scores)

    # Completion rates
    metrics["openclaw/submitted_trajectories"] = n_submitted
    metrics["openclaw/skipped_trajectories"] = n_skipped
    metrics["openclaw/skipped_recovered"] = m.get("skipped_recovered", 0)
    metrics["openclaw/skipped_lost"] = m.get("skipped_lost", 0)
    metrics["openclaw/timed_out_trajectories"] = m.get("dispatched", n_target) - n_submitted - n_skipped
    metrics["openclaw/groups_used"] = n_groups_used

    # Sample counts (after multi-step splitting, total_samples >> submitted_trajectories)
    total_samples = sum(len(g) for g in completed_samples) if completed_samples else 0
    metrics["openclaw/total_samples"] = total_samples
    metrics["openclaw/avg_samples_per_trajectory"] = total_samples / n_submitted if n_submitted > 0 else 0

    # Reward stats (only counting submitted)
    if rewards:
        avg_reward_submitted = sum(rewards) / len(rewards)
        # Treat missing as 0: total reward / target count
        avg_reward_with_missing = sum(rewards) / n_target if n_target > 0 else 0.0
        metrics["openclaw/avg_reward_submitted"] = avg_reward_submitted
        metrics["openclaw/avg_reward_with_missing_as_zero"] = avg_reward_with_missing

    # Average task completion time
    durations = m.get("durations", [])
    if durations:
        metrics["openclaw/avg_task_duration_sec"] = sum(durations) / len(durations)
        metrics["openclaw/max_task_duration_sec"] = max(durations)
        metrics["openclaw/p90_task_duration_sec"] = sorted(durations)[int(len(durations) * 0.9)]

    # Group-level reward distribution
    if completed_samples:
        n_all_zero = 0
        n_all_one = 0
        n_all_same_mid = 0
        n_mixed = 0
        group_variances = []
        for group in completed_samples:
            group_rewards = [float(s.reward.get("score", 0)) if isinstance(s.reward, dict) else 0.0 for s in group]
            mean = sum(group_rewards) / len(group_rewards) if group_rewards else 0.0
            var = sum((r - mean) ** 2 for r in group_rewards) / len(group_rewards) if group_rewards else 0.0
            group_variances.append(var)
            if all(r == 0.0 for r in group_rewards):
                n_all_zero += 1
            elif all(r >= 1.0 for r in group_rewards):
                n_all_one += 1
            elif var == 0.0:
                n_all_same_mid += 1
            else:
                n_mixed += 1
        n_g = len(completed_samples)
        metrics["openclaw/group_all_zero_frac"] = n_all_zero / n_g
        metrics["openclaw/group_all_one_frac"] = n_all_one / n_g
        metrics["openclaw/group_all_same_mid_frac"] = n_all_same_mid / n_g
        metrics["openclaw/group_mixed_frac"] = n_mixed / n_g
        metrics["openclaw/group_reward_var_mean"] = sum(group_variances) / n_g
        # Fraction of groups with zero variance (no gradient signal)
        metrics["openclaw/group_zero_var_frac"] = sum(1 for v in group_variances if v == 0.0) / n_g

    # Average steps per trajectory
    if n_submitted > 0:
        metrics["openclaw/avg_steps_per_trajectory"] = steps_total / n_submitted

    # Format penalty count
    metrics["openclaw/format_penalty_count"] = m.get("format_penalty", 0)
    # Format penalty that actually killed a non-zero reward
    metrics["openclaw/format_penalty_nonzero_to_zero"] = m.get("format_penalty_nonzero_to_zero", 0)

    return metrics


atexit.register(stop_global_worker)
