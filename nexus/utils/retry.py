import asyncio
import functools
import time
from typing import Any, Callable, Tuple, Type, TypeVar, cast
from nexus.utils.logger import get_logger

logger = get_logger("retry_decorator")

# Define generic type variable for callable functions
F = TypeVar("F", bound=Callable[..., Any])


def retry(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    exponential_base: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
) -> Callable[[F], F]:
    """Asynchronous decorator to retry a function call with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts.
        initial_delay: Delay before the first retry attempt in seconds.
        exponential_base: Multiplier base for calculating subsequent delays.
        exceptions: Tuple of exception types to catch and retry on.

    Returns:
        Callable: The decorated async function.
    """

    def decorator(func: F) -> F:
        if not asyncio.iscoroutinefunction(func):
            raise TypeError(f"Decorator @retry can only be used on async functions. Function '{func.__name__}' is sync.")

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            attempt = 1
            delay = initial_delay

            while True:
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:
                    if attempt > max_retries:
                        logger.error(
                            "All retry attempts exhausted",
                            func_name=func.__name__,
                            attempt=attempt,
                            max_retries=max_retries,
                            exception=str(exc),
                        )
                        raise exc

                    logger.warning(
                        "Async function call failed, retrying...",
                        func_name=func.__name__,
                        attempt=attempt,
                        next_retry_delay_seconds=round(delay, 2),
                        exception=type(exc).__name__,
                        error_message=str(exc),
                    )

                    await asyncio.sleep(delay)
                    attempt += 1
                    delay *= exponential_base

        return cast(F, wrapper)

    return decorator
