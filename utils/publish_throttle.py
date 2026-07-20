import os
import random
import time
from utils.logging_setup import setup_logger

logger = setup_logger("publish_throttle")

ENABLED = os.getenv("PUBLISH_THROTTLE_ENABLED", "true").lower() == "true"
DELAY_MIN = float(os.getenv("PUBLISH_DELAY_MIN_SECONDS", "20"))
DELAY_MAX = float(os.getenv("PUBLISH_DELAY_MAX_SECONDS", "30"))
BATCH_SIZE = int(os.getenv("PUBLISH_BATCH_SIZE", "10"))
BATCH_PAUSE = float(os.getenv("PUBLISH_BATCH_PAUSE_SECONDS", "180"))

_post_count = 0


def throttle() -> None:
    global _post_count
    if not ENABLED:
        return
    _post_count += 1
    if _post_count % BATCH_SIZE == 0:
        logger.info(f"Pausa de lote ({BATCH_PAUSE}s) después de {_post_count} publicaciones")
        time.sleep(BATCH_PAUSE)
    else:
        delay = random.uniform(DELAY_MIN, DELAY_MAX)
        logger.debug(f"Throttle: esperando {delay:.1f}s")
        time.sleep(delay)
