import logging

from .bot import Bot
from .config import load_config
from .engines import build_engine
from .state import State


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram.ext.Application").setLevel(logging.INFO)

    cfg = load_config()
    engines = {name: build_engine(ec) for name, ec in cfg.engines.items()}
    state = State(cfg.redis_url)
    bot = Bot(cfg, state, engines)
    app = bot.build()

    logging.info("Engines: %s", list(engines))
    logging.info("Default engine: %s", cfg.default_engine)

    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
