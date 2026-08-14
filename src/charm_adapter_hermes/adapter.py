"""
Charm Adapter for Nous Research Hermes Agent.

This adapter bridges the Hermes AIAgent (https://github.com/NousResearch/hermes-agent)
to the Charm Cloud Runner, enabling Hermes agents to be published, executed,
and managed on the Charm platform.

Key integration points:
  - Redirects HERMES_HOME to CHARM_WORKSPACE_DIR for daemon-mode persistence
    (SQLite session DB, skills, memory all survive container restarts).
  - Bridges Hermes callbacks (stream_delta, tool_start/complete, thinking)
    to Charm's SSE emitter protocol so the Store frontend can render
    real-time token streaming, tool usage cards, and thinking indicators.
  - Runs AIAgent in quiet_mode to suppress TUI chrome that would corrupt
    the runner's structured stdout.

Usage in charm.yaml:
    runtime:
      adapter:
        type: "hermes"
        entry_point: "src.main:agent"
      lifecycle: "daemon"
"""

import inspect
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

logger = logging.getLogger("charm.adapter.hermes")


class HermesAdapter:
    """Charm BaseAdapter-compatible wrapper around Hermes AIAgent.

    The adapter follows the same contract as charm.adapters.base.BaseAdapter
    but is distributed as a standalone pip package, registered via the
    ``[project.entry-points."charm.adapters"]`` mechanism in pyproject.toml.
    """

    def __init__(self, agent_instance: Any, config: Optional[Any] = None):
        self.agent = agent_instance  # The user's AIAgent (or a factory)
        self.config = config
        self._hermes_home: Optional[str] = None

        # Redirect Hermes data directory to Charm's persistent workspace
        # so SQLite session DBs, skills, and memory survive daemon restarts.
        self._setup_persistence()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _setup_persistence(self) -> None:
        """Point HERMES_HOME at the Charm workspace directory.

        In daemon mode the runner sets CHARM_WORKSPACE_DIR to a GCS-backed
        mount (``/workspace/{user_id}/{agent_id}/daemon_shared``).  Hermes
        stores all durable state under ``HERMES_HOME`` (default ~/.hermes),
        including:
          - sessions.db (SQLite + FTS5 conversation history)
          - skills/ (auto-generated skills)
          - memory/ (user model, context)

        Redirecting HERMES_HOME ensures everything lands on persistent
        storage instead of the ephemeral container filesystem.
        """
        workspace = os.getenv("CHARM_WORKSPACE_DIR", "")
        if workspace:
            hermes_home = os.path.join(workspace, ".hermes")
            os.makedirs(hermes_home, exist_ok=True)
            os.environ["HERMES_HOME"] = hermes_home
            self._hermes_home = hermes_home
            logger.info("HERMES_HOME → %s (Charm persistent workspace)", hermes_home)

    # ------------------------------------------------------------------
    # Agent instantiation helpers
    # ------------------------------------------------------------------

    def _ensure_agent(self) -> Any:
        """Lazily instantiate the AIAgent if a factory/class was provided."""
        if callable(self.agent) and not hasattr(self.agent, "run_conversation"):
            logger.debug("Auto-instantiating Hermes AIAgent from factory…")
            provider_config = getattr(self.config, "provider_config", {}) if self.config else {}
            kwargs = self._build_agent_kwargs(provider_config)
            self.agent = self.agent(**kwargs)
        return self.agent

    def _build_agent_kwargs(self, provider_config: Dict[str, Any]) -> Dict[str, Any]:
        """Build constructor kwargs from Charm environment + user config.

        When the user provides a raw AIAgent class (not an instance), we
        construct it here with the right quiet_mode and provider settings
        pulled from Charm environment variables.
        """
        kwargs: Dict[str, Any] = {
            "quiet_mode": True,
        }

        # Model / provider from Charm env (set by the runner from charm.yaml keys)
        model = os.getenv("CHARM_HERMES_MODEL", "")
        if model:
            kwargs["model"] = model

        api_key = os.getenv("CHARM_HERMES_API_KEY", "") or os.getenv("OPENROUTER_API_KEY", "")
        if api_key:
            kwargs["api_key"] = api_key

        base_url = os.getenv("CHARM_HERMES_BASE_URL", "")
        if base_url:
            kwargs["base_url"] = base_url

        # Merge any explicit config the user set in their entry point
        if provider_config:
            kwargs.update(provider_config)

        return kwargs

    # ------------------------------------------------------------------
    # Core execution: invoke
    # ------------------------------------------------------------------

    def invoke(
        self, inputs: Dict[str, Any], callbacks: Optional[List[Any]] = None
    ) -> Dict[str, Any]:
        """Execute a single Hermes conversation turn.

        Parameters
        ----------
        inputs : dict
            Must contain ``query`` (the user message).  May also contain
            ``session_id`` for cross-turn continuity within a daemon.
        callbacks : list, optional
            Charm callback handlers (currently unused; streaming is bridged
            via Hermes's own callback system).

        Returns
        -------
        dict
            ``{"status": "success", "output": "<assistant response>"}``
            or ``{"status": "error", ...}`` on failure.
        """
        agent = self._ensure_agent()
        user_message = inputs.get("query", "") or inputs.get("input", "")

        if not user_message:
            return {
                "status": "error",
                "error_type": "InputError",
                "message": "No 'query' or 'input' field provided in inputs.",
            }

        logger.info("Hermes invoke — message length: %d chars", len(user_message))

        try:
            # Hermes AIAgent.run_conversation returns a dict with full
            # metadata: {"response": str, "messages": [...], "usage": {...}}
            result = agent.run_conversation(user_message=user_message)

            # Extract the final assistant text
            if isinstance(result, dict):
                output = result.get("final_response", "") or result.get("response", "") or result.get("output", "")
            elif isinstance(result, str):
                output = result
            else:
                output = str(result)

            return {
                "status": "success",
                "output": output,
            }

        except Exception as e:
            logger.error("Hermes agent execution failed: %s", e, exc_info=True)
            return {
                "status": "error",
                "error_type": type(e).__name__,
                "message": f"Hermes Agent Error: {str(e)}",
            }

    # ------------------------------------------------------------------
    # Streaming execution
    # ------------------------------------------------------------------

    def stream(
        self, inputs: Dict[str, Any], callbacks: Optional[List[Any]] = None
    ) -> Generator[Any, None, None]:
        """Stream a Hermes conversation with real-time token output."""
        import queue
        import threading
        
        agent = self._ensure_agent()
        user_message = inputs.get("query", "") or inputs.get("input", "")

        if not user_message:
            yield {
                "status": "error",
                "error_type": "InputError",
                "message": "No 'query' or 'input' field provided in inputs.",
            }
            return

        q = queue.Queue()

        def _on_stream_delta(delta: str) -> None:
            q.put({"type": "token", "content": delta})

        def _on_tool_start(tool_name: str, tool_input: Any) -> None:
            q.put({"type": "tool_start", "tool": tool_name})
            try:
                from charm.core.io import CharmEmitter
                CharmEmitter.emit_tool_usage(tool_name, 1)
            except ImportError:
                pass

        def _on_tool_complete(tool_name: str, result: Any) -> None:
            q.put({"type": "tool_complete", "tool": tool_name})

        if hasattr(agent, "stream_delta_callback"):
            agent.stream_delta_callback = _on_stream_delta
        if hasattr(agent, "tool_start_callback"):
            agent.tool_start_callback = _on_tool_start
        if hasattr(agent, "tool_complete_callback"):
            agent.tool_complete_callback = _on_tool_complete

        def worker():
            try:
                result = agent.run_conversation(user_message=user_message)
                if isinstance(result, dict):
                    output = result.get("final_response", "") or result.get("response", "") or result.get("output", "")
                else:
                    output = str(result)
                q.put({"type": "success", "content": output})
            except Exception as e:
                q.put({"type": "error", "error": e})
            finally:
                q.put(None)

        t = threading.Thread(target=worker)
        t.start()

        while True:
            item = q.get()
            if item is None:
                break
            
            if item["type"] == "token":
                yield {"status": "streaming", "delta": item["content"]}
            elif item["type"] == "tool_start":
                yield {"status": "streaming", "delta": ""} # Tool start heartbeat
            elif item["type"] == "tool_complete":
                yield {"status": "streaming", "delta": ""} # Tool end heartbeat
            elif item["type"] == "success":
                yield {"status": "success", "output": item["content"]}
            elif item["type"] == "error":
                e = item["error"]
                logger.error("Hermes streaming failed: %s", e, exc_info=True)
                yield {
                    "status": "error",
                    "error_type": type(e).__name__,
                    "message": f"Hermes Agent Error: {str(e)}",
                }
                
        t.join()

    # ------------------------------------------------------------------
    # State & tools (BaseAdapter contract)
    # ------------------------------------------------------------------

    def get_state(self) -> Dict[str, Any]:
        """Return current agent state (session info, memory stats)."""
        state: Dict[str, Any] = {}
        agent = self.agent if hasattr(self.agent, "run_conversation") else None
        if agent:
            state["session_id"] = getattr(agent, "session_id", None)
            state["model"] = getattr(agent, "model", None)
            if self._hermes_home:
                state["hermes_home"] = self._hermes_home
        return state

    def set_tools(self, tools: List[Any]) -> None:
        """Hermes manages its own toolsets; this is a no-op."""
        pass
