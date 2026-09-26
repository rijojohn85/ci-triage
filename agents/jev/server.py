"""The JSON-RPC app wiring (transport only): card + executor + handler.

Mirrors `workflow/a2a_server.py`'s wiring with a real executor: a2a-sdk
1.1.5's `DefaultRequestHandler` over an in-memory task store (the agent is
stateless, AD-5), the JSON-RPC binding at `/`, and the public card at
`/.well-known/agent-card.json`.
"""

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes.agent_card_routes import create_agent_card_routes
from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from starlette.applications import Starlette

from agents.jev.card import agent_card
from agents.jev.executor import ClassifyStep, JevExecutor

__all__ = ["create_app"]

_RPC_URL = "/"


def create_app(classify: ClassifyStep) -> Starlette:
    """Build the Starlette app serving `classify-failure` over JSON-RPC."""
    handler = DefaultRequestHandler(
        agent_executor=JevExecutor(classify),
        task_store=InMemoryTaskStore(),
        agent_card=agent_card(),
    )
    return Starlette(
        routes=[
            *create_jsonrpc_routes(handler, _RPC_URL),
            *create_agent_card_routes(agent_card()),
        ]
    )
