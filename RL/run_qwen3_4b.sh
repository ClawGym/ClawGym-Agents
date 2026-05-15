#!/bin/bash
# ============================================================================
# ClawGym-RL training launch script (Qwen3-4B).
#
# Architecture:
#   Slime (trainer) ─── Ray ─── SGLang (inference engine)
#                                  ↑
#                        ClawGymRLAPIServer (proxy)
#                                  ↑
#                        OpenClaw container (agent execution sandbox: Docker or chroot)
#
# GPU allocation:
#   ACTOR_GPUS   → Megatron actor (training forward/backward)
#   ROLLOUT_GPUS → SGLang inference engine (model inference + tool-call generation)
#   The two sets are disjoint and ACTOR_GPUS + ROLLOUT_GPUS <= NUM_GPUS.
# ============================================================================

# --- Cleanup leftover processes ---
pkill -9 sglang
pkill -9 -f 'node.*dist/index.js.*gateway'
pkill -9 -f 'openclaw-gatewa'
sleep 3
ray stop --force
pkill -9 -f 'raylet|gcs_server|dashboard.py|runtime_env_agent|log_monitor.py|monitor.py|ray::'
pkill -9 python
if [ -z "${OPENCLAW_ROOTFS:-}" ]; then
  docker rm -f $(docker ps -aq --filter "name=clawgym-rl-") 2>/dev/null
fi
sleep 3
pkill -9 -f 'raylet|gcs_server|dashboard.py|runtime_env_agent|log_monitor.py|monitor.py|ray::'
pkill -9 python

set -ex

export PYTHONUNBUFFERED=1    # unbuffered stdout/stderr
export PYTHONFAULTHANDLER=1  # print traceback on hard crash

# --- GPU allocation ---
NUM_GPUS=${NUM_GPUS:-8}          # total GPUs available
ACTOR_GPUS=${ACTOR_GPUS:-4}      # GPUs for the Megatron actor (sets TP size)
ROLLOUT_GPUS=${ROLLOUT_GPUS:-4}  # GPUs for the SGLang inference engine
# ACTOR_GPUS  -> tensor-model-parallel-size below.
# ROLLOUT_GPUS -> rollout-num-gpus-per-engine below.

# Colocate mode: training and inference share GPUs, swapped via offload.
if [ "${USE_COLOCATE:-0}" = "1" ]; then
  ACTOR_GPUS=${NUM_GPUS}
  ROLLOUT_GPUS=${NUM_GPUS}
  echo "[ClawGym-RL] COLOCATE mode: all ${NUM_GPUS} GPUs shared between training and inference"
fi

if [ "${USE_COLOCATE:-0}" != "1" ] && (( ACTOR_GPUS + ROLLOUT_GPUS > NUM_GPUS )); then
    echo "ACTOR_GPUS + ROLLOUT_GPUS must be <= NUM_GPUS"
    echo "ACTOR_GPUS=${ACTOR_GPUS}, ROLLOUT_GPUS=${ROLLOUT_GPUS}, NUM_GPUS=${NUM_GPUS}"
    exit 1
fi

# --- Ray health-check tuning (avoid spurious node-dead detection at scale) ---
export RAY_health_check_failure_threshold=20
export RAY_health_check_period_ms=5000
export RAY_health_check_timeout_ms=30000
export RAY_num_heartbeats_timeout=60

# --- Paths ---
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
SLIME_ROOT="$(cd -- "${SCRIPT_DIR}/slime" &>/dev/null && pwd)"
source "${SLIME_ROOT}/scripts/models/qwen3-4B.sh"  # populate MODEL_ARGS (num layers, hidden size, ...)

# --- Experiment name (drives save path and wandb group) ---
EXP_NAME=${EXP_NAME:-clawgym-rl-4b-instruct-2507}

# --- Model paths ---
HF_CKPT=${HF_CKPT:-${SCRIPT_DIR}/local/models/Qwen3-4B-Instruct-2507}  # HF-format initial weights
REF_LOAD=${REF_LOAD:-${HF_CKPT}}                                       # reference model for KL (usually same as init)
SAVE_CKPT=${SAVE_CKPT:-${SCRIPT_DIR}/exp/${EXP_NAME}}                  # training output directory

if [ ! -d "${HF_CKPT}" ]; then
    echo "ERROR: HF model not found at ${HF_CKPT}"
    echo "Download it first:"
    echo "  hf download Qwen/Qwen3-4B-Instruct-2507 --local-dir ${HF_CKPT}"
    exit 1
fi

# --- Mirror training logs into the checkpoint directory ---
_TIMESTAMP=$(date +%Y%m%d_%H%M%S)
_LOG_DIR="${SAVE_CKPT}/logs"
mkdir -p "${_LOG_DIR}"
exec > >(tee -a "${_LOG_DIR}/train_${_TIMESTAMP}.log") 2>&1
echo "[$(date)] Training log: ${_LOG_DIR}/train_${_TIMESTAMP}.log"

# --- Local API server config ---
export SGLANG_API_KEY="${SGLANG_API_KEY}"     # SGLang API auth (optional)
export SERVED_MODEL_NAME="qwen3-4b-instruct"  # model name surfaced in API requests
export HOST="0.0.0.0"                          # API server bind address
export PORT="${PORT:-30001}"                   # API server port (OpenClaw container talks to RL server here)

# --- Logging ---
export OPENCLAW_RECORD_ENABLED="${OPENCLAW_RECORD_ENABLED:-0}"  # record per-turn JSONL logs
export OPENCLAW_RECORD_FILE="${SCRIPT_DIR}/results/qwen3_4b_record.jsonl"

# --- SGLang tool-call parsing (informational; consumed by SGLANG_ARGS below) ---
export TOOL_CALL_PARSER="${TOOL_CALL_PARSER:-qwen25}"  # SGLang tool-call parser
export REASONING_PARSER="${REASONING_PARSER:-}"        # optional chain-of-thought parser

# --- OpenClaw user-turn limits ---
# max_turns=1 means we send one user message; the agent may still issue many internal tool steps
# (capped inside OpenClaw). "turn" here = number of user messages we send to the gateway.
export OPENCLAW_EVAL_MAX_TURNS="${OPENCLAW_EVAL_MAX_TURNS:-1}"
export OPENCLAW_TRAIN_MAX_TURNS="${OPENCLAW_TRAIN_MAX_TURNS:-1}"

# --- Eval parallelism ---
# Number of concurrent OpenClaw containers during evaluation.
export OPENCLAW_EVAL_NUM_WORKERS="${OPENCLAW_EVAL_NUM_WORKERS:-32}"

# --- Train parallelism ---
# Number of concurrent OpenClaw containers per training rollout.
# Lower values reduce gateway concurrency pressure at the cost of slower rollouts.
export OPENCLAW_TRAIN_NUM_WORKERS="${OPENCLAW_TRAIN_NUM_WORKERS:-64}"

# ============================================================================
# Checkpoint args
# ============================================================================
CKPT_ARGS=(
   --megatron-to-hf-mode bridge  # weight conversion between Megatron and HF via bridge mode
   --hf-checkpoint "${HF_CKPT}"  # HF-format initial weights
   --ref-load "${REF_LOAD}"      # KL reference model
   --save "${SAVE_CKPT}"         # training checkpoint output dir
   --save-interval "${SAVE_INTERVAL:-5}"
   --rotary-base 5000000         # RoPE base frequency (Qwen3 uses 5M)
)

# ============================================================================
# Rollout args (controls per-iteration rollout data and decoding)
# ============================================================================
ROLLOUT_FN="clawgym_rl_rollout.generate_rollout_clawgym_rl"

# --- Context / response length (single source of truth for rollout, SGLang and OpenClaw gateway) ---
OPENCLAW_CONTEXT_WINDOW=${OPENCLAW_CONTEXT_WINDOW:-65536}
OPENCLAW_MAX_TOKENS=${OPENCLAW_MAX_TOKENS:-8192}

ROLLOUT_ARGS=(
   --disable-rollout-global-dataset           # do not use Slime's built-in dataset; we manage data ourselves
   --rollout-function-path "${ROLLOUT_FN}"    # custom rollout function

   --num-rollout 100000000                    # total rollout iterations (set huge = run forever)
   --rollout-batch-size ${ROLLOUT_BATCH_SIZE:-8}    # distinct prompts (tasks) per rollout
                                                     # concurrent containers = rollout-batch-size * n-samples-per-prompt
   --n-samples-per-prompt 8                   # samples per prompt (GRPO needs multiple samples per prompt to compare)
                                              # 8 * 8 = 64 concurrent containers
   --rollout-max-response-len ${OPENCLAW_MAX_TOKENS}     # max tokens per single model generation
   --rollout-max-context-len ${OPENCLAW_CONTEXT_WINDOW}  # max context (system + user + history + response)
   --rollout-temperature 0.7                  # sampling temperature (GRPO needs some randomness for sample diversity)
   --reward-key score                         # key in the reward dict used as the scalar score

   --num-steps-per-rollout 1                  # gradient updates per rollout (1 = standard online GRPO)
)

# ============================================================================
# GRPO algorithm args
# ============================================================================
GRPO_ARGS=(
   --advantage-estimator grpo       # GRPO advantage estimator
   --dynamic-history                # split samples of one trajectory share sample.index; baseline is per-trajectory, not per-sample
   --use-kl-loss                    # enable KL penalty
   --kl-loss-coef 0.0               # KL coefficient (0 = no penalty)
   --kl-loss-type low_var_kl        # low-variance KL estimator
   --entropy-coef 0.00              # entropy regularization (raise to encourage exploration)
   --eps-clip 0.2                   # PPO clip lower bound (standard 0.2)
   --eps-clip-high 0.28             # PPO clip upper bound (slightly higher to allow small positive drift)
   --use-dynamic-global-batch-size  # tolerate occasional missing samples by dynamically adjusting batch size
   --calculate-per-token-loss       # DAPO-style: loss is summed over response tokens then divided by total token count
)

# ============================================================================
# Performance args (parallelism + memory optimization)
# ============================================================================
PERF_ARGS=(
   --tensor-model-parallel-size ${ACTOR_GPUS}  # TP degree (= ACTOR_GPUS)
   --sequence-parallel               # enable sequence parallelism (reduces TP communication)
   --pipeline-model-parallel-size 1  # pipeline parallelism (1 = single stage)
   --context-parallel-size 1         # context parallelism (1 = off)
   --expert-model-parallel-size 1    # MoE expert parallelism (1; Qwen3-4B is dense)
   --expert-tensor-parallel-size 1
   --recompute-granularity full      # full activation recompute (trade compute for memory)
   --recompute-method uniform        # uniform recompute across layers
   --recompute-num-layers 1          # recompute one layer at a time
   --use-dynamic-batch-size          # batch by token count rather than sample count
   --max-tokens-per-gpu 65536        # per-GPU max tokens per micro-batch
   --log-probs-chunk-size 1024       # log-prob computation chunk size (prevents OOM)
)

# ============================================================================
# Optimizer args
# ============================================================================
OPTIMIZER_ARGS=(
   --optimizer adam
   --lr 1e-6                          # learning rate (RL fine-tuning typically 1e-5 to 1e-6)
   --lr-decay-style constant          # constant LR
   --weight-decay 0.1
   --adam-beta1 0.9
   --adam-beta2 0.98
   --optimizer-cpu-offload            # offload optimizer state to CPU
   --overlap-cpu-optimizer-d2h-h2d    # overlap CPU<->GPU transfer with compute
   --use-precision-aware-optimizer    # required when CPU offload is enabled
)

# ============================================================================
# Eval args
# ============================================================================
EVAL_ARGS=(
   --eval-interval "${OPENCLAW_EVAL_INTERVAL:-5}"  # run eval every N rollouts
   --eval-function-path "${ROLLOUT_FN}"            # eval reuses the rollout function
   ${SKIP_INITIAL_EVAL:+--skip-eval-before-train}  # set SKIP_INITIAL_EVAL=1 to skip the eval run before training starts
)

# ============================================================================
# SGLang inference engine args
# ============================================================================
SGLANG_ARGS=(
   --rollout-num-gpus-per-engine ${SGLANG_TP:-1}     # TP per SGLang engine (default 1)
   --sglang-tool-call-parser "${TOOL_CALL_PARSER}"   # tool-call parser
   --sglang-mem-fraction-static 0.8                  # static memory fraction (higher = more KV cache)
   --sglang-context-length ${OPENCLAW_CONTEXT_WINDOW}  # SGLang max context length;
                                                       # must be >= rollout-max-context-len or long conversations get 400'd
   ${REASONING_PARSER:+--sglang-reasoning-parser $REASONING_PARSER}  # optional reasoning parser
)

# ============================================================================
# Custom function paths (Slime calls our code through these hooks)
# ============================================================================
CUSTOM_ARGS=(
   --custom-generate-function-path clawgym_rl_api_server.generate    # custom generate function
   --custom-rm-path clawgym_rl_api_server.reward_func                # custom reward function
)

# ============================================================================
# Misc
# ============================================================================
MISC_ARGS=(
   --attention-dropout 0.0               # attention dropout (off for RL FT)
   --hidden-dropout 0.0                  # hidden dropout
   --accumulate-allreduce-grads-in-fp32  # accumulate gradients in fp32
   --attention-softmax-in-fp32           # softmax in fp32
   --attention-backend flash             # use Flash Attention
)

# ============================================================================
# WandB
# ============================================================================
USE_WANDB=${USE_WANDB:-1}
WANDB_PROJECT=${WANDB_PROJECT:-clawgym_rl}
WANDB_KEY_VALUE=${WANDB_KEY:-${WANDB_API_KEY:-}}
if [ "${USE_WANDB}" = "1" ] && [ -n "${WANDB_KEY_VALUE}" ]; then
  WANDB_ARGS=(
    --use-wandb
    --wandb-project ${WANDB_PROJECT}
    --wandb-group ${EXP_NAME}
    --wandb-key ${WANDB_KEY_VALUE}
  )
else
  WANDB_ARGS=()
fi

# ============================================================================
# Dataset paths
# ============================================================================
export OPENCLAW_EVAL_TASKS="${OPENCLAW_EVAL_TASKS:-${SCRIPT_DIR}/data/clawgym_eval}"
export OPENCLAW_TRAIN_TASKS="${OPENCLAW_TRAIN_TASKS:-${SCRIPT_DIR}/data/clawgym_train}"

# ============================================================================
# Start Ray + submit training job
# ============================================================================
export MASTER_ADDR=${MASTER_ADDR:-"127.0.0.1"}
export no_proxy="127.0.0.1,${MASTER_ADDR}"
ray start --head --node-ip-address "${MASTER_ADDR}" --num-gpus "${NUM_GPUS}" --disable-usage-stats --dashboard-host=0.0.0.0 --dashboard-port=8265

RUNTIME_ENV_JSON="{
  \"env_vars\": {
   \"PYTHONPATH\": \"${SLIME_ROOT}/../Megatron-LM/:${SCRIPT_DIR}:${SLIME_ROOT}\",
    \"CUDA_DEVICE_MAX_CONNECTIONS\": \"1\",
    \"OPENCLAW_EVAL_TASKS\": \"${OPENCLAW_EVAL_TASKS}\",
    \"OPENCLAW_TRAIN_TASKS\": \"${OPENCLAW_TRAIN_TASKS}\",
    \"OPENCLAW_EVAL_MAX_TURNS\": \"${OPENCLAW_EVAL_MAX_TURNS}\",
    \"OPENCLAW_TRAIN_MAX_TURNS\": \"${OPENCLAW_TRAIN_MAX_TURNS}\",
    \"OPENCLAW_EVAL_NUM_WORKERS\": \"${OPENCLAW_EVAL_NUM_WORKERS}\",
    \"OPENCLAW_EVAL_N_SAMPLES\": \"${OPENCLAW_EVAL_N_SAMPLES:-1}\",
    \"OPENCLAW_TRAIN_NUM_WORKERS\": \"${OPENCLAW_TRAIN_NUM_WORKERS}\",
    \"OPENCLAW_ROOTFS\": \"${OPENCLAW_ROOTFS:-}\",
    \"OPENCLAW_GATEWAY_IMAGE\": \"${OPENCLAW_GATEWAY_IMAGE:-clawgym-rl:v0.1}\",
    \"OPENCLAW_CONTEXT_WINDOW\": \"${OPENCLAW_CONTEXT_WINDOW}\",
    \"OPENCLAW_MAX_TOKENS\": \"${OPENCLAW_MAX_TOKENS}\",
    \"PORT\": \"${PORT}\"
  }
}"

# Submit to Ray.
if [ "${USE_COLOCATE:-0}" = "1" ]; then
  TRAIN_SCRIPT="train.py"
else
  TRAIN_SCRIPT="train_async.py"
fi
ray job submit --address="http://127.0.0.1:8265" \
   --working-dir "${SLIME_ROOT}" \
   --runtime-env-json="${RUNTIME_ENV_JSON}" \
   -- python3 "${TRAIN_SCRIPT}" \
   --actor-num-nodes 1 \
   --actor-num-gpus-per-node "${ACTOR_GPUS}" \
   --rollout-num-gpus "${ROLLOUT_GPUS}" \
   --num-gpus-per-node "${NUM_GPUS}" \
   ${USE_COLOCATE:+--colocate} \
   ${MODEL_ARGS[@]} \
   ${CKPT_ARGS[@]} \
   ${ROLLOUT_ARGS[@]} \
   ${OPTIMIZER_ARGS[@]} \
   ${GRPO_ARGS[@]} \
   ${PERF_ARGS[@]} \
   ${EVAL_ARGS[@]} \
   ${SGLANG_ARGS[@]} \
   ${MISC_ARGS[@]} \
   ${WANDB_ARGS[@]} \
   ${CUSTOM_ARGS[@]}
