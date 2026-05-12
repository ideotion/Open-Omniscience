"""
Pillar 4: Real-Time Monitoring & Alerting System - Retry Handler

Retry logic for failed operations with exponential backoff.
"""

import time
import asyncio
import random
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable, Tuple, TypeVar, Union
from enum import Enum
import logging


T = TypeVar('T')


class RetryStrategy(Enum):
    FIXED_DELAY = "fixed_delay"
    EXPONENTIAL_BACKOFF = "exponential_backoff"
    LINEAR_BACKOFF = "linear_backoff"
    RANDOM_BACKOFF = "random_backoff"


class RetryCondition(Enum):
    ALWAYS = "always"
    ON_FAILURE = "on_failure"
    ON_EXCEPTION = "on_exception"
    ON_SPECIFIC_EXCEPTION = "on_specific_exception"


@dataclass
class RetryConfig:
    """Configuration for retry logic."""
    max_retries: int = 3
    initial_delay: float = 1.0
    max_delay: float = 60.0
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL_BACKOFF
    backoff_factor: float = 2.0
    jitter: bool = True
    jitter_factor: float = 0.1
    retry_condition: RetryCondition = RetryCondition.ON_FAILURE
    retryable_exceptions: List[type] = field(default_factory=list)
    on_retry: Optional[Callable[[int, Exception, float], None]] = None


@dataclass
class RetryResult:
    """Result of a retry operation."""
    success: bool
    result: Optional[T] = None
    error: Optional[Exception] = None
    retries: int = 0
    total_time: float = 0.0
    last_delay: float = 0.0


class RetryHandler:
    """
    Handles retries for failed operations with configurable strategies.

    Supports:
    - Fixed delay retries
    - Exponential backoff
    - Linear backoff
    - Random backoff with jitter
    - Custom retry conditions
    - Callback on retry attempts
    """

    def __init__(self, config: Optional[RetryConfig] = None):
        """
        Initialize the retry handler.

        Args:
            config: Retry configuration (defaults to reasonable values).
        """
        self.config = config if config else RetryConfig()
        self.logger = logging.getLogger("RetryHandler")

    def _calculate_delay(self, attempt: int) -> float:
        """
        Calculate the delay before the next retry.

        Args:
            attempt: Current attempt number (0-based).

        Returns:
            Delay in seconds.
        """
        if self.config.strategy == RetryStrategy.FIXED_DELAY:
            delay = self.config.initial_delay
        elif self.config.strategy == RetryStrategy.EXPONENTIAL_BACKOFF:
            delay = self.config.initial_delay * (self.config.backoff_factor ** attempt)
        elif self.config.strategy == RetryStrategy.LINEAR_BACKOFF:
            delay = self.config.initial_delay * (attempt + 1)
        elif self.config.strategy == RetryStrategy.RANDOM_BACKOFF:
            delay = random.uniform(
                self.config.initial_delay,
                self.config.initial_delay * (attempt + 1)
            )
        else:
            delay = self.config.initial_delay

        # Apply max delay
        delay = min(delay, self.config.max_delay)

        # Apply jitter
        if self.config.jitter:
            jitter_range = delay * self.config.jitter_factor
            delay = delay + random.uniform(-jitter_range, jitter_range)

        return max(0, delay)

    def _should_retry(self, attempt: int, error: Optional[Exception] = None) -> bool:
        """
        Determine if we should retry based on the configuration.

        Args:
            attempt: Current attempt number.
            error: Exception that occurred (if any).

        Returns:
            True if we should retry, False otherwise.
        """
        # Check if we've exceeded max retries
        if attempt >= self.config.max_retries:
            return False

        # Check retry condition
        if self.config.retry_condition == RetryCondition.ALWAYS:
            return True
        elif self.config.retry_condition == RetryCondition.ON_FAILURE:
            return True  # For sync functions, we assume failure if we're retrying
        elif self.config.retry_condition == RetryCondition.ON_EXCEPTION:
            return error is not None
        elif self.config.retry_condition == RetryCondition.ON_SPECIFIC_EXCEPTION:
            if error is None:
                return False
            return any(isinstance(error, exc) for exc in self.config.retryable_exceptions)

        return False

    def execute(
        self,
        func: Callable[[], T],
        *args,
        **kwargs,
    ) -> RetryResult:
        """
        Execute a function with retry logic (synchronous version).

        Args:
            func: Function to execute.
            *args: Positional arguments for the function.
            **kwargs: Keyword arguments for the function.

        Returns:
            RetryResult with the outcome.
        """
        start_time = time.time()
        last_error = None
        retries = 0
        last_delay = 0.0

        for attempt in range(self.config.max_retries + 1):
            try:
                result = func(*args, **kwargs)
                return RetryResult(
                    success=True,
                    result=result,
                    retries=retries,
                    total_time=time.time() - start_time,
                    last_delay=last_delay,
                )
            except Exception as e:
                last_error = e
                retries += 1

                # Check if we should retry
                if not self._should_retry(attempt, e):
                    break

                # Calculate delay
                delay = self._calculate_delay(attempt)
                last_delay = delay

                # Call on_retry callback
                if self.config.on_retry:
                    self.config.on_retry(attempt, e, delay)

                # Log retry
                self.logger.debug(
                    f"Retry attempt {attempt + 1}/{self.config.max_retries} "
                    f"after {delay:.2f}s delay: {e}"
                )

                # Wait before retrying
                time.sleep(delay)

        return RetryResult(
            success=False,
            error=last_error,
            retries=retries,
            total_time=time.time() - start_time,
            last_delay=last_delay,
        )

    async def execute_async(
        self,
        func: Callable[[], T],
        *args,
        **kwargs,
    ) -> RetryResult:
        """
        Execute an async function with retry logic.

        Args:
            func: Async function to execute.
            *args: Positional arguments for the function.
            **kwargs: Keyword arguments for the function.

        Returns:
            RetryResult with the outcome.
        """
        start_time = time.time()
        last_error = None
        retries = 0
        last_delay = 0.0

        for attempt in range(self.config.max_retries + 1):
            try:
                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(None, func, *args, **kwargs)

                return RetryResult(
                    success=True,
                    result=result,
                    retries=retries,
                    total_time=time.time() - start_time,
                    last_delay=last_delay,
                )
            except Exception as e:
                last_error = e
                retries += 1

                # Check if we should retry
                if not self._should_retry(attempt, e):
                    break

                # Calculate delay
                delay = self._calculate_delay(attempt)
                last_delay = delay

                # Call on_retry callback
                if self.config.on_retry:
                    self.config.on_retry(attempt, e, delay)

                # Log retry
                self.logger.debug(
                    f"Async retry attempt {attempt + 1}/{self.config.max_retries} "
                    f"after {delay:.2f}s delay: {e}"
                )

                # Wait before retrying
                await asyncio.sleep(delay)

        return RetryResult(
            success=False,
            error=last_error,
            retries=retries,
            total_time=time.time() - start_time,
            last_delay=last_delay,
        )

    def execute_with_predicate(
        self,
        func: Callable[[], T],
        predicate: Callable[[T], bool],
        *args,
        **kwargs,
    ) -> RetryResult:
        """
        Execute a function and retry if the predicate is not satisfied.

        Args:
            func: Function to execute.
            predicate: Function that takes the result and returns True if successful.
            *args: Positional arguments for the function.
            **kwargs: Keyword arguments for the function.

        Returns:
            RetryResult with the outcome.
        """
        start_time = time.time()
        last_error = None
        retries = 0
        last_delay = 0.0
        last_result = None

        for attempt in range(self.config.max_retries + 1):
            try:
                last_result = func(*args, **kwargs)

                # Check predicate
                if predicate(last_result):
                    return RetryResult(
                        success=True,
                        result=last_result,
                        retries=retries,
                        total_time=time.time() - start_time,
                        last_delay=last_delay,
                    )
                else:
                    # Predicate not satisfied, treat as failure
                    last_error = ValueError("Predicate not satisfied")
                    retries += 1

            except Exception as e:
                last_error = e
                retries += 1
                last_result = None

            # Check if we should retry
            if retries > 0 and not self._should_retry(attempt, last_error):
                break

            # Calculate delay
            delay = self._calculate_delay(attempt)
            last_delay = delay

            # Call on_retry callback
            if self.config.on_retry:
                self.config.on_retry(attempt, last_error or ValueError("Predicate not satisfied"), delay)

            # Log retry
            self.logger.debug(
                f"Predicate retry attempt {attempt + 1}/{self.config.max_retries} "
                f"after {delay:.2f}s delay"
            )

            # Wait before retrying
            time.sleep(delay)

        return RetryResult(
            success=False,
            result=last_result,
            error=last_error,
            retries=retries,
            total_time=time.time() - start_time,
            last_delay=last_delay,
        )

    def get_config(self) -> RetryConfig:
        """Get the current configuration."""
        return self.config

    def set_config(self, config: RetryConfig) -> None:
        """Set the configuration."""
        self.config = config


# Convenience functions for common retry patterns

def retry_on_exception(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    retryable_exceptions: Optional[List[type]] = None,
) -> Callable:
    """
    Decorator for retrying a function on specific exceptions.

    Args:
        max_retries: Maximum number of retries.
        initial_delay: Initial delay in seconds.
        max_delay: Maximum delay in seconds.
        backoff_factor: Multiplier for exponential backoff.
        jitter: Whether to add random jitter to delays.
        retryable_exceptions: List of exception types to retry on.

    Returns:
        Decorator function.
    """
    if retryable_exceptions is None:
        retryable_exceptions = [Exception]

    config = RetryConfig(
        max_retries=max_retries,
        initial_delay=initial_delay,
        max_delay=max_delay,
        strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
        backoff_factor=backoff_factor,
        jitter=jitter,
        retry_condition=RetryCondition.ON_SPECIFIC_EXCEPTION,
        retryable_exceptions=retryable_exceptions,
    )
    handler = RetryHandler(config)

    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs) -> T:
            result = handler.execute(func, *args, **kwargs)
            if result.success:
                return result.result
            raise result.error if result.error else RuntimeError("Function failed after retries")
        return wrapper

    return decorator


def retry_with_backoff(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
) -> Callable:
    """
    Decorator for retrying a function with exponential backoff.

    Args:
        max_retries: Maximum number of retries.
        initial_delay: Initial delay in seconds.
        max_delay: Maximum delay in seconds.
        backoff_factor: Multiplier for exponential backoff.
        jitter: Whether to add random jitter to delays.

    Returns:
        Decorator function.
    """
    config = RetryConfig(
        max_retries=max_retries,
        initial_delay=initial_delay,
        max_delay=max_delay,
        strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
        backoff_factor=backoff_factor,
        jitter=jitter,
        retry_condition=RetryCondition.ON_EXCEPTION,
    )
    handler = RetryHandler(config)

    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs) -> T:
            result = handler.execute(func, *args, **kwargs)
            if result.success:
                return result.result
            raise result.error if result.error else RuntimeError("Function failed after retries")
        return wrapper

    return decorator
