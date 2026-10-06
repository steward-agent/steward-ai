"""Run the sample store workflows without a card processor."""

from decimal import Decimal

from ecommerce_agent.models import Caller, Intent, Scope, UserRequest
from ecommerce_agent.secrets import MapSecrets
from ecommerce_agent.settings import Settings
from ecommerce_agent.workflow import build_agent


def main() -> None:
    settings = Settings(demo=True, approval_plugin="threshold", auto_approve_below=Decimal("100"))
    secrets = MapSecrets(
        {
            "PLUGIN_PUBLIC_TOKEN": "public-demo-token",
            "PLUGIN_SERVER_TOKEN": "server-demo-token",
        }
    )
    agent = build_agent(settings, secrets=secrets)
    server = Caller(scope=Scope.SERVER)
    public = Caller(scope=Scope.PUBLIC)

    policy = agent.handle(UserRequest(message="What is your return policy?"), public)
    print(policy.outcome.value)
    print(policy.message)
    print()

    refund = agent.handle(
        UserRequest(
            message="I want to return my headphones",
            order_id="1001",
            customer_ref="cust_1",
            order_access=True,
            idempotency_key="demo-refund-1001",
        ),
        public,
    )
    print(refund.outcome.value)
    print(refund.message)
    print()

    settlement = agent.handle(UserRequest(message="reconcile payouts", intent=Intent.SETTLEMENT), server)
    print(settlement.outcome.value)
    print(settlement.message)
    print()

    quote = agent.handle(UserRequest(message="Quote 80 USD in EUR"), public)
    print(quote.outcome.value)
    print(quote.message)
    print()
    print(agent.observability.snapshot()["signals"])


if __name__ == "__main__":
    main()
