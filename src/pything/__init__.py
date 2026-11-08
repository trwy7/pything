"""pything framework package.

You should probably import a submodule:

- ``state``      — config, paths, logging and shared registries
- ``web``        — responses, requests, routing, static files, templates
- ``websocket``  — raw websocket transport (RFC 6455) and client tracking
- ``settings``   — setting declarations
- ``app``        — the App model
- ``discovery``  — finding apps and resolving which are enabled
- ``routes``     — built-in pages (registers routes on import)
- ``server``     — HTTP request handler
- ``loader``     — app loading and ``main()`` startup
"""

# Imported to register the built-in routes.
from . import routes  # noqa: F401
