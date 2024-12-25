import re
import os
from functools import lru_cache, wraps
from inspect import Signature
from sqlalchemy.orm import scoped_session
from logging import getLogger
import asyncio
from collections import deque
from typing import Coroutine
logger = getLogger(__name__)

@lru_cache(maxsize=1)
def get_url_pattern() -> re.Pattern:
    """
    Lazily initializes and caches the regex pattern for matching invalid URLs
    based on a comma-separated list of allowed domains in an environment variable.

    Returns:
        re.Pattern: Compiled regex pattern for detecting invalid URLs.
    """
    # Get the allowed domains from the environment variable
    allowed_domains = os.getenv("ALLOWED_DOMAINS", "")
    allowed_domains_list = [domain.strip() for domain in allowed_domains.split(",") if domain.strip()]
    allowed_domains_regex = "|".join(re.escape(domain) for domain in allowed_domains_list)

    if not allowed_domains:
        return re.compile("(?=a)b") # dummy pattern that matches nothing, just to prevent any errors

    # Compile and returwn the regex pattern
    logger.info(rf"domains: https?:\/\/(?!{allowed_domains_regex})(?:[\w.-]+\.\w+)(?:\/\S*)?")
    return re.compile(
        rf"https?:\/\/(?!{allowed_domains_regex})(?:[\w.-]+\.\w+)(?:\/\S*)?"
    )

def has_invalid_url(text: str) -> bool:
    """
    Checks if a string contains any URL that does not belong to the allowed domains.

    Args:
        text (str): The string to check.

    Returns:
        bool: True if an invalid URL exists, False otherwise.
    """
    pattern = get_url_pattern()
    result = pattern.search(text)
    logger.info(f"has_invalid_url result: {result}")
    return bool(result)

class RollbackException(Exception):
    pass

def uses_db(sessionmaker):
    session_scope = scoped_session(sessionmaker)
    def decorator(func):
        logger.debug(f"decorating {func.__name__}")
        original_signature = Signature.from_callable(func)
        new_params = [param for name, param in original_signature.parameters.items() if name != "session"]
        new_signature = original_signature.replace(parameters=new_params)
        @wraps(func)
        async def wrapper(*args, **kwargs): 
            with session_scope() as session: # we are not currently using async with, because the sessionmaker is not async yet
                try:
                    logger.debug(f"calling {func.__name__}")
                    result = await func(*args, session=session, **kwargs)
                    logger.debug(f"commiting session for {func.__name__}")
                    session.commit()
                    logger.debug(f"committed session for {func.__name__}")
                    return result
                except RollbackException:
                    logger.debug(f"rolling back session for {func.__name__}")
                    session.rollback()
                    logger.debug(f"rolled back session for {func.__name__}")
                    return None
                except Exception as e:
                    logger.debug(f"rolling back session for {func.__name__} due to unhandled exception")
                    session.rollback()
                    logger.debug(f"rolled back session for {func.__name__} due to unhandled exception")
                    raise e
        wrapper.__signature__ = new_signature
        return wrapper
    return decorator


def string_to_list(string: str) -> list[str]:
    if "\n" in string[:40]:
        string = set(string.split("\n"))
    else:
        string = set(string.split(","))
    string = [name.strip() for name in string]
    return string

class RollingCounter:
    def __init__(self, duration: int):
        """
        Initializes the RollingCounter with a specified duration and event loop.

        :param duration: Duration in seconds to keep each increment active. Must be > 0.
        :param loop: Optional asyncio event loop to use. Defaults to asyncio.get_event_loop().
        """
        if duration <= 0:
            raise ValueError("Duration must be greater than 0.")
        self.duration = duration
        self.counter = 0
        self.tasks = deque()

    async def _decrement_after_delay(self):
        """Waits for the specified duration, then decrements the counter."""
        await asyncio.sleep(self.duration)
        self.counter -= 1
        self.tasks.popleft()  # Remove the completed task from the queue

    def set(self):
        """
        Increments the counter and schedules a task to decrement it after the duration.
        """
        self.counter += 1
        task = asyncio.create_task(self._decrement_after_delay())
        self.tasks.append(task)

    def get(self) -> int:
        """
        Returns the current value of the counter.
        """
        return self.counter

    def average(self) -> float:
        """
        Returns the average number of increments per second over the duration.

        :return: Average value (counter / duration)
        """
        return self.counter / self.duration

    def __str__(self):
        return str(self.counter) # make it easy to use in templates
    
    def __repr__(self):
        return f"RollingCounter(duration={self.duration}, counter={self.counter})"

class RollingCounterDict:
    def __init__(self, duration: int):
        """
        Initializes a RollingCounterDict with a specified duration for each counter.

        :param duration: Duration in seconds for each RollingCounter. Must be > 0.
        :param loop: Optional asyncio event loop to use. Defaults to asyncio.get_event_loop().
        """
        if duration <= 0:
            raise ValueError("Duration must be greater than 0.")
        self.duration = duration
        self.counters = {}

    def set(self, key: str):
        """
        Increments the counter for the given key, initializing it if it doesn't exist.

        :param key: The key for the counter to increment.
        """
        if key not in self.counters:
            self.counters[key] = RollingCounter(self.duration)
        self.counters[key].set()

    def get(self, key: str) -> int:
        """
        Returns the current value of the counter for the given key, or 0.0 as a sentinel if the key doesn't exist.

        :param key: The key for the counter.
        :return: The current value of the counter or 0.0.
        """
        if key in self.counters:
            return self.counters[key].get()
        return float(0)

    def __setitem__(self, key: str, _: None):
        """
        Increments the counter for the given key, initializing it if it doesn't exist.

        :param key: The key for the counter to increment.
        """
        self.set(key)

    def __getitem__(self, key: str) -> int:
        """
        Returns the current value of the counter for the given key, or 0.0 as a sentinel if the key doesn't exist.

        :param key: The key for the counter.
        :return: The current value of the counter or 0.0.
        """
        return self.get(key)
    
def chunk_list(lst: list, chunk_size: int) -> list[list]:
    """Splits a list into chunks of specified size."""
    if chunk_size <= 0:
        raise ValueError("Chunk size must be greater than 0")
    
    # Create chunks for all but the last chunk
    chunks = [lst[i:i + chunk_size] for i in range(0, len(lst) - len(lst) % chunk_size, chunk_size)]
    
    # Handle the last chunk if there are remaining elements
    if len(lst) % chunk_size != 0:
        chunks.append(lst[-(len(lst) % chunk_size):])
    
    return chunks

class Paginator:
    # a bidirectional iterator over a list of items, with a constrained view size
    def __init__(self, items: list, view_size: int):
        self.items = chunk_list(items, view_size)
        self.index = 0

    def __iter__(self):
        return self
    
    def next(self, is_iter: bool = False):
        if self.index >= len(self.items):
            if is_iter:
                raise StopIteration
            else:
                return self.items[self.index] # bump off the end and return the same item
        result = self.items[self.index]
        self.index += 1
        return result
    
    def previous(self):
        if self.index == 0:
            return self.items[self.index]
        self.index -= 1
        return self.items[self.index]
    
    def __next__(self):
        return self.next(True)
    
    def current(self):
        return self.items[self.index]
    
    def has_next(self):
        return self.index < len(self.items) - 1 # don't show the next button if we're at the end
    
    def has_previous(self):
        return self.index > 0
    
    def __len__(self):
        return len(self.items)
    
async def callback_listener(callback: Coroutine, bind:str):
    address, port = bind.split(":")

    async def listener(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            await callback()
            writer.write(b"200 OK") # just send a 200 ok response, not with any proper headers, since nc doesn't care about them
            await writer.drain()
        except Exception as e:
            logger.error(f"Error in callback_listener: {e}")
            writer.write(b"500 Internal Server Error")
            await writer.drain()
        finally:
            writer.close()

    server = await asyncio.start_server(listener, address, port)
    await server.serve_forever()
