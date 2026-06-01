from __future__ import annotations

import asyncio
import functools
import logging
from typing import Any, Callable, Tuple, Type

import httpx

logger = logging.getLogger(__name__)

# Errors that should NOT be retried — they indicate a permanent problem.
_PERMANENT_HTTP_CODES = {400, 401, 403, 404}


def async_retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    exceptions: Tuple[Type[BaseException], ...] = (Exception,),
) -> Callable:
    """
    Decorator: retry an async function on transient errors with exponential back-off.

    Permanent OpenAI errors (4xx) are re-raised immediately without retrying.
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_error: BaseException | None = None
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except httpx.HTTPStatusError as error:
                    if error.response.status_code in _PERMANENT_HTTP_CODES:
                        raise  # do not retry permanent errors
                    last_error = error
                except exceptions as error:
                    last_error = error

                if attempt < max_attempts - 1:
                    delay = base_delay * (2**attempt)
                    logger.warning(
                        "%s attempt %d/%d failed: %s. Retrying in %.1fs…",
                        func.__name__,
                        attempt + 1,
                        max_attempts,
                        last_error,
                        delay,
                    )
                    await asyncio.sleep(delay)

            assert last_error is not None
            raise last_error

        return wrapper

    return decorator
