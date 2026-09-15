"""Train a small regression model and log it to the local MLflow server."""

from __future__ import annotations

import os

import mlflow
import mlflow.sklearn
from mlflow.models import infer_signature
from sklearn.datasets import make_regression
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_squared_error
from sklearn.model_selection import train_test_split


TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000")
EXPERIMENT_NAME = "Default"


def main() -> None:
    """Train, evaluate, and persist one model run in MLflow."""
    mlflow.set_tracking_uri(TRACKING_URI)
    mlflow.set_experiment(EXPERIMENT_NAME)

    features, targets = make_regression(
        n_samples=200,
        n_features=4,
        noise=10.0,
        random_state=42,
    )
    features_train, features_test, targets_train, targets_test = train_test_split(
        features,
        targets,
        test_size=0.2,
        random_state=42,
    )

    model = Ridge(alpha=1.0)
    with mlflow.start_run(run_name="basic-ridge-regression") as run:
        model.fit(features_train, targets_train)
        predictions = model.predict(features_test)
        mse = mean_squared_error(targets_test, predictions)

        mlflow.log_params(
            {
                "model": "ridge",
                "alpha": model.alpha,
                "n_samples": len(features),
                "n_features": features.shape[1],
                "test_size": 0.2,
                "random_state": 42,
            }
        )
        mlflow.log_metric("mse", mse)
        mlflow.sklearn.log_model(
            model,
            name="model",
            signature=infer_signature(features_train, model.predict(features_train)),
            input_example=features_test[:1],
        )

        print(f"tracking_uri: {TRACKING_URI}")
        print(f"experiment: {EXPERIMENT_NAME}")
        print(f"run_id: {run.info.run_id}")
        print(f"mse: {mse:.4f}")
        print(f"model_uri: runs:/{run.info.run_id}/model")
        print(f"artifact_uri: {run.info.artifact_uri}")


if __name__ == "__main__":
    main()
