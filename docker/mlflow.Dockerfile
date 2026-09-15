FROM ghcr.io/mlflow/mlflow:v3.16.0-full

RUN pip install --no-cache-dir azure-storage-blob==12.28.0
