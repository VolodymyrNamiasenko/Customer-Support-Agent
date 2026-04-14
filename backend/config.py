from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = str(BASE_DIR / "uploads")
CHROMA_PERSIST_DIR = str(BASE_DIR / "rag_dbs" / "support_chroma_db")
DOCUMENT_REGISTRY = str(BASE_DIR / "document_registry.json")
OPTIMIZED_PROGRAM_PATH = str(BASE_DIR / "optimized_pulse_agent.json")

# Embedding
EMBEDDING_MODEL = "sentence-transformers/all-mpnet-base-v2"

# Chunking
CHUNK_SIZE = 800
CHUNK_OVERLAP = 250
HEADERS_TO_SPLIT_ON = [
    ("#", "Chapter"),
    ("##", "Section"),
    ("###", "Subsection"),
    ("####", "Step"),
]
SEPARATORS = ["\n\n", "\n", ". ", " → ", "System path:", "(", ")"]

# LLM (Ollama)
OLLAMA_BASE_URL = "http://localhost:11434"
MODEL_NAME = "ollama_chat/llama3.2:3b"
DEFAULT_K = 5
DEFAULT_TEMPERATURE = 0.1
DEFAULT_MAX_TOKENS = 512

# Allowed file types
ALLOWED_EXTENSIONS = {".docx", ".pdf", ".md"}
