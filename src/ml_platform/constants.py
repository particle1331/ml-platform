BEAT_QUEUE = "beat"
DEFAULT_QUEUE = "default"
TASK_RETENTION_SECONDS = 3 * 24 * 60 * 60

# Fully qualified names of every task the platform can execute.
# The UI's task registry is code-configured from this tuple, so a task type
# appears in the registry even when it has no recent runs.
TASK_REGISTRY = (
    "ml_platform.tasks.add",
    "ml_platform.tasks.count_pending",
    "ml_platform.tasks.one_over",
    "ml_platform.tasks.wait",
)
