"""SafeLab-Agent.

An agent package that plugs into the BSLBench platform as the backend provider
``"safelab"``. The platform stays the environment and the evaluator; this
package only decides which action to return each turn.

Importing ``safelab`` has no side effects and does not need the platform.
Registration is explicit: call ``safelab.bench.register()`` (the launch scripts
under ``scripts/`` do this) before the platform creates its backend.
"""

__version__ = "0.1.0"
