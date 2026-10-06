#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

# The repository keeps the deployable R12/Week6 modules in jetson_patch so the
# same reviewed files are used by tests and the selective Jetson installer.
SOURCE_ROOT = Path(__file__).resolve().parents[1] / "jetson_patch"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from rcboat.config import VALUES, load_runtime_settings
from rcboat.controller import BoatController
from rcboat.hardware import MockHardware, RealHardware
from rcboat.navigation import RouteManager
from rcboat.server import ControlServer


def lock_single_instance(path: str):
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")
    if os.name == "nt":
        import msvcrt
        if lock_path.stat().st_size == 0:
            handle.write(" "); handle.flush()
        handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    handle.seek(0); handle.write(f"{os.getpid()}\n"); handle.truncate(); handle.flush()
    return handle


def release_instance_lock(handle) -> None:
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except (OSError, ValueError):
        pass
    handle.close()


async def run(args: argparse.Namespace) -> None:
    lock = lock_single_instance(args.lock_file)
    settings = load_runtime_settings(args.config)
    hardware = MockHardware() if args.mock else RealHardware(settings)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass
    controller = None
    server = None
    task = None
    try:
        hardware.start()
        controller = BoatController(hardware, RouteManager(args.routes), settings)
        server = ControlServer(controller, args.host, args.port, request_stop=lambda: loop.call_later(0.1, stop.set))
        await server.start()

        async def control_loop() -> None:
            while not stop.is_set():
                controller.step()
                await asyncio.sleep(0.02)

        task = asyncio.create_task(control_loop())
        await stop.wait()
    finally:
        if task:
            task.cancel(); await asyncio.gather(task, return_exceptions=True)
        if server:
            await server.close()
        if controller:
            controller.close()
        else:
            hardware.close()
        release_instance_lock(lock)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--routes", default=str(Path(__file__).with_name("routes.json")))
    parser.add_argument("--config", default=str(Path(__file__).with_name("boat_config.json")))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--lock-file", default=str(Path(__file__).with_name(".rcboat-daemon.lock")))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
