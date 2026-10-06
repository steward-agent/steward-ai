"""Errors whose messages are safe to log and return."""


class EcommerceAgentError(Exception):
    """Base error for this package."""


class PluginConfigError(EcommerceAgentError):
    """The merchant's plugin configuration is incomplete."""


class ToolError(EcommerceAgentError):
    """A payment or commerce call failed. The message must not include secrets."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        rate_limited: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.rate_limited = rate_limited


class Unauthorized(EcommerceAgentError):
    """The caller did not present a known plugin token."""


class Forbidden(EcommerceAgentError):
    """The caller's token cannot perform this action."""


class RateLimited(EcommerceAgentError):
    """The gateway rejected the call because the merchant's limit was reached."""

    def __init__(self, retry_after: int) -> None:
        super().__init__("rate_limited")
        self.retry_after = retry_after
