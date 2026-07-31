import os
import logging
from logging.handlers import RotatingFileHandler

def setup_logging():
    logger = logging.getLogger("SchemaBuilder")
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

        # Console handler
        ch = logging.StreamHandler()
        ch.setFormatter(formatter)
        logger.addHandler(ch)

        # File handler
        fh = RotatingFileHandler('schema_builder.log', maxBytes=10*1024*1024, backupCount=5)
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    return logger

logger = setup_logging()

# Database Configuration
DB_USER = os.getenv("DB_USER", "system")
DB_PASSWORD = os.getenv("DB_PASSWORD", "DevPassword123")
DB_DSN = os.getenv("DB_DSN", "localhost:1521/FREEPDB1")
