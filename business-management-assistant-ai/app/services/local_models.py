from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LocalModel:
    key: str
    repo_id: str
    display_name: str
    tasks: tuple[str, ...]
    size_hint: str
    license_name: str
    official_url: str
    recommended_runtime: str
    download_command: str
    notes: str


LOCAL_MODELS = (
    LocalModel(
        key="qwen3-0.6b",
        repo_id="Qwen/Qwen3-0.6B",
        display_name="Qwen3 0.6B",
        tasks=("routing", "classification", "short_extraction", "local_chat"),
        size_hint="0.6B parameters; compact CPU/GPU option",
        license_name="Apache-2.0",
        official_url="https://huggingface.co/Qwen/Qwen3-0.6B",
        recommended_runtime="transformers or llama.cpp-compatible quantization",
        download_command="python scripts/download_small_model.py qwen3-0.6b",
        notes="Good default seed for high-volume routing and short structured tasks; use non-thinking mode for low latency.",
    ),
    LocalModel(
        key="smollm2-1.7b-instruct",
        repo_id="HuggingFaceTB/SmolLM2-1.7B-Instruct",
        display_name="SmolLM2 1.7B Instruct",
        tasks=("classification", "summarization", "rewriting", "function_call_drafts", "local_chat"),
        size_hint="1.7B parameters; stronger compact instruction model",
        license_name="Apache-2.0",
        official_url="https://huggingface.co/HuggingFaceTB/SmolLM2-1.7B-Instruct",
        recommended_runtime="transformers, Transformers.js, vLLM, or SGLang",
        download_command="python scripts/download_small_model.py smollm2-1.7b-instruct",
        notes="Use as the compact workhorse for summaries, rewrites, and draft tool calls.",
    ),
    LocalModel(
        key="gemma3-1b-it",
        repo_id="google/gemma-3-1b-it",
        display_name="Gemma 3 1B IT",
        tasks=("local_chat", "summarization", "image_text_assistance", "classification"),
        size_hint="1B parameters; text model with image-text capability in the Gemma family",
        license_name="Gemma Terms of Use",
        official_url="https://huggingface.co/google/gemma-3-1b-it",
        recommended_runtime="transformers or an approved local runtime",
        download_command="python scripts/download_small_model.py gemma3-1b-it",
        notes="Requires accepting Google's Gemma terms on Hugging Face before downloading gated files.",
    ),
    LocalModel(
        key="qwen3-embedding-0.6b",
        repo_id="Qwen/Qwen3-Embedding-0.6B",
        display_name="Qwen3 Embedding 0.6B",
        tasks=("embeddings", "semantic_search", "reranking_support", "knowledge_indexing"),
        size_hint="0.6B parameters; embedding and retrieval specialist",
        license_name="Apache-2.0",
        official_url="https://huggingface.co/Qwen/Qwen3-Embedding-0.6B",
        recommended_runtime="sentence-transformers-compatible embedding service",
        download_command="python scripts/download_small_model.py qwen3-embedding-0.6b",
        notes="Keep separate from the chat model; use it to index business memory and retrieve evidence.",
    ),
    LocalModel(
        key="qwen3-asr-0.6b",
        repo_id="Qwen/Qwen3-ASR-0.6B",
        display_name="Qwen3 ASR 0.6B",
        tasks=("speech_to_text", "meeting_transcription", "voice_notes"),
        size_hint="0.6B parameters; speech recognition specialist",
        license_name="Check official model card",
        official_url="https://huggingface.co/Qwen/Qwen3-ASR-0.6B",
        recommended_runtime="official Qwen ASR runtime / supported inference stack",
        download_command="python scripts/download_small_model.py qwen3-asr-0.6b",
        notes="Use for local transcription before summarisation; verify the model card terms before production use.",
    ),
)


def catalog() -> list[dict[str, Any]]:
    return [asdict(model) for model in LOCAL_MODELS]


def get_model(key: str) -> LocalModel:
    for model in LOCAL_MODELS:
        if model.key == key:
            return model
    raise KeyError(key)


def task_recommendations(task: str) -> list[dict[str, Any]]:
    """Models whose task list contains the requested task (case-insensitive, spaces treated as underscores)."""
    normalised = task.lower().strip().replace(" ", "_").replace("-", "_")
    return [asdict(model) for model in LOCAL_MODELS if normalised in model.tasks]


def local_status(model: LocalModel, root: str = "models") -> dict[str, Any]:
    path = Path(root) / model.key
    return {"key": model.key, "path": str(path), "downloaded": path.exists(), "ready": (path / "config.json").exists()}
