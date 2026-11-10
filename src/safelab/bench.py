"""Locate the BSLBench platform and register SafeLab as a backend provider.

The platform is a separate, private repository. SafeLab never copies or edits
it: it puts the platform on ``sys.path`` and registers one builder under the
provider name ``"safelab"`` through the platform's public
``agent_interface.backends.register_backend``. Both platform entry points
(``run_agent.py`` for the dry run, ``main.py --agent`` for the simulator)
create their backend with ``create_backend``, so registering in the same
process before calling them is all the integration there is.

The platform root comes from the environment variable ``SAFELAB_BENCH_ROOT``,
falling back to the development machine's checkout.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ENV_VAR = "SAFELAB_BENCH_ROOT"
DEFAULT_ROOT = Path(r"D:\科学具身仿真\Benchmark\bench")
PROVIDER = "safelab"


class BenchNotFound(RuntimeError):
    """The platform checkout is not where SAFELAB_BENCH_ROOT says it is."""


def root():
    value = os.environ.get(ENV_VAR)
    return Path(value).expanduser() if value else DEFAULT_ROOT


def available(path=None):
    """Whether a usable platform checkout is at ``path`` (default: ``root()``)."""
    path = Path(path) if path is not None else root()
    return ((path/"src"/"agent_interface"/"__init__.py").is_file()
            and (path/"run_agent.py").is_file() and (path/"main.py").is_file())


def ensure_importable(path=None):
    """Put the platform's packages on ``sys.path``; return the platform root."""
    path = (Path(path) if path is not None else root()).resolve()
    if not available(path):
        raise BenchNotFound(
            f"No BSLBench checkout at {path}. Set {ENV_VAR} to the platform's root "
            "directory (the one containing run_agent.py and src/agent_interface).")
    # Appended, not prepended: nothing in this repository may shadow a platform
    # module, and nothing in the platform may shadow ours.
    for entry in (path/"src", path):
        if str(entry) not in sys.path:
            sys.path.append(str(entry))
    return path


def register(path=None):
    """Register provider ``"safelab"`` with the platform. Safe to call repeatedly."""
    ensure_importable(path)
    from agent_interface.backends import backend_providers, register_backend
    if PROVIDER not in backend_providers():
        register_backend(PROVIDER, _build)
    return PROVIDER


def _build(spec, *, api_key=None, context=None):
    from .backend import SafeLabBackend
    return SafeLabBackend(spec, api_key=api_key, context=context)
