"""The A2A read-only server: JSON-RPC `get_task`/`list_tasks` over HTTP (AD-4/5).

Transport wiring only (SOLID-S): it builds the read-only task store and hands
it to a2a-sdk 1.1.5's `DefaultRequestHandler`, then exposes the JSON-RPC
binding with `create_jsonrpc_routes`. There is no executor work on this path —
`RefusingExecutor` refuses any attempt to run an agent, so a read can never
schedule a worker. The SDK's database-backed task store is deliberately not
wired here; `triage_run` is the only owner of run state (AD-4).
"""

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
from a2a.types.a2a_pb2 import AgentCapabilities, AgentCard
from a2a.utils.errors import UnsupportedOperationError
from starlette.applications import Starlette

from workflow.task_store import ReadOnlyTaskStore, TaskReader
from workflow.thresholds import load_thresholds

__all__ = ["RefusingExecutor", "create_app"]

_RPC_URL = "/"
_REFUSAL = "this endpoint serves task reads only (AD-4)"


class RefusingExecutor(AgentExecutor):
    """An executor that refuses every call: this agent has no work to do.

    The handler requires an executor, but 2.4 only reads. Any `message/send`
    that reached here would be a wiring mistake, so both methods refuse
    definitively (AD-22).
    """

    async def execute(self, _context: RequestContext, _event_queue: EventQueue) -> None:
        raise UnsupportedOperationError(message=_REFUSAL)

    async def cancel(self, _context: RequestContext, _event_queue: EventQueue) -> None:
        raise UnsupportedOperationError(message=_REFUSAL)


def _agent_card() -> AgentCard:
    """The public card for the read-only orchestrator endpoint (AD-5)."""
    return AgentCard(
        name="triage-orchestrator",
        description="Read-only A2A view of a triage run (AD-4).",
        version="0.1.0",
        capabilities=AgentCapabilities(streaming=False, push_notifications=False),
    )


def create_app(reader: TaskReader, repo_id: int) -> Starlette:
    """Build the Starlette app that serves `get_task`/`list_tasks` (AD-4, AD-5).

    `reader` supplies stored runs/steps and each run's serving confidence
    (story 4.1); `repo_id` is the tenant scope every read is bound to (AD-15).
    The cut-offs come from the one thresholds file (AD-19). A run whose
    confidence is below the class cutoff — or cannot be read — is served
    blame-free (AD-27).
    """
    store = ReadOnlyTaskStore(reader, repo_id, cutoffs=load_thresholds().confidence)
    handler = DefaultRequestHandler(
        agent_executor=RefusingExecutor(),
        task_store=store,
        agent_card=_agent_card(),
    )
    return Starlette(routes=create_jsonrpc_routes(handler, _RPC_URL))
