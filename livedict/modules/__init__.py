import warnings

warnings.warn(
    "LiveDict is discontinued and has been renamed to NimbusKV. "
    "Please install `nimbuskv` and use `from nimbuskv import NimbusKV`.",
    DeprecationWarning,
    stacklevel=2,
)