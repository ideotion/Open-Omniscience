"""R763: the AI install's spawned and clearnet steps refuse protected mode, the same way the app update does.

Each of these steps downloads outside this app's process:
- the Ollama installer script
- ``pip`` / ``uv`` installing vLLM
- the Hugging Face snapshot
- a model pull by the Ollama daemon

None of them goes through the proxy that protected mode routes this app's own requests through, so running one would reveal this
machine's address to those hosts. That would be a silent transport downgrade (the non-negotiable "never silently downgrade
transport"), so the step is refused, with a reason that names why. The update helper's ``git fetch`` is refused the same way
(``src.maintenance.self_update.refuse_offline_or_protected``), and this module reuses that module's rule rather than a second
copy of it: protected mode is chosen, OR the settings cannot be read, which counts as protected (R117).

The in-process steps are NOT refused here. The installer's release lookup and download (``installer.prepare_installer``) go
through ``guarded_session``, which honours the proxy.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

AI_INSTALL_PROTECTED_REFUSAL = (
    "Protected mode is on: the AI install did not start. It downloads over a direct connection, not through your proxy, "
    "which would reveal this machine's address. Switch to standard mode to install, or install by hand through your proxy."
)


def ai_install_protected() -> bool:
    """True when an AI install step that runs outside this process must be refused: protected mode is chosen, or the settings
    cannot be read (R117). The update's own rule, the one function, so the two refusals cannot drift apart."""
    from src.maintenance.self_update import protected_mode_chosen

    return protected_mode_chosen()


def refuse_if_protected(exc_type: type[Exception]) -> None:
    """Raise ``exc_type(AI_INSTALL_PROTECTED_REFUSAL)`` when :func:`ai_install_protected`. Each caller passes its own module's
    error type, so the refusal reaches the user on the path that module already reports through."""
    if ai_install_protected():
        raise exc_type(AI_INSTALL_PROTECTED_REFUSAL)
