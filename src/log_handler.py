import logging
import io
from contextlib import contextmanager

@contextmanager
def setup_log_capture():
    log_capture_stream = io.StringIO()
    handler = logging.StreamHandler(log_capture_stream)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    
    root_logger = logging.getLogger()
    original_handlers = root_logger.handlers[:]
    root_logger.handlers = []
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

    try:
        yield log_capture_stream
    finally:
        root_logger.handlers = original_handlers