"""synclivedict.py — LiveDict v2 module.

Module contains implementations for LiveDict core components."""
from .livedict import LiveDict as _LD

class _SyncLiveDict(_LD):
    """_SyncLiveDict."""
    '_SyncLiveDict class.\n\nThis class provides the core functionality for ... (fill in with specific behaviour).\n\nAttributes:\n    TODO (typing): describe important attributes.\n\nExample:\n    >>> obj = _SyncLiveDict()'

    def __init__(self, *args, **kwargs):
        kwargs['work_mode'] = 'sync'
        super().__init__(*args, **kwargs)