from pathlib import Path
import os
import sys

sys.path.insert(0, "src")
os.chdir(Path(__file__).resolve().parents[1])

from rag_agent.config import get_settings

print("cwd", Path.cwd())
print("env EMBEDDING_MODEL=", repr(os.environ.get("EMBEDDING_MODEL")))
print(".env line:", [l for l in Path(".env").read_text(encoding="utf-8").splitlines() if "EMBEDDING_MODEL" in l])
s = get_settings()
print("loaded", s.embedding_model, s.embedding_dims)
