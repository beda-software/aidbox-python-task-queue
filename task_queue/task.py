import asyncio
import functools

# import jsonschema
from fhirpy.base.exceptions import OperationOutcome

from . import config
from app.sdk import sdk

from .task_queue import process_queue_entry, register_task


class TaskException(Exception):
    message = None
    info = None

    def __init__(self, message=None, info=None):
        self.message = message
        self.info = info


class TaskFailure(TaskException):
    pass


def task(_fn=None, *, task_name=None, priority=10, immediate=True, payload_schema=None):
    def wrapper(fn):
        generated_task_name = task_name or "{}.{}".format(fn.__module__, fn.__name__)

        def check_payload(payload):
            if payload_schema:
                payload_validator = jsonschema.Draft202012Validator(schema=payload_schema)
                validate_payload(payload_validator, payload)

        @functools.wraps(fn)
        async def delay_fn(payload, related=None):
            check_payload(payload)

            res = sdk.client.resource(
                "TaskQueue",
                **{
                    "source": generated_task_name,
                    "status": "pending",
                    "priority": priority,
                    "payload": payload,
                    "processing": immediate,
                    "affectedResources": related,
                },
            )
            await res.save()

            if config.task_always_eager:
                # task_always_eager settings runs the task in the main thread
                # It's very useful for tests
                await process_queue_entry(res)
            else:
                if immediate:
                    asyncio.get_event_loop().create_task(process_queue_entry(res))

            return res

        async def process_queue_fn(q, payload, apply_strategy):
            try:
                result = await fn(payload)

                await apply_strategy(payload, sync=True, info=result)
            except TaskFailure as exc:
                await apply_strategy(payload, fail=True, info=exc.info, message=exc.message)

        @functools.wraps(fn)
        async def wrapped_fn(payload, related=None):
            check_payload(payload)

            return await fn(payload)

        wrapped_fn.delay = delay_fn
        register_task(generated_task_name, process_queue_fn)

        return wrapped_fn

    if _fn is None:
        return wrapper
    else:
        return wrapper(_fn)


def validate_payload(payload_validator, payload):
    errors = list(payload_validator.iter_errors(payload))

    if errors:
        raise OperationOutcome(
            resource={
                "resourceType": "OperationOutcome",
                "text": {"status": "generated", "div": "Invalid payload"},
                "issue": [
                    {
                        "severity": "fatal",
                        "code": "invalid",
                        "expression": [".".join([str(x) for x in ve.absolute_path])],
                        "diagnostics": ve.message,
                    }
                    for ve in errors
                ],
            }
        )
