meta_resources = {}

entities = {
    "TaskQueue": {
        "history": "none",
        "attrs": {
            "source": {
                "type": "code",
                "isRequired": True,
                "search": {"name": "source", "type": "token"},
            },
            "status": {
                "type": "code",
                "isRequired": True,
                "enum": [
                    "pending",
                    "synced",
                    "rejected",
                    "duplicated",
                    "failed",
                    "exception",
                    "skipped",
                    "immediate",
                ],
                "search": {"name": "status", "type": "token"},
            },
            "priority": {
                "type": "integer",
                "isRequired": True,
                "search": {"name": "priority", "type": "token"},
            },
            "processing": {
                "type": "boolean",
                "search": {"name": "processing", "type": "token"},
            },
            "processingMessage": {"type": "string"},
            "processingInfo": {"isOpen": True},
            "payload": {"isOpen": True, "isRequired": True},
            "payloadHash": {
                "type": "string",
                "search": {"name": "payload-hash", "type": "token"},
            },
            "affectedResources": {
                "isCollection": True,
                "type": "Reference",
                "search": {"name": "affected-resources", "type": "reference"},
            },
        },
    },
}
