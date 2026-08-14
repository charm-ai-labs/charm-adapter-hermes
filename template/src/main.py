"""
Hermes Agent Entry Point for Charm.

This module creates and exports a Hermes AIAgent instance configured for
headless execution inside the Charm Cloud Runner. The Charm adapter
(charm-adapter-hermes) picks up this factory via the ``entry_point``
declared in charm.yaml.

Customization:
  - Change ``model`` to use a different LLM provider/model.
  - Add ``enabled_toolsets`` / ``disabled_toolsets`` to control Hermes tools.
  - Set environment variables via charm.yaml ``keys`` for API credentials.
"""

import os

def create_agent(**kwargs):
    try:
        from run_agent import AIAgent
        # The Charm adapter redirects HERMES_HOME before this runs,
        # so all persistent data (sessions, skills, memory) will land on
        # the daemon's persistent workspace automatically.
        kwargs.setdefault("model", os.getenv("CHARM_HERMES_MODEL", "openrouter/auto"))
        kwargs.setdefault("quiet_mode", True)
        kwargs.setdefault("save_trajectories", False)
        return AIAgent(**kwargs)
    except ImportError:
        # Fallback for `charm validate` running locally without hermes-agent installed
        class DummyAgent:
            def __init__(self, *args, **kw):
                pass
            def run_conversation(self, **kw):
                return {"response": "dummy output"}
        return DummyAgent()

agent = create_agent
