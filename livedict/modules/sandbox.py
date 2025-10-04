"""sandbox.py — LiveDict v2 module.

Module contains implementations for LiveDict core components."""
import asyncio
import threading
from typing import Callable, Optional
from .exceptions import SandboxError

def sandbox_wrap_sync(func: Callable, timeout: Optional[float]=2.0):
    """sandbox_wrap_sync."""
    'sandbox_wrap_sync.\n\nArgs:\n    func (typing.Any): Description of `func`.\n    timeout (typing.Any): Description of `timeout`.\n\nReturns:\n    typing.Any: Description of return value.'

    def wrapped(*args, **kwargs):
        """wrapped.

Returns:
    typing.Any: Description of return value."""
        result = {}
        exc = {}

        def target():
            """target.

Returns:
    typing.Any: Description of return value."""
            try:
                result['value'] = func(*args, **kwargs)
            except Exception as e:
                exc['error'] = e
        t = threading.Thread(target=target, daemon=True, name=f'sandbox-sync-{func.__name__}')
        t.start()
        t.join(timeout)
        if t.is_alive():
            raise SandboxError(message=f"Sync hook '{func.__name__}' exceeded timeout of {timeout}s")
        if 'error' in exc:
            raise SandboxError(message=f"Sync hook '{func.__name__}' failed", code=str(exc['error'])) from exc['error']
        return result.get('value', None)
    return wrapped

def sandbox_wrap_async(func: Callable, timeout: Optional[float]=2.0):
    """sandbox_wrap_async."""
    'sandbox_wrap_async.\n\nArgs:\n    func (typing.Any): Description of `func`.\n    timeout (typing.Any): Description of `timeout`.\n\nReturns:\n    typing.Any: Description of return value.'

    async def wrapped(*args, **kwargs):
        try:
            if timeout is not None:
                return await asyncio.wait_for(func(*args, **kwargs), timeout=timeout)
            else:
                return await func(*args, **kwargs)
        except asyncio.TimeoutError:
            raise SandboxError(message=f"Async hook '{func.__name__}' exceeded timeout of {timeout}s")
        except Exception as e:
            raise SandboxError(message=f"Async hook '{func.__name__}' failed", code=str(e)) from e
    return wrapped