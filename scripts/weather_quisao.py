"""Ask OpenAI for the current weather in Quisao, Pililla, Rizal."""

from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

import mlflow
from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

LOCATION = "Quisao, Pililla, Rizal"
API_URL = "https://api.open-meteo.com/v1/forecast"
MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4-nano")
TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000")
EXPERIMENT_NAME = "Prompts"

WEATHER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather for a latitude and longitude.",
            "parameters": {
                "type": "object",
                "properties": {
                    "latitude": {"type": "number"},
                    "longitude": {"type": "number"},
                },
                "required": ["latitude", "longitude"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    }
]

WEATHER_CODES = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "dense drizzle",
    61: "slight rain",
    63: "moderate rain",
    65: "heavy rain",
    71: "slight snow",
    73: "moderate snow",
    75: "heavy snow",
    80: "slight rain showers",
    81: "moderate rain showers",
    82: "violent rain showers",
    95: "thunderstorm",
    96: "thunderstorm with slight hail",
    99: "thunderstorm with heavy hail",
}


def fetch_weather(latitude: float, longitude: float) -> dict[str, object]:
    """Fetch current conditions from Open-Meteo for a coordinate pair."""
    query = urlencode(
        {
            "latitude": latitude,
            "longitude": longitude,
            "current": (
                "temperature_2m,relative_humidity_2m,apparent_temperature,"
                "precipitation,weather_code,wind_speed_10m"
            ),
            "temperature_unit": "celsius",
            "wind_speed_unit": "kmh",
            "precipitation_unit": "mm",
            "timezone": "Asia/Manila",
        }
    )

    try:
        with urlopen(f"{API_URL}?{query}", timeout=15) as response:
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError) as error:
        raise RuntimeError(f"Weather request failed: {error}") from error

    if "current" not in payload:
        raise RuntimeError(f"Weather response did not contain current data: {payload}")
    return payload


def get_weather(latitude: float, longitude: float) -> dict[str, object]:
    """Implement the weather function exposed to the OpenAI model."""
    payload = fetch_weather(latitude, longitude)
    current = payload["current"]
    units = payload["current_units"]
    weather_code = int(current["weather_code"])
    return {
        "latitude": latitude,
        "longitude": longitude,
        "observed_at": f"{current['time']} (Asia/Manila)",
        "conditions": WEATHER_CODES.get(weather_code, f"weather code {weather_code}"),
        "temperature": f"{current['temperature_2m']} {units['temperature_2m']}",
        "feels_like": (
            f"{current['apparent_temperature']} "
            f"{units['apparent_temperature']}"
        ),
        "humidity": (
            f"{current['relative_humidity_2m']} "
            f"{units['relative_humidity_2m']}"
        ),
        "precipitation": f"{current['precipitation']} {units['precipitation']}",
        "wind": f"{current['wind_speed_10m']} {units['wind_speed_10m']}",
    }


def main() -> None:
    """Ask OpenAI to call the weather function, then print its answer."""
    mlflow.set_tracking_uri(TRACKING_URI)
    mlflow.set_experiment(EXPERIMENT_NAME)
    mlflow.openai.autolog()

    with mlflow.start_run(run_name="weather-quisao"):
        client = OpenAI()
        messages: list[object] = [
            {
                "role": "system",
                "content": (
                    "You are a helpful weather assistant. "
                    "Answer concisely based on data."
                )
            },
            {
                "role": "user",
                "content": f"What is the current weather in {LOCATION}?",
            }
        ]

        completion = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=WEATHER_TOOLS,
            tool_choice={
                "type": "function",
                "function": {"name": "get_weather"},
            },
        )

        assistant_message = completion.choices[0].message
        messages.append(assistant_message)
        for tool_call in assistant_message.tool_calls or []:
            if tool_call.function.name != "get_weather":
                continue

            arguments = json.loads(tool_call.function.arguments)
            weather = get_weather(arguments["latitude"], arguments["longitude"])
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(weather),
                }
            )

        completion = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=WEATHER_TOOLS,
        )

        return completion.choices[0].message.content


if __name__ == "__main__":
    main()
