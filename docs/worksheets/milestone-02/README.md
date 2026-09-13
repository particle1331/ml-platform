# Milestone 2 — Try the worker transport in Azure

[Worksheet sequence](../README.md) · [Previous: local system](../milestone-01/README.md) · [Next: durable orchestration](../milestone-03/README.md)

**Status: orientation sketch.** This describes the experiment, learning goals, likely modules, and expected evidence. Expand it against milestone 1's actual code before implementation. Commands below are proposed test targets; neither the tests nor the cloud resources exist yet.

You will send a small Celery task through Azure Service Bus, run it in a worker, and retrieve its result from Azure Blob Storage. Then you will run a task longer than a normal message lock and interrupt a worker to observe what the broker does. The question is whether this transport combination supports the platform's execution requirements with a configuration we understand.

Milestone 1 shows the local job workflow. This milestone investigates its cloud transport assumptions. Milestone 3 then uses those findings to implement application recovery. We do not need to deploy the database, control API, dashboard, or MLflow to Azure to answer the initial transport questions.

The first action, once milestone 1 is working, is to record its Celery, Kombu, Azure SDK, and image versions and reproduce one local worker test. Kombu is the library Celery uses to communicate with the broker. Its supported options must be checked for the exact installed release.

Prerequisites are milestone 1's passing local workflow, its dependency lockfile, and a reusable toy task. The cloud experiment also needs an Azure subscription, permission to create the selected resources and assign access, Azure CLI authentication, Docker, and Terraform. Before running it, select a region, resource sizes, maximum replicas, a spending limit, and a cleanup time. Look up current prices when expanding the worksheet; this sketch does not assume the experiment is free.

The concrete walkthrough is: publish a message containing an experiment ID and toy-task inputs; a worker records a distinct execution ID, runs the task, writes its result, and acknowledges the message. An **acknowledgement** tells the broker it can remove that delivery. A **message lock** temporarily reserves a delivery for one receiver. If the lock expires or the worker disappears before acknowledgement, another worker may receive it. **Lock renewal** extends that reservation during long work. Service Bus documents a maximum single lock duration of five minutes, so longer work needs renewal. [Service Bus message locks](https://learn.microsoft.com/en-us/azure/service-bus-messaging/message-transfers-locks-settlement)

Start with a local worker using cloud Service Bus and Blob Storage. Then run the same small probe image in Azure Container Apps (ACA). The cloud probe must not call a laptop-only API: it takes its small input from the message and writes evidence to Azure. Reuse milestone 1's plain job function and input validation, but give this probe its own task wrapper. That isolates broker redelivery from milestone 1's non-expiring `RUNNING` claim, which would otherwise suppress a replacement execution. Full platform recovery is tested in milestone 3.

| Module | What you will add or inspect | Expected checkpoint |
| --- | --- | --- |
| A. Describe the experiment resources | A small Terraform configuration for an isolated resource group, Service Bus queues, and Blob containers; explain every resource before creating it | Configuration validates, the plan contains only intended experiment resources, and resource identifiers are recorded |
| B. Connect a local worker | An explicit Azure configuration profile and probe task; separate queues/prefixes from other environments | Both queues route correctly, success/failure results are retrievable, and the RabbitMQ local suite still passes |
| C. Observe locks and interruption | Execution IDs, timestamps, a long-running probe, and a host-controlled worker termination test | Configured renewal supports the required duration; an unacknowledged interrupted delivery becomes available to a replacement worker |
| D. Run the probe on ACA | The same image, its registry/hosting resources, and managed identity access; initially one worker replica | The Azure worker receives and completes a task without laptop services or embedded storage/broker account keys |
| E. Record the transport decision | A result matrix, reproducible commands, limitations, and experiment cleanup | Required compatibility tests pass for the selected configuration; resources are removed or deliberately retained with ownership recorded |

A **managed identity** is an Azure identity assigned to the workload so it can authenticate without storing account keys. An access **role** grants that identity operations on a resource. Verify the transport's actual queue-management calls as well as send/receive access. The identity used by a queue scaler may also need separate configuration. Queue scaling and scale-in recovery remain later deployment work; this experiment begins with one replica.

The documentation currently describes lock-renewal options in its development reference and labels them as version-dependent. When expanding C, inspect the installed transport source and release documentation before selecting those settings. Do not infer support from the Azure SDK alone. [Kombu Service Bus transport](https://docs.celeryq.dev/projects/kombu/en/latest/reference/kombu.transport.azureservicebus.html)

Suggested additions, to revise after milestone 1:

```text
src/ml_platform/transport_probe.py    # thin experimental Celery task wrapper
infra/terraform/experiments/servicebus/
tests/azure/test_transport.py
tests/azure/test_worker_identity.py
docs/worksheets/milestone-02/NOTES.md
```

Keep the experiment configuration isolated from the eventual milestone 5 environment. Add ACA resources only when reaching D. Terraform state and credentials stay outside Git. Expanding A includes exact setup, plan, apply, and teardown commands and what each does; authoring this sketch does not create Azure resources.

The proposed test entry points are:

```bash
uv run pytest tests/azure/test_transport.py -q
uv run pytest tests/azure/test_worker_identity.py -q
```

The completed worksheet must state environment variables, how workers start, acknowledgement settings, test deadlines, identity roles, and cleanup steps before these commands can be used. Keep cloud tests an explicit suite; fail clearly when requested prerequisites are missing.

The test matrix should distinguish these observations:

- A short success returns the expected payload; an intentional exception produces a failure result.
- Two task types reach their intended queues and are not consumed by the wrong worker pool.
- With late acknowledgement and verified renewal enabled, a task runs beyond five minutes and completes without lock-expiry-driven concurrent execution. Extend the test to the intended maximum task duration once that requirement is known.
- A worker terminated before acknowledgement causes a replacement delivery under the chosen policy. Record delivery/execution counts and bounded recovery time. A second execution is evidence of redelivery, not proof of duplicate-safe application effects.
- A fresh client retrieves the result blob after the original worker is gone.
- The ACA worker authenticates with its assigned identity and finishes without relying on the developer's login or laptop network endpoints.

If a required case fails, capture the smallest reproducer and keep the requirement failing while investigating. Options include a compatible released dependency version, a different broker, or a different worker execution mechanism. Update the architecture decision before proceeding; neither skipped tests nor accepting silent task loss settles compatibility.

In `NOTES.md`, record versions, queue/lock/acknowledgement settings, worker location, experiment and execution IDs, test commands and results, resource duration/cost observations, and the cleanup outcome. Separate established behavior from untested features such as worker inspection, cancellation, and complex Celery workflows.

Before turning this into a full worksheet, resolve the maximum job duration, selected dependency versions, credential path for local/cloud tests, exact experiment resources, and failure-test harness. No changes to milestone 1's job inputs or dashboard arithmetic are required simply to sketch this experiment.
