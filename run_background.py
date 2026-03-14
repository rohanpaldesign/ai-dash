"""
run_background.py — Background service entry point.

Starts three threads:
  1. window_monitor   — polls active window every 5s
  2. repo_analyzer    — scans git repos every 10 min
  3. periodic_processor — runs sessionizer + metrics every 5 min

Press Ctrl+C to stop cleanly.
"""

import logging
import signal
import sys
import threading
import time
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent))

from collectors import window_monitor, repo_analyzer
from processors import sessionizer, metrics_calculator

PROCESS_INTERVAL = 300  # 5 minutes between processor runs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(threadName)s] %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(Path(__file__).parent / "background.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

stop_event = threading.Event()


def periodic_processor() -> None:
    """Runs sessionizer + metrics_calculator every PROCESS_INTERVAL seconds."""
    logger.info("Periodic processor started (interval: %ds)", PROCESS_INTERVAL)
    while not stop_event.is_set():
        # Sleep in small chunks so we respond quickly to stop_event
        for _ in range(PROCESS_INTERVAL // 5):
            if stop_event.is_set():
                break
            time.sleep(5)
        if stop_event.is_set():
            break
        try:
            logger.info("Running sessionizer...")
            sessionizer.run()
            logger.info("Running metrics calculator...")
            metrics_calculator.run()
        except Exception as exc:
            logger.error("Processor error: %s", exc)
    logger.info("Periodic processor stopped.")


def shutdown(signum=None, frame=None) -> None:
    logger.info("Shutdown signal received. Stopping threads...")
    stop_event.set()


def main() -> None:
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    threads = [
        threading.Thread(
            target=window_monitor.run,
            args=(stop_event,),
            name="WindowMonitor",
            daemon=True,
        ),
        threading.Thread(
            target=repo_analyzer.run,
            args=(stop_event,),
            name="RepoAnalyzer",
            daemon=True,
        ),
        threading.Thread(
            target=periodic_processor,
            name="PeriodicProcessor",
            daemon=True,
        ),
    ]

    for t in threads:
        t.start()
        logger.info("Started thread: %s", t.name)

    logger.info("Background service running. Press Ctrl+C to stop.")

    # Keep main thread alive
    try:
        while not stop_event.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown()

    # Wait for threads to finish (they're daemon threads, so they'll die when main exits)
    for t in threads:
        t.join(timeout=15)

    logger.info("Background service stopped.")


if __name__ == "__main__":
    main()
