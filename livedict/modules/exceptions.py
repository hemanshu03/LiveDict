"""exceptions.py — LiveDict v2 module.

Module contains implementations for LiveDict core components."""

class LiveDictError(Exception):
    """LiveDictError."""
    'LiveDictError class.\n\nThis class provides the core functionality for ... (fill in with specific behaviour).\n\nAttributes:\n    TODO (typing): describe important attributes.\n\nExample:\n    >>> obj = LiveDictError()'

    def __init__(self, message=None, **context):
        self.message = message or 'An error occurred in LiveDict.'
        self.context = context
        super().__init__(self.message)

    def __str__(self):
        ctx = ', '.join((f'{k}={v!r}' for k, v in self.context.items()))
        return f'{self.message}' + (f' | Context: {ctx}' if ctx else '')

class LockedKeyError(LiveDictError):
    """LockedKeyError."""
    'LockedKeyError class.\n\nThis class provides the core functionality for ... (fill in with specific behaviour).\n\nAttributes:\n    TODO (typing): describe important attributes.\n\nExample:\n    >>> obj = LockedKeyError()'
    pass

class SandboxError(LiveDictError):
    """SandboxError."""
    'SandboxError class.\n\nThis class provides the core functionality for ... (fill in with specific behaviour).\n\nAttributes:\n    TODO (typing): describe important attributes.\n\nExample:\n    >>> obj = SandboxError()'
    pass