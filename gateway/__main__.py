"""Runnable gateway: env settings + Postgres store + uvicorn (AD-25).

The one place concrete I/O adapters are wired in (SOLID-D). Host and port
are environment knobs with safe defaults; secrets keep their AD-16 names.
"""

import os

import uvicorn

from gateway.app import create_app
from gateway.settings import GatewaySettings, load_gateway_limits
from gateway.store import PostgresIntakeStore

_DEFAULT_HOST = "0.0.0.0"
_DEFAULT_PORT = 8080
_HOST_ENV = "GATEWAY_HOST"
_PORT_ENV = "GATEWAY_PORT"


def main() -> None:
    settings = GatewaySettings.from_env()
    store = PostgresIntakeStore(settings.database_url)
    app = create_app(settings, store, load_gateway_limits())
    uvicorn.run(
        app,
        host=os.environ.get(_HOST_ENV, _DEFAULT_HOST),
        port=int(os.environ.get(_PORT_ENV, str(_DEFAULT_PORT))),
    )


if __name__ == "__main__":
    main()
