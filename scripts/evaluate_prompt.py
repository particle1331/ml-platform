"""Evaluate a small question-answering prompt with MLflow."""

from __future__ import annotations

import os

import mlflow
from dotenv import load_dotenv
from mlflow.genai import scorer
from mlflow.genai.scorers import Correctness, Guidelines
from openai import OpenAI


load_dotenv()

MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4-nano")
JUDGE_MODEL = os.getenv("MLFLOW_JUDGE_MODEL", "openai:/gpt-5.4-nano")
TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000")
EXPERIMENT_NAME = "Prompts"

SYSTEM_PROMPT = "You are a helpful assistant. Answer questions concisely."

EVAL_DATASET = [
    {
        "inputs": {"question": "What is the capital of France?"},
        "expectations": {"expected_response": "Paris"},
    },
    {
        "inputs": {"question": "Who was the first person to build an airplane?"},
        "expectations": {"expected_response": "Wright Brothers"},
    },
    {
        "inputs": {"question": "Who wrote Romeo and Juliet?"},
        "expectations": {"expected_response": "William Shakespeare"},
    },
]


client: OpenAI | None = None


def ask_agent(question: str) -> str:
    """Generate one answer using the prompt being evaluated."""
    if client is None:
        raise RuntimeError("OpenAI client has not been initialized")

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ],
    )
    return response.choices[0].message.content or ""


@scorer
def is_concise(outputs: str) -> bool:
    """Pass when the answer contains no more than five words."""
    return len(outputs.split()) <= 5


def main() -> None:
    """Run the evaluation and print its MLflow run metrics."""
    mlflow.set_tracking_uri(TRACKING_URI)
    mlflow.set_experiment(EXPERIMENT_NAME)
    mlflow.openai.autolog()

    global client
    client = OpenAI()

    results = mlflow.genai.evaluate(
        data=EVAL_DATASET,
        predict_fn=ask_agent,
        scorers=[
            Correctness(model=JUDGE_MODEL),
            Guidelines(
                name="is_english",
                guidelines="The answer must be written in English.",
                model=JUDGE_MODEL,
            ),
            is_concise,
        ],
    )

    print(f"run_id: {results.run_id}")
    for name, value in results.metrics.items():
        print(f"{name}: {value}")


if __name__ == "__main__":
    main()
