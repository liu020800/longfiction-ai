import uvicorn
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.logging_util import setup_logging
from core.config import settings

setup_logging(debug=settings.DEBUG, log_level=settings.LOG_LEVEL)

from api.main import app

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
