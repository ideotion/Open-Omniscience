"""
Retry Utility

Provides retry functionality with exponential backoff for web requests.
"""

import asyncio
import time
import random
from typing import Callable, Any, Optional, Tuple, List
from functools import wraps
import logging

# Configure logging
logger = logging.getLogger(__name__)


class RetryError(Exception):
    """Exception raised when all retry attempts fail."""
    
    def __init__(self, message: str, last_exception: Optional[Exception] = None):
        """
        Initialize RetryError.
        
        Args:
            message: Error message
            last_exception: The last exception that was raised
        """
        super().__init__(message)
        self.last_exception = last_exception


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retry_on: Tuple[type, ...] = (Exception,),
    retry_if: Optional[Callable[[Exception], bool]] = None,
) -> Callable[[Callable], Callable]:
    """
    Decorator for retrying a function with exponential backoff.
    
    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Base delay between retries in seconds
        max_delay: Maximum delay between retries in seconds
        exponential_base: Base for exponential backoff
        jitter: Whether to add random jitter to delays
        retry_on: Tuple of exception types to retry on
        retry_if: Optional function to determine if an exception should be retried
        
    Returns:
        Decorated function
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except retry_on as e:
                    last_exception = e
                    
                    # Check if we should retry this exception
                    if retry_if and not retry_if(e):
                        raise
                    
                    # Don't retry on the last attempt
                    if attempt >= max_retries:
                        break
                    
                    # Calculate delay
                    delay = min(
                        base_delay * (exponential_base ** attempt),
                        max_delay
                    )
                    
                    # Add jitter
                    if jitter:
                        delay = delay * (0.5 + random.random())
                    
                    logger.warning(
                        f"Attempt {attempt + 1}/{max_retries + 1} failed for {func.__name__}: {e}. "
                        f"Retrying in {delay:.2f} seconds..."
                    )
                    
                    time.sleep(delay)
            
            # All retries failed
            raise RetryError(
                f"All {max_retries + 1} attempts failed for {func.__name__}",
                last_exception
            )
        
        return wrapper
    
    return decorator


def async_retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retry_on: Tuple[type, ...] = (Exception,),
    retry_if: Optional[Callable[[Exception], bool]] = None,
) -> Callable[[Callable], Callable]:
    """
    Decorator for retrying an async function with exponential backoff.
    
    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Base delay between retries in seconds
        max_delay: Maximum delay between retries in seconds
        exponential_base: Base for exponential backoff
        jitter: Whether to add random jitter to delays
        retry_on: Tuple of exception types to retry on
        retry_if: Optional function to determine if an exception should be retried
        
    Returns:
        Decorated async function
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except retry_on as e:
                    last_exception = e
                    
                    # Check if we should retry this exception
                    if retry_if and not retry_if(e):
                        raise
                    
                    # Don't retry on the last attempt
                    if attempt >= max_retries:
                        break
                    
                    # Calculate delay
                    delay = min(
                        base_delay * (exponential_base ** attempt),
                        max_delay
                    )
                    
                    # Add jitter
                    if jitter:
                        delay = delay * (0.5 + random.random())
                    
                    logger.warning(
                        f"Attempt {attempt + 1}/{max_retries + 1} failed for {func.__name__}: {e}. "
                        f"Retrying in {delay:.2f} seconds..."
                    )
                    
                    await asyncio.sleep(delay)
            
            # All retries failed
            raise RetryError(
                f"All {max_retries + 1} attempts failed for {func.__name__}",
                last_exception
            )
        
        return wrapper
    
    return decorator


class RetryStrategy:
    """
    Configurable retry strategy.
    
    Provides more control over retry behavior with customizable parameters.
    """
    
    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
        retry_on: Optional[Tuple[type, ...]] = None,
        retry_if: Optional[Callable[[Exception], bool]] = None,
    ):
        """
        Initialize retry strategy.
        
        Args:
            max_retries: Maximum number of retry attempts
            base_delay: Base delay between retries in seconds
            max_delay: Maximum delay between retries in seconds
            exponential_base: Base for exponential backoff
            jitter: Whether to add random jitter to delays
            retry_on: Tuple of exception types to retry on
            retry_if: Optional function to determine if an exception should be retried
        """
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.retry_on = retry_on or (Exception,)
        self.retry_if = retry_if
    
    def calculate_delay(self, attempt: int) -> float:
        """
        Calculate delay for a given attempt.
        
        Args:
            attempt: Current attempt number (0-indexed)
            
        Returns:
            Delay in seconds
        """
        delay = min(
            self.base_delay * (self.exponential_base ** attempt),
            self.max_delay
        )
        
        if self.jitter:
            delay = delay * (0.5 + random.random())
        
        return delay
    
    def should_retry(self, exception: Exception, attempt: int) -> bool:
        """
        Determine if a retry should be attempted.
        
        Args:
            exception: The exception that was raised
            attempt: Current attempt number (0-indexed)
            
        Returns:
            True if retry should be attempted, False otherwise
        """
        # Don't retry if we've exhausted all attempts
        if attempt >= self.max_retries:
            return False
        
        # Check if exception is in retry_on list
        if not isinstance(exception, self.retry_on):
            return False
        
        # Check custom retry_if function
        if self.retry_if and not self.retry_if(exception):
            return False
        
        return True
    
    def execute(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """
        Execute a function with retry logic.
        
        Args:
            func: Function to execute
            *args: Positional arguments for the function
            **kwargs: Keyword arguments for the function
            
        Returns:
            Result of the function
            
        Raises:
            RetryError: If all retry attempts fail
        """
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                
                if not self.should_retry(e, attempt):
                    raise
                
                delay = self.calculate_delay(attempt)
                logger.warning(
                    f"Attempt {attempt + 1}/{self.max_retries + 1} failed: {e}. "
                    f"Retrying in {delay:.2f} seconds..."
                )
                
                time.sleep(delay)
        
        raise RetryError(
            f"All {self.max_retries + 1} attempts failed",
            last_exception
        )
    
    async def async_execute(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """
        Execute an async function with retry logic.
        
        Args:
            func: Async function to execute
            *args: Positional arguments for the function
            **kwargs: Keyword arguments for the function
            
        Returns:
            Result of the function
            
        Raises:
            RetryError: If all retry attempts fail
        """
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                
                if not self.should_retry(e, attempt):
                    raise
                
                delay = self.calculate_delay(attempt)
                logger.warning(
                    f"Attempt {attempt + 1}/{self.max_retries + 1} failed: {e}. "
                    f"Retrying in {delay:.2f} seconds..."
                )
                
                await asyncio.sleep(delay)
        
        raise RetryError(
            f"All {self.max_retries + 1} attempts failed",
            last_exception
        )


# Pre-configured retry strategies
DEFAULT_RETRY = RetryStrategy()
AGGRESSIVE_RETRY = RetryStrategy(
    max_retries=5,
    base_delay=0.5,
    max_delay=30.0,
    exponential_base=2.0,
)
CONSERVATIVE_RETRY = RetryStrategy(
    max_retries=2,
    base_delay=2.0,
    max_delay=10.0,
    exponential_base=1.5,
)


if __name__ == "__main__":
    # Test the retry functionality
    import logging
    logging.basicConfig(level=logging.INFO)
    
    # Test synchronous retry
    @retry_with_backoff(max_retries=3, base_delay=0.5)
    def flaky_function():
        import random
        if random.random() < 0.7:
            raise ValueError("Temporary failure")
        return "Success!"
    
    print("Testing synchronous retry...")
    try:
        result = flaky_function()
        print(f"Result: {result}")
    except RetryError as e:
        print(f"Failed after retries: {e}")
    
    # Test asynchronous retry
    @async_retry_with_backoff(max_retries=3, base_delay=0.5)
    async def async_flaky_function():
        import random
        if random.random() < 0.7:
            raise ValueError("Temporary failure")
        return "Async Success!"
    
    print("\nTesting asynchronous retry...")
    async def test_async():
        try:
            result = await async_flaky_function()
            print(f"Result: {result}")
        except RetryError as e:
            print(f"Failed after retries: {e}")
    
    asyncio.run(test_async())
