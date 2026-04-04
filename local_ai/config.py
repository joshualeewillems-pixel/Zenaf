"""
Central model configuration for Atria and File Steward.
One place controls provider choice, Ollama settings, and LLM second-pass toggle.
"""

MODEL_PROVIDER = "ollama"
OLLAMA_MODEL = "qwen3:8b"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_TIMEOUT = 60

# Council-specific default (Pass 2 benchmark: qwen2:7b-instruct). Non-council still uses OLLAMA_MODEL.
OLLAMA_COUNCIL_MODEL = "qwen2:7b-instruct"

ENABLE_LLM_SECOND_PASS = True
