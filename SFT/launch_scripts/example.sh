#!/usr/bin/env bash
set -xeuo pipefail

deepspeed \
   --module openrlhf.cli.train_sft \
   --max_len 65536 \
   --dataset ../datastes/openclaw_training_demo_datasets.jsonl  \
   --input_key "messages" \
   --pretrain path_to_Qwen3-4B-Instruct-2507 \
   --save_path path_to_save_path \
   --ckpt_path path_to_save_ckpt_path \
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
   --ring_attn_size 4
