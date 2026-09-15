"""Create required Blob containers in the local Azurite emulator."""

from __future__ import annotations

import os
import time

from azure.core.exceptions import ResourceExistsError
from azure.storage.blob import BlobServiceClient


CONTAINER_NAME = "mlflow-artifacts"
MAX_ATTEMPTS = 30
RETRY_SECONDS = 2


def main() -> None:
    """Create the MLflow artifact container, retrying until Azurite is ready."""
    service = BlobServiceClient.from_connection_string(
        os.environ["AZURE_STORAGE_CONNECTION_STRING"]
    )

    for attempt in range(MAX_ATTEMPTS):
        try:
            service.create_container(CONTAINER_NAME)
        except ResourceExistsError:
            print(f"Azurite container already exists: {CONTAINER_NAME}")
            return
        except Exception as error:
            if attempt == MAX_ATTEMPTS - 1:
                raise
            print(f"Waiting for Azurite: {error}")
            time.sleep(RETRY_SECONDS)
        else:
            print(f"Created Azurite container: {CONTAINER_NAME}")
            return


if __name__ == "__main__":
    main()
