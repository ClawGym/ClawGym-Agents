#!/usr/bin/env bash
set -xeuo pipefail

deepspeed \
   --module openrlhf.cli.train_sft \
   --max_len 65536 \
   --dataset ../datastes/openclaw_training_demo_datasets.jsonl  \
   --input_key "messages" \
   --pretrain /volume/posttrain/users/lyang/models/Qwen3-4B-Instruct-2507 \
   --save_path /volume/posttrain/users/lyang/models/openclaw-sft/4b-w-desp-reward05-all-based-04_181920-data \
   --ckpt_path /volume/posttrain/users/lyang/models/openclaw-sft/4b-w-desp-reward05-all-based-04_181920-data-ckpt \
   --save_steps 80 \
   --max_ckpt_num 10 \
   --logging_steps 1 \
   --train_batch_size 128 \
   --micro_train_batch_size 1 \
   --max_samples 1000000 \
   --eval_steps -1 \
   --zero_stage 2 \
   --max_epochs 3 \
   --packing_samples \
   --bf16 \
   --save_hf_ckpt \
   --flash_attn \
   --learning_rate 1e-5 \
   --gradient_checkpointing \
   --apply_chat_template \
   --multiturn \
   --use_tensorboard /volume/posttrain/users/lyang/openclaw-sft/tensorboard/4b-w-desp-reward05-all-based-04_181920-data \
   --ring_attn_size 4
