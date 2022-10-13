import asyncio
import logging
import traceback
from functools import wraps

import sqlalchemy
from aidbox_python_sdk.db import row_to_resource
from aidboxpy import AsyncAidboxResource

from app.sdk import sdk
from .utils import get_dict_hash


def _get_client():
    from app.sdk import sdk

    return sdk.client


def make_bundle(resources, type_="searchset", **kwargs):
    client = _get_client()

    entries = []
    for resource in resources:
        serialized_resource = (
            resource.serialize()
            if isinstance(resource, AsyncAidboxResource)
            else resource
        )
        entry = {"resource": serialized_resource}
        if type_ in ["transaction", "batch"]:
            if resource.id:
                entry["request"] = {
                    "method": "PUT",
                    "url": "/{0}/{1}".format(
                        serialized_resource["resourceType"], serialized_resource["id"]
                    ),
                }
            else:
                entry["request"] = {
                    "method": "POST",
                    "url": "/{0}".format(serialized_resource["resourceType"]),
                }
        entries.append(entry)

    return client.resource("Bundle", type=type_, entry=entries, **kwargs)


async def update_queue_status(q, status, message=None, info=None):
    q["status"] = status
    q["processingMessage"] = message
    q["processingInfo"] = info
    await q.save()
    return q


async def mark_as_synced(q, affected_resource=None, message=None, info=None):
    if affected_resource:
        if not isinstance(affected_resource, list):
            affected_resource = [affected_resource]
        q["affectedResources"] = [res.to_reference() for res in affected_resource]
    return await update_queue_status(q, "synced", message, info)


async def mark_as_fuzzymatched(q, affected_resources, message=None, info=None):
    q["affectedResources"] = [
        affected_resources.to_reference() for affected_resource in affected_resources
    ]
    return await update_queue_status(q, "fuzzymatched", message, info)


async def mark_as_rejected(q, message=None, info=None):
    return await update_queue_status(q, "rejected", message, info)


async def mark_as_duplicated(q, message=None, info=None):
    return await update_queue_status(q, "duplicated", message, info)


async def mark_as_skipped(q, message=None, info=None):
    return await update_queue_status(q, "skipped", message, info)


async def mark_as_failed(q, message=None, info=None):
    return await update_queue_status(q, "failed", message, info)


async def mark_as_exception(q, message=None, info=None):
    return await update_queue_status(q, "exception", message, info)


async def mark_as_manual(q, message=None, info=None):
    return await update_queue_status(q, "manual", message, info)


def apply_entry_strategy_factory(merge_fn=None, create_fn=None, apply_fn=None):
    merge_fn = merge_fn or default_entry_strategy_merge_to
    create_fn = create_fn or default_entry_strategy_create
    apply_fn = apply_fn or default_entry_strategy_apply

    async def _fn(q, resource, message=None, info=None, **strategy):
        q["payload"] = (
            resource.serialize() if isinstance(resource, AsyncAidboxResource) else resource
        )

        if "reject" in strategy:
            await mark_as_rejected(q, message=message, info=info)
        elif "duplicate" in strategy:
            await mark_as_duplicated(q, message=message, info=info)
        elif "fail" in strategy:
            await mark_as_failed(q, message=message, info=info)
        elif "skip" in strategy:
            await mark_as_skipped(q, message=message, info=info)
        elif "sync" in strategy:
            await mark_as_synced(q, message=message, info=info)

        # Import strategies
        elif "move_to_manual" in strategy:
            await mark_as_manual(q, message=message, info=info)
        elif "sync_to" in strategy:
            await mark_as_synced(
                q, affected_resource=strategy["sync_to"], message=message, info=info
            )
        elif "fuzzymatch_to" in strategy:
            await mark_as_fuzzymatched(q, strategy["fuzzymatch_to"], message=message, info=info)
        elif "merge_to" in strategy:
            await merge_fn(q, resource, strategy["merge_to"])
        elif "create" in strategy:
            await create_fn(q, resource)
        elif "apply" in strategy:
            await apply_fn(q, resource)
        else:
            raise NotImplementedError("Not implemented strategy `{0}`".format(strategy))
        return q

    return _fn


async def default_entry_strategy_merge_to(q, resource, merge_to):
    raise NotImplementedError()


async def default_entry_strategy_apply(q, resource):
    raise NotImplementedError()


async def default_entry_strategy_create(q, resource):
    await resource.save()
    return await mark_as_synced(q, resource)


async def has_duplicates(q):
    count = (
        await sdk.client.resources(q["resourceType"])
        .search(
            status__not=["pending", "duplicated"],
            source=q["source"],
            payload_hash=q["payloadHash"],
            id__not=q["id"],
        )
        .count()
    )

    return count > 0


async def select_and_mark_as_processing(queue_resource_name, statuses_priority):
    queue = getattr(sdk.db, queue_resource_name)

    ids_stmt = sqlalchemy.union(
        *[
            sqlalchemy.select([queue.c.id])
            .where(
                sqlalchemy.and_(
                    ~queue.c.resource.contains({"processing": True}),
                    sqlalchemy.or_(*[queue.c.resource.contains({"status": status})]),
                )
            )
            .order_by(
                *[
                    *([queue.c.resource["priority"].asc()] if status == "pending" else []),
                    queue.c.ts.asc(),
                ]
            )
            .limit(count)
            for status, count in statuses_priority
        ]
    )
    update_stmt = (
        sqlalchemy.update(queue)
        .values(resource=queue.c.resource.op("||")({"processing": True}))
        .where(queue.c.id.in_(ids_stmt))
        .returning(queue)
    )
    rows = await sdk.db.alchemy(update_stmt)
    entries = [row_to_resource(row) for row in rows]
    return sorted(entries, key=lambda entry: entry["priority"])


async def select_processing(queue_resource_name):
    queue = getattr(sdk.db, queue_resource_name)
    select_stmt = (
        sqlalchemy.select([queue])
        .where(queue.c.resource.contains({"processing": True}))
        .order_by(queue.c.resource["priority"].asc())
    )
    rows = await sdk.db.alchemy(select_stmt)
    return [row_to_resource(row) for row in rows]


def get_fn_for_export_queue(q):
    source = q["source"]
    if source in task_registry:
        return task_registry[source], False

    resource_type = q["payload"]["resourceType"]

    try:
        rt_mapping = task_mapping[resource_type]
        if isinstance(rt_mapping, dict):
            fns = rt_mapping.get(source) or rt_mapping["default"]
        else:
            fns = rt_mapping

        return fns[0], True
    except KeyError:
        raise NotImplementedError(
            "You should add function or mapping of function for the chosen "
            "resource type `{0}` and/or source `{1}` or "
            "`default`".format(resource_type, source)
        )


def catch_queue_exceptions(func):
    @wraps(func)
    async def wrapper(q, *args, **kwargs):
        try:
            return await func(q, *args, **kwargs)
        except Exception as exc:
            logging.exception(exc)
            return await mark_as_exception(q, message=traceback.format_exc())

    return wrapper


task_registry = {}
task_mapping = {}


def register_task(task_name, fn):
    if task_name in task_registry:
        raise Exception(f"Task `{task_name}` is already registered. Choose another name")
    task_registry[task_name] = fn


def register_mapping(mapping):
    task_mapping.update(mapping)


apply_entry_strategy = apply_entry_strategy_factory()


@catch_queue_exceptions
async def process_queue_entry(q):
    q["processing"] = False
    if not q.get("payloadHash"):
        q["payloadHash"] = get_dict_hash(q["payload"])

    process_fn, check_duplicates = get_fn_for_export_queue(q)

    if check_duplicates and await has_duplicates(q):
        return await mark_as_duplicated(q, message="Duplicated due to hash")

    resource = (
        sdk.client.resource(q["payload"]["resourceType"], **q["payload"])
        if "resourceType" in q["payload"]
        else q["payload"]
    )
    return await process_fn(
        q, resource, lambda res, **strategy: apply_entry_strategy(q, res, **strategy)
    )


async def add_to_export_queue(source, priority, resources, immediate=False):
    if isinstance(resources, list):
        affected_resources = [res.to_reference() for res in resources if "id" in res]
        resources = make_bundle(resources, "collection")
    else:
        affected_resources = [resources.to_reference()] if "id" in resources else []
    res = sdk.client.resource(
        "TaskQueue",
        **{
            "source": source,
            "status": "pending",
            "priority": priority,
            "payload": resources.serialize()
            if isinstance(resources, AsyncAidboxResource)
            else resources,
            "affectedResources": affected_resources,
        },
    )
    await res.save()

    if immediate:
        asyncio.get_event_loop().create_task(process_queue_entry(res))

    return res
