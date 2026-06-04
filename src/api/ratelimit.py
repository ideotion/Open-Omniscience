"""
Single shared rate limiter.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

SlowAPIMiddleware enforces limits registered on ``app.state.limiter``. Previously
each router built its OWN ``Limiter`` instance, so the ``@limiter.limit`` decorators
on router endpoints registered on instances the middleware never saw -- i.e. they
did nothing. Everything now imports this one instance, which main.py attaches to
the app, so the decorators are actually enforced.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
