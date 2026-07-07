"""HF code embedding function. Heavy imports allowed here."""
import os

def _maybe_enable_amd_wsl2_gpu():
    """Set HSA_ENABLE_DXG_DETECTION=1 if running on WSL2 with AMD GPU exposed via /dev/dxg."""
    if os.path.exists('/dev/dxg') and 'HSA_ENABLE_DXG_DETECTION' not in os.environ:
        os.environ['HSA_ENABLE_DXG_DETECTION'] = '1'

_maybe_enable_amd_wsl2_gpu()

import psutil

from chromadb.utils.embedding_functions import EmbeddingFunction

_CODERANK_QUERY_PREFIX = "Represent this query for searching relevant code: "

# Global cache for the embedding model
_EMB_MODEL_CACHE = {}


class HFCodeEmbeddingFunction(EmbeddingFunction):
    def __init__(self, model_name, device=None):
        self.model_name = model_name

        if model_name in _EMB_MODEL_CACHE:
            self._st_model = _EMB_MODEL_CACHE[model_name]
            return

        print(f"Loading model: {model_name}")
        from sentence_transformers import SentenceTransformer
        st_model = SentenceTransformer(model_name, trust_remote_code=True, device=device)
        st_model.max_seq_length = 512
        print(f"  Device: {st_model.device}")
        self._st_model = st_model
        _EMB_MODEL_CACHE[model_name] = st_model

    def _choose_safe_batch_size(self, max_batch=64, safety_margin_gb=2.0):
        try:
            avail = psutil.virtual_memory().available / 1e9
        except Exception:
            avail = 4.0

        batch = max_batch
        while batch > 1:
            needed = 1.2 + batch * 0.18
            if needed + safety_margin_gb < avail:
                return batch
            batch //= 2
        return 1

    def embed(self, texts, show_progress=False):
        """Embed texts for indexing (no query prefix)."""
        if isinstance(texts, str):
            texts = [texts]

        batch_size = self._choose_safe_batch_size()
        print(f"Embedding batch size: {batch_size}")
        return self._st_model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=show_progress,
            convert_to_numpy=True,
        )

    def __call__(self, texts):
        """Called by ChromaDB at query time — adds query prefix."""
        if isinstance(texts, str):
            texts = [texts]
        prefixed = [_CODERANK_QUERY_PREFIX + t for t in texts]
        return self._st_model.encode(prefixed, convert_to_numpy=True)
