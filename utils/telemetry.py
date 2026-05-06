"""
Telemetry utility for tracking system health, request latency, and resource usage.
Separate from business analytics, focusing on system reliability.
"""
import time
import functools
from typing import Callable, Any
from utils.logger import get_logger

logger = get_logger(__name__)

class TelemetryTracker:
    @staticmethod
    def track_latency(operation_name: str) -> Callable:
        """Decorator to track execution time of operations."""
        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            def wrapper(*args, **kwargs) -> Any:
                start_time = time.time()
                try:
                    result = func(*args, **kwargs)
                    latency = time.time() - start_time
                    logger.info(f"TELEMETRY: Operation '{operation_name}' completed in {latency:.4f} seconds")
                    return result
                except Exception as e:
                    latency = time.time() - start_time
                    logger.error(f"TELEMETRY: Operation '{operation_name}' failed after {latency:.4f} seconds. Error: {str(e)}", exc_info=True)
                    raise
            return wrapper
        return decorator

    @staticmethod
    def record_event(event_name: str, details: dict = None) -> None:
        """Record a generic telemetry event."""
        log_details = f" | Details: {details}" if details else ""
        logger.info(f"TELEMETRY: Event '{event_name}'{log_details}")

telemetry = TelemetryTracker()
