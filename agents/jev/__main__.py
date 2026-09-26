"""The servable entrypoint (transport only): compose, then serve.

The one place the real pieces are wired: the typesafe-sdk adapter, the `jev`
runtime settings and the classify step are injected into the JSON-RPC app,
which is then served. No agent logic lives here (SOLID-S); tests inject
fakes through the same parameters.
"""

import uvicorn
from starlette.applications import Starlette

from agents.jev.classifier import classify
from agents.jev.executor import ClassifyStep
from agents.jev.provider import JevProvider, TypeSafeJevProvider
from agents.jev.runtime import JevRuntime, load_jev_runtime
from agents.jev.server import create_app
from contracts.evidence import EvidencePack
from contracts.jev import JevResult

__all__ = ["build_app", "serve"]


def build_app(
    provider: JevProvider | None = None, runtime: JevRuntime | None = None
) -> Starlette:
    """Compose the real pieces into the servable app (tests inject fakes)."""
    jev_provider = provider if provider is not None else TypeSafeJevProvider()
    jev_runtime = runtime if runtime is not None else load_jev_runtime()

    async def classify_step(pack: EvidencePack) -> JevResult:
        return await classify(pack, jev_provider, jev_runtime)

    step: ClassifyStep = classify_step
    return create_app(step)


def serve() -> None:
    """Serve the composed app on the YAML-pinned host/port; blocks until
    the process is stopped."""
    jev_runtime = load_jev_runtime()
    uvicorn.run(
        build_app(runtime=jev_runtime), host=jev_runtime.host, port=jev_runtime.port
    )


if __name__ == "__main__":
    serve()
