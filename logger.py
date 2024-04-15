import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(filename)s->%(funcName)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)
