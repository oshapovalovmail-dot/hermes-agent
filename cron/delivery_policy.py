"""Profile-scoped policy for cron failure notifications (not run persistence)."""
import logging

logger = logging.getLogger(__name__)


def deliver_errors() -> bool:
    from cron.scheduler import load_config
    from hermes_cli.config_backend import ConfigBackendUnavailable
    from utils import is_truthy_value

    try:
        value = (load_config().get("cron") or {}).get("deliver_errors", True)
        return is_truthy_value(value, default=True)
    except (Exception, ConfigBackendUnavailable) as exc:
        logger.warning("Failed to read cron.deliver_errors; preserving error delivery: %s", type(exc).__name__, exc_info=True)
        return True
