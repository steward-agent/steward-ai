"""Run the merchant's agent API."""

from ecommerce_agent.logging import configure_logging, get_logger
from ecommerce_agent.settings import load_settings


def main() -> None:
    import uvicorn

    configure_logging()
    settings = load_settings()
    logger = get_logger()
    if settings.demo:
        logger.warning("Demo mode is on. It seeds a sample order and must stay off in production.")
    uvicorn.run(
        "ecommerce_agent.asgi:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
