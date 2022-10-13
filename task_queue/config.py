import os

task_always_eager = os.environ.get("TASK_ALWAYS_EAGER", "False") == "True"
