"""The producer serves /ui alongside its existing API surface."""

from fastapi.testclient import TestClient

from ml_platform import producer


def client() -> TestClient:
    # No context manager: the test exercises routing, not Flet's background
    # session manager, which starts with the uvicorn lifespan.
    return TestClient(producer.app)


def test_health_and_openapi_remain_available_with_ui_mounted() -> None:
    response = client().get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    openapi = client().get("/openapi.json").json()
    for path in ("/tasks", "/tasks/{task_id}", "/active", "/pending", "/revoke/{task_id}", "/abort/{task_id}", "/workers"):
        assert path in openapi["paths"], f"missing route {path}"


def test_ui_is_mounted_and_serves_the_flet_client() -> None:
    response = client().get("/ui/", follow_redirects=True)

    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")


def test_task_records_schema_is_unchanged() -> None:
    """The UI work must not change what /tasks returns."""
    openapi = client().get("/openapi.json").json()

    tasks_schema = openapi["paths"]["/tasks"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    # Still a bare array of free-form records — no envelope or typed model.
    assert tasks_schema["type"] == "array"
    assert tasks_schema["items"]["type"] == "object"
    assert "properties" not in tasks_schema["items"]
