# charm-adapter-hermes

Official Charm adapter for [Nous Research Hermes Agent](https://github.com/NousResearch/hermes-agent) — the self-improving AI agent with persistent memory, cross-session recall, and multi-provider LLM support.

This repository serves as both:
1. **A production adapter** enabling Hermes agents to run on the Charm platform.
2. **A reference implementation** showing how to build a Charm adapter plugin from scratch.

## Quick Start

### 1. Create a new Hermes agent project

```bash
charm init my-hermes-agent --template hermes-agent
cd my-hermes-agent
```

### 2. Set your API key

```bash
# In your charm.yaml `environment_variables` section, or via environment:
export OPENROUTER_API_KEY="sk-or-..."
```

### 3. Run locally

```bash
charm run --input '{"query": "Hello, who are you?"}'
```

### 4. Publish to Charm Store

```bash
charm push
```

## How It Works

### Architecture

```
┌──────────────────────────────────────────────────────┐
│                   Charm Cloud Runner                 │
│                                                      │
│  ┌────────────┐    ┌─────────────────┐               │
│  │ charm.yaml │───▶│ HermesAdapter   │               │
│  │ lifecycle:  │    │                 │               │
│  │   daemon    │    │  ┌───────────┐  │               │
│  └────────────┘    │  │ AIAgent   │  │               │
│                    │  │ (Hermes)  │  │               │
│                    │  └─────┬─────┘  │               │
│                    │        │        │               │
│                    └────────┼────────┘               │
│                             │                        │
│                    ┌────────▼────────┐               │
│                    │ CHARM_WORKSPACE │               │
│                    │   /daemon_shared│               │
│                    │  ├─ .hermes/    │               │
│                    │  │  ├─ sessions.db (FTS5)       │
│                    │  │  ├─ skills/                  │
│                    │  │  └─ memory/                  │
│                    └─────────────────┘               │
└──────────────────────────────────────────────────────┘
```

### Key Integration Points

| Concern | How it's handled |
|---|---|
| **Persistent memory** | `HERMES_HOME` is redirected to `CHARM_WORKSPACE_DIR/.hermes` so SQLite/FTS5 data survives daemon restarts |
| **Streaming** | Hermes `stream_delta_callback` is bridged to Charm's SSE emitter for real-time token output |
| **Threaded Streaming** | Because Hermes executes synchronously, the adapter wraps `run_conversation` in a background thread and bridges `stream_delta_callback` to Charm Runner via a thread-safe Queue, ensuring real-time token output |
| **Tool usage** | Hermes `tool_start_callback` / `tool_complete_callback` trigger Charm's tool usage tracking |
| **Headless mode** | Agent runs with `quiet_mode=True` — no TUI spinners or terminal chrome |
| **Model flexibility** | Any Hermes-supported provider (OpenRouter, OpenAI, Anthropic, local endpoints) works via env vars |
| **Lazy Configuration** | If `entry_point` points to a factory function, the adapter automatically injects environment variables like `model` before instantiation |

## Configuration

### charm.yaml

```yaml
version: "0.4.2"
persona:
  name: "My Hermes Agent"
  description: "My custom hermes agent"
interface:
  input:
    type: object
    properties:
      query:
        type: string
  output:
    type: string
runtime:
  adapter:
    type: "hermes"
    entry_point: "src.main:agent"
  lifecycle: "daemon"
  environment_variables:
    models:
      - OPENROUTER_API_KEY
```

### Environment Variables

| Variable | Description |
|---|---|
| `OPENROUTER_API_KEY` | Default LLM provider key |
| `CHARM_HERMES_MODEL` | Override the model (e.g., `anthropic/claude-sonnet-4-20250514`) |
| `CHARM_HERMES_BASE_URL` | Override the LLM API endpoint |

## Docker Runtime Image

For production deployments, use the pre-built runtime image:

```yaml
runtime:
  custom_image: "ghcr.io/charmaios/charm-runner-hermes:latest"
```

Or build locally:

```bash
docker build -t charm-runner-hermes .
```

## For Plugin Developers

This repo demonstrates the standard Charm adapter plugin pattern:

1. **Inherit the contract** — implement `invoke()`, `stream()`, `get_state()`, `set_tools()`.
2. **Register via entry points** — declare `[project.entry-points."charm.adapters"]` in `pyproject.toml`.
3. **Redirect state** — use `CHARM_WORKSPACE_DIR` for any persistent data.
4. **Run headless** — suppress all interactive UI when inside the runner.

See the [Custom Adapters Guide](https://docs.charmos.io/guides/custom-adapters) for the full specification.

## License

MIT
