"""Sidekick - voice-first intelligent companion.

This package owns the *core brain*: intent resolution, safety policy, session
orchestration and the stable request/action contract consumed by the execution
layer (Agent 2) and the voice/UI layer (Agent 3).

Module map:

- :mod:`sidekick.core.schemas`   - contract v1 request/response models
- :mod:`sidekick.core.catalog`   - capability catalog (tools, arguments, risk)
- :mod:`sidekick.core.registry`  - tool registry + adapter protocol
- :mod:`sidekick.core.sessions`  - session scoped state store
- :mod:`sidekick.core.tasks`     - action lifecycle / task orchestration
- :mod:`sidekick.core.safety`    - deterministic safety policy
- :mod:`sidekick.core.decision`  - decision model abstraction + provenance
- :mod:`sidekick.core.decisions` - rule based fallback and real Laya adapter
- :mod:`sidekick.core.parsing`   - segmentation, correction and entity parsing
- :mod:`sidekick.core.engine`    - the decision engine that ties it together
"""

__version__ = "0.1.0"
