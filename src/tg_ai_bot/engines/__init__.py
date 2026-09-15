from ..config import EngineConfig
from .base import Engine, Message
from .openai_compat import OpenAICompatEngine
from .anythingllm import AnythingLLMEngine


def build_engine(cfg: EngineConfig) -> Engine:
    if cfg.type == "openai_compat":
        return OpenAICompatEngine(
            name=cfg.name,
            base_url=cfg.params["base_url"],
            api_key=cfg.params["api_key"],
            model=cfg.params["model"],
        )
    if cfg.type == "anythingllm":
        return AnythingLLMEngine(
            url=cfg.params["url"],
            api_key=cfg.params["api_key"],
            workspace=cfg.params["workspace"],
        )
    raise ValueError(f"Unknown engine type: {cfg.type}")


__all__ = ["Engine", "Message", "build_engine"]
