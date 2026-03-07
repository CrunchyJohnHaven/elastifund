"""Entry point for the Polymarket edge discovery engine."""

from __future__ import annotations

import argparse
import logging
from logging.handlers import RotatingFileHandler
import signal
import threading
import time

if __package__ is None or __package__ == "":  # pragma: no cover
    import sys
    from pathlib import Path

    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from src.config import load_config
    from src.research_loop import ResearchLoop
else:  # pragma: no cover
    from .config import load_config
    from .research_loop import ResearchLoop


def configure_logging(log_path: str, level: int = logging.INFO) -> None:
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    root = logging.getLogger()
    root.setLevel(level)

    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    root.addHandler(stream)

    file_handler = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=3)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Polymarket 15-minute edge discovery engine")
    parser.add_argument("--config", default="config/defaults.yaml", help="Path to config YAML")
    parser.add_argument("--run-once", action="store_true", help="Run a single cycle and exit")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    configure_logging(config.system.log_path, getattr(logging, args.log_level.upper(), logging.INFO))

    logger = logging.getLogger("edge-main")
    loop = ResearchLoop(config, logger=logger)

    stop_event = threading.Event()
    collector_thread: threading.Thread | None = None

    def _handle_signal(signum: int, _frame: object) -> None:
        logger.info("Received signal %s, shutting down...", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    if args.run_once:
        result = loop.run_cycle(run_ml=True, collect_data=True)
        logger.info("Run once complete: recommendation=%s top=%s", result.recommendation, result.top_hypothesis)
        stop_event.set()
    else:
        # Start continuous collectors in background only for daemon mode.
        collector_thread = threading.Thread(target=loop.pipeline.collect_loop, args=(stop_event,), daemon=True)
        collector_thread.start()
        loop.pipeline.start_btc_stream()
        logger.info("Starting continuous research loop")
        loop.run_forever(stop_event)

    stop_event.set()
    loop.pipeline.stop_btc_stream()
    if collector_thread is not None:
        collector_thread.join(timeout=5)
    time.sleep(0.1)


if __name__ == "__main__":
    main()
