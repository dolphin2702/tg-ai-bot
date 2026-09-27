from ..config import EngineConfig
from .base import Engine, EngineUnavailable, Message
from .openai_compat import OpenAICompatEngine
from .anythingllm import AnythingLLMEngine


def build_engine(cfg: EngineConfig) -> Engine:
    if cfg.type == "openai_compat":
        return OpenAICompatEngine(
            name=cfg.name,
            base_url=cfg.params["base_url"],
            api_key=cfg.params["api_key"],
            models=cfg.params["models"],
        )
    if cfg.type == "anythingllm":
        return AnythingLLMEngine(
            url=cfg.params["url"],
            api_key=cfg.params["api_key"],
            workspace=cfg.params["workspace"],
        )
    raise ValueError(f"Unknown engine type: {cfg.type}")


__all__ = ["Engine", "EngineUnavailable", "Message", "build_engine"]
