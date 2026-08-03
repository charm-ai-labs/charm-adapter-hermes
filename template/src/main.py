"""
Hermes Agent Entry Point for Charm.

This module creates and exports a Hermes AIAgent instance configured for
headless execution inside the Charm Cloud Runner. The Charm adapter
(charm-adapter-hermes) picks up this object via the ``entry_point``
declared in charm.yaml.

Customization:
  - Change ``model`` to use a different LLM provider/model.
  - Add ``enabled_toolsets`` / ``disabled_toolsets`` to control Hermes tools.
  - Set environment variables via charm.yaml ``keys`` for API credentials.
"""

import os

try:
    from run_agent import AIAgent
    # Create the Hermes agent in quiet mode (no TUI/spinners).
    # The Charm adapter will redirect HERMES_HOME before this runs,
    # so all persistent data (sessions, skills, memory) will land on
    # the daemon's persistent workspace automatically.
    agent = AIAgent(
        model=os.getenv("CHARM_HERMES_MODEL", "openrouter/auto"),
        quiet_mode=True,
        save_trajectories=False,
    )
except ImportError:
    # Fallback for `charm validate` running locally without hermes-agent installed
    class DummyAgent:
        def __init__(self, *args, **kwargs):
            pass
    agent = DummyAgent()
