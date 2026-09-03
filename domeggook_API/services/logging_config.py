from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


MAX_LOG_BYTES = 1_000_000
MAX_LOG_FILES = 5


def configure_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    _prune_rotated_logs(log_dir, "collector.log", MAX_LOG_FILES)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            RotatingFileHandler(
                log_dir / "collector.log",
                maxBytes=MAX_LOG_BYTES,
                backupCount=MAX_LOG_FILES - 1,
                encoding="utf-8",
            ),
        ],
        force=True,
    )


def _prune_rotated_logs(log_dir: Path, base_name: str, max_files: int) -> None:
    logs = sorted(
        log_dir.glob(f"{base_name}*"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in logs[max(max_files, 1) :]:
        try:
            path.unlink()
        except FileNotFoundError:
            pass

