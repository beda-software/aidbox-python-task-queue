# Task Queue Manager for Aidbox

## Installation
1. Add the project as a submodule to `app/contrib` directory
2. Include task queue manifest: meta_resources and entities
```python
from app.contrib.task_queue import manifest as task_queue_manifest

meta_resources = merge_resources(
    task_queue_manifest.meta_resources,
    {...}
)

entities = {
    **task_queue_manifest.entities,
    ...
}
```
3. Add imports to `main.py`
```python
...
import app.contrib.task_queue
import app.contrib.task_queue.operations

...
```
4. Add cronjob periodic task or k8s CronJob to call `POST /TaskQueue/$beat` periodically

## Usage
```python
import asyncio
import logging

from aiohttp import web

from app.contrib.task_queue.task import task
from app.sdk import sdk

@sdk.operation(["POST"], ["send_sms"])
async def send_sms_op(operation, request):
    task_queue_id = await send_sms_task.delay({"msg": "Hello!"})
    return web.json_response({"task_queue_id": task_queue_id}, status=202)


@task(immediate=False)
async def send_sms_task(payload):
    await asyncio.sleep(5)
    msg = payload["msg"]
    logging.debug(f"Message: {msg}")

```

## Tests
Set env variable `TASK_ALWAYS_EAGER=True` to run tasks in the same event loop

To run tests locally, copy `.env.tpl` to `.env` and specify `TESTS_AIDBOX_LICENSE_ID` and `TESTS_AIDBOX_LICENSE_KEY`.  


Build images using `docker-compose -f docker-compose.tests.yaml build`.


After that, just start `./run_test.sh` or `./run_test.sh tests/test_base.py` (if you want to run the particular file/test).
The first run may take about a minute because it prepares the db and devbox.


If you have updated some requirements, you need to re-run `docker-compose -f docker-compose.tests.yaml build`
