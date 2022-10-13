import logging

import coloredlogs
from aidbox_python_sdk.main import create_app as _create_app

# Don't remove these imports
import task_queue.operations
from app.sdk import sdk, sdk_settings

coloredlogs.install(
    level="DEBUG", fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.DEBUG
)
logging.getLogger("aidbox_sdk").setLevel(logging.INFO)
logging.getLogger("urllib3").setLevel(logging.INFO)


async def create_app():
    return await _create_app(sdk_settings, sdk, debug=True)
