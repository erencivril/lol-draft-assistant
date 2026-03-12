from __future__ import annotations

import logging

from app.logging_config import setup_logging


def test_setup_logging_configures_handlers_and_level(tmp_path) -> None:
    setup_logging(tmp_path, debug=False)
    logger = logging.getLogger("lda")

    assert logger.level == logging.INFO
    assert len(logger.handlers) == 2
    assert (tmp_path / "app.log").exists()

    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
