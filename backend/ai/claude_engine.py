"""Compatibility wrapper for older imports.

SudoBrain now uses `backend.ai.local_llm_engine` for local reasoning engine/Ollama reasoning.
This module remains so existing call sites can migrate incrementally.
"""

from backend.ai.local_llm_engine import ask, ask_with_knowledge, extract_knowledge, load_identity

__all__ = ["ask", "ask_with_knowledge", "extract_knowledge", "load_identity"]
