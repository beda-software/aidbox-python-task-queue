from aidbox_python_sdk.sdk import SDK
from aidbox_python_sdk.settings import Settings

from app.manifest import meta_resources, entities

sdk_settings = Settings(**{})
sdk = SDK(sdk_settings, resources=meta_resources, entities=entities)
