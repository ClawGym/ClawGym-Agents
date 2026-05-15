## SFT Training
> [!IMPORTANT]
> We use the open-source framework [OpenRLHF](https://github.com/OpenRLHF/OpenRLHF) for SFT training of dense models, such as Qwen3-4B and Qwen3-8B. For MoE models, such as Qwen3-30B-A3B, we train them using our internal Megatron-based framework. Here, we provide the SFT training pipeline based on the open-source framework.

### Environment Setup 

You can refer to the environment configuration provided by [OpenRLHF](https://github.com/OpenRLHF/OpenRLHF) for installation. If you are using Ray, ensure that the environment is configured uniformly across all nodes:
```bash
cd ./ClawGym-Agents/SFT
uv venv --python 3.11
source .venv/bin/activate
git clone https://github.com/OpenRLHF/OpenRLHF.git
cd OpenRLHF
pip install -e .
```

### Training

```bash
# Pre-tokenize multi-turn interaction trajectories and compute loss masks (Optional, but recommended to avoid training bottlenecks)
python ./ClawGym-Agents/SFT/process_scripts/sft_data_pre_tokenize_toolcall_for_openclaw.py

# Optional: This step is required if you pre-tokenized the multi-turn data in the previous steps
mv ./ClawGym-Agents/SFT/process_scripts/sft_dataset.py ./ClawGym-Agents/SFT/OpenRLHF/openrlhf/datasets/sft_dataset.py 

# Launch training
bash ./ClawGym-Agents/SFT/launch_scripts/example.sh
```