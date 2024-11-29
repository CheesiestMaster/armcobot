import re
import os
from functools import lru_cache, wraps
from inspect import Signature
from sqlalchemy.orm import scoped_session

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

    # Compile and return the regex pattern
    return re.compile(
        rf"https?:\/\/(?:[\w.-]+\.)?(?!\b(?:{allowed_domains_regex})\b)\S+"
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
    return bool(pattern.search(text))

class RollbackException(Exception):
    pass

def uses_db(sessionmaker):
    session_scope = scoped_session(sessionmaker)
    def decorator(func):
        original_signature = Signature.from_callable(func)
        new_params = [param for name, param in original_signature.parameters.items() if name != "session"]
        new_signature = original_signature.replace(parameters=new_params)
        @wraps(func)
        async def wrapper(*args, **kwargs): 
            with session_scope() as session: # we are not currently using async with, because the sessionmaker is not async yet
                try:
                    result = await func(*args, session=session, **kwargs)
                    session.commit()
                    return result
                except RollbackException:
                    session.rollback()
                    return None
                except Exception as e:
                    session.rollback()
                    raise e
        wrapper.__signature__ = new_signature
        return wrapper
    return decorator