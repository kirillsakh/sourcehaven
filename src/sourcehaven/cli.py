import argparse
import asyncio
import json
import signal
import sys
from collections.abc import Sequence

import uvicorn
from pydantic import SecretStr

from sourcehaven.api.app import create_app
from sourcehaven.composition import build_container
from sourcehaven.config import Settings
from sourcehaven.migrations import upgrade_database
from sourcehaven.worker.runner import run_worker

COMMANDS: dict[str, str] = {
    "serve": "Run the web application.",
    "worker": "Run the background ingestion worker.",
    "migrate": "Apply database migrations.",
    "openapi": "Print the OpenAPI schema.",
}


def build_parser() -> argparse.ArgumentParser:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(prog="sourcehaven")
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser] = parser.add_subparsers(
        dest="command", required=True, metavar="COMMAND"
    )
    for name, help_text in COMMANDS.items():
        subparsers.add_parser(name, help=help_text, description=help_text)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Sourcehaven command line interface.

    Args:
        argv: Arguments excluding the program name; defaults to ``sys.argv[1:]``.

    Returns:
        The process exit code.
    """
    args: argparse.Namespace = build_parser().parse_args(argv)
    if args.command == "migrate":
        return migrate(Settings())
    if args.command == "serve":
        return serve(Settings())
    if args.command == "openapi":
        return print_openapi(Settings())
    return worker(Settings())


def migrate(settings: Settings) -> int:
    admin_url: SecretStr | None = settings.admin_database_url
    app_password: SecretStr | None = settings.app_role_password
    maintenance_password: SecretStr | None = settings.maintenance_role_password
    if admin_url is None or app_password is None or maintenance_password is None:
        missing: list[str] = [
            name
            for name, value in (
                ("SOURCEHAVEN_ADMIN_DATABASE_URL", admin_url),
                ("SOURCEHAVEN_APP_ROLE_PASSWORD", app_password),
                ("SOURCEHAVEN_MAINTENANCE_ROLE_PASSWORD", maintenance_password),
            )
            if value is None
        ]
        print(
            f"sourcehaven migrate: missing required settings: {', '.join(missing)}", file=sys.stderr
        )
        return 2
    upgrade_database(
        admin_url=admin_url,
        app_role_password=app_password,
        maintenance_role_password=maintenance_password,
    )
    print("sourcehaven migrate: database is at the latest revision", file=sys.stderr)
    return 0


def serve(settings: Settings) -> int:
    uvicorn.run(
        create_app(settings),
        host="0.0.0.0",
        port=8000,
        proxy_headers=True,
        forwarded_allow_ips=settings.trusted_proxy,
        access_log=False,
    )
    return 0


def print_openapi(settings: Settings) -> int:
    print(json.dumps(create_app(settings).openapi(), indent=2))
    return 0


def worker(settings: Settings) -> int:
    asyncio.run(_run_worker_until_signalled(settings))
    print("sourcehaven worker: stopped", file=sys.stderr)
    return 0


async def _run_worker_until_signalled(settings: Settings) -> None:
    stop: asyncio.Event = asyncio.Event()
    loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
    signals: tuple[signal.Signals, ...] = (signal.SIGTERM, signal.SIGINT)
    for signal_number in signals:
        loop.add_signal_handler(signal_number, stop.set)
    try:
        async with build_container(settings) as container:
            await run_worker(container, stop=stop)
    finally:
        for signal_number in signals:
            loop.remove_signal_handler(signal_number)
