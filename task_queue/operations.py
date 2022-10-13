import asyncio
import logging

from aiohttp import web

from app.sdk import sdk
from .task_queue import process_queue_entry, select_and_mark_as_processing, select_processing


class State(object):
    lock = None
    processing_ids = None

    def __init__(self):
        self.processing_ids = set()
        self.lock = asyncio.Lock()

    def get_processing_ids(self):
        return self.processing_ids

    def set_processing_ids(self, ids):
        self.processing_ids = ids


queue_previous_state = State()


@sdk.operation(["POST"], ["TaskQueue", "$beat"])
async def task_queue_beat_op(_operation, _request):
    statuses_priority = [("pending", 100), ("skipped", 50)]
    asyncio.create_task(process_queue(
        "TaskQueue",
        statuses_priority,
        process_entry=process_queue_entry,
        previous_state=queue_previous_state,
    ))
    return web.json_response({})


async def process_queue(queue_resource_name, statuses_priority, *, process_entry, previous_state):
    async with previous_state.lock:
        processing_entries = await select_processing(queue_resource_name)
        processing_entries_count = len(processing_entries)
        if processing_entries_count:
            current_processing_ids = set(
                [processing_row["id"] for processing_row in processing_entries]
            )
            if current_processing_ids == previous_state.get_processing_ids():
                logging.debug(
                    "[{0}] Continue processing {1} entries".format(
                        queue_resource_name, processing_entries_count
                    )
                )
            else:
                previous_state.set_processing_ids(current_processing_ids)
                logging.debug(
                    "[{0}] Skip processing {1} entries".format(
                        queue_resource_name, processing_entries_count
                    )
                )
                return

        else:
            processing_entries = await select_and_mark_as_processing(
                queue_resource_name, statuses_priority
            )
            current_processing_ids = set(
                [processing_row["id"] for processing_row in processing_entries]
            )
            logging.debug(
                "[{0}] Start processing {1} entries".format(
                    queue_resource_name, len(processing_entries)
                )
            )

        previous_state.set_processing_ids(current_processing_ids)

    for entry in processing_entries:
        await process_entry(sdk.client.resource(queue_resource_name, **entry))
