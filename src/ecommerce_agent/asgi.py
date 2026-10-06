"""ASGI entrypoint. Tokens and provider secrets are read from the environment."""

from ecommerce_agent.api import create_api
from ecommerce_agent.gateway import Gateway
from ecommerce_agent.logging import configure_logging
from ecommerce_agent.secrets import EnvSecrets
from ecommerce_agent.settings import load_settings
from ecommerce_agent.workflow import build_agent

configure_logging()
settings = load_settings()
secrets = EnvSecrets()
agent = build_agent(settings, secrets=secrets)
gateway = Gateway(settings, secrets)
app = create_api(agent, gateway)
