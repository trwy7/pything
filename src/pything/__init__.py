"""pything framework package.

The implementation lives in submodules:

- ``state``      — config, paths, logging and shared registries
- ``web``        — responses, requests, routing, static files, templates
- ``websocket``  — raw websocket transport (RFC 6455) and client tracking
- ``settings``   — setting declarations
- ``app``        — the App model
- ``discovery``  — finding apps and resolving which are enabled
- ``routes``     — built-in pages (registers routes on import)
- ``server``     — HTTP request handler
- ``loader``     — app loading and ``main()`` startup

Apps import from those modules directly, e.g. ``from pything.app import App``.
Nothing is re-exported here.
"""

import sys

sys.modules["pything"] = sys.modules[__name__]

# Imported for its side effect: registers the built-in routes.
from . import routes  # noqa: F401
