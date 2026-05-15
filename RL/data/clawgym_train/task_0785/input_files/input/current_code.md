# Current Inference Code (to be audited by EcoLobster)

```python
# Environment:
# - PyTorch 2.12.0.dev20260315+cu128
# - CUDA 12.8
# - transformers 4.50.0
# - bitsandbytes 0.45.3
# - torchao 0.17.0.dev20260316+cu128 (not currently used in prod)

from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
import torch

MODEL_ID = "Qwen/Qwen2.5-7B-Instruct"

# Weight-only INT8 (bitsandbytes) — current setting in prod:
# NOTE: We purposely kept this simple; no extra thresholds or overrides.
bnb_config = BitsAndBytesConfig(
    load_in_8bit=True  # using default llm_int8_threshold (not set)
)

tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, use_fast=True)
model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID,
    device_map="auto",
    quantization_config=bnb_config
)
model.eval()

# We are prioritizing low-latency single-request handling for now.
BS = 1  # batch size
MAX_NEW_TOKENS = 256
INPUT_LEN = 512

# Example requests (handled one by one; no dynamic batching yet)
prompts = [
    "Summarize the key points from this product doc in 5 bullet points.",
    "Translate the following English paragraph into Chinese with business tone.",
    "Generate a concise response for a customer asking about pricing tiers."
]

def run_request(prompt: str):
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    with torch.no_grad():
        output_ids = model.generate(
            **inputs,
            max_new_tokens=MAX_NEW_TOKENS,
            do_sample=False,
            temperature=0.0
        )
    return tokenizer.decode(output_ids[0], skip_special_tokens=True)

if __name__ == "__main__":
    for p in prompts:
        result = run_request(p)
        print("=== Response ===")
        print(result)
        print()

# --- Experimental (disabled) ---
# We briefly tested FP8 eager mode with torchao, but left it commented out due to instability:
# from torchao.quantization import float8_weight_only, Float8WeightOnlyConfig
# model = float8_weight_only(model, Float8WeightOnlyConfig())
# (This path is NOT active in production.)
```