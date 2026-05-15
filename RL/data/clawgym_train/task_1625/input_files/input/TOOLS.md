## Model Queue Configuration

# Max retries and default source
MODEL_QUEUE_MAX_RETRIES=3
DEFAULT_MODEL_SOURCE=ollama-remote

# Model Source Mappings (REQUIRED)
# Format: MODEL_SOURCE_{NAME}=model1,model2,model3

MODEL_SOURCE_OLLAMA_LOCAL=ollama/qwen2.5,ollama/llama3,ollama/mistral
MODEL_SOURCE_OLLAMA_REMOTE=ollama-remote/qwen3.5:27b,ollama-remote/llama3:70b
MODEL_SOURCE_CLOUD_NVIDIA=nvidia/z-ai/glm5,nvidia/llama3