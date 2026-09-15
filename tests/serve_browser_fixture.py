"""Isolated browser-test server. Never used by the product startup script."""
import os

if os.getenv("EXAMPILOT_TEST_MODE") != "1" or not os.getenv("EXAMPILOT_DATA_DIR"):
    raise RuntimeError("Browser fixtures require explicit test mode and isolated data directory")

import uvicorn
from backend import api
from tests.test_workflow import ModelDouble

api.settings.provider = lambda job_id="system": ModelDouble()
original_public = api.settings.public
api.settings.public = lambda: {**original_public(), "has_key": True, "test_fixture": True}

if __name__ == "__main__":
    uvicorn.run(api.app, host="127.0.0.1", port=8791, log_level="warning")
