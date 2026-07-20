"""
Dispatcher de publicación web.
WEB_PUBLISH_TARGET=node_webapp → publica en la WebApp Node.js de Hostinger
WEB_PUBLISH_TARGET=off         → omite publicación web
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

from utils.logging_setup import setup_logger

logger = setup_logger("publish_web", "publish_web.log")

TARGET = os.getenv("WEB_PUBLISH_TARGET", "off")


def main():
    logger.info(f"Publicación web → target: {TARGET}")

    if TARGET == "node_webapp":
        from pipeline.node_webapp.publisher import publish_pending
        publish_pending()

    elif TARGET == "off":
        logger.info("Publicación web deshabilitada (WEB_PUBLISH_TARGET=off)")

    else:
        logger.warning(f"WEB_PUBLISH_TARGET desconocido: {TARGET}. Opciones: node_webapp, off")


if __name__ == "__main__":
    main()
