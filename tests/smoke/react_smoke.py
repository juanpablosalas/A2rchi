#!/usr/bin/env python3
"""ReAct smoke check using chat streaming endpoint."""
import json
import os
import sys
import time
import uuid

import requests


def _fail(message: str) -> None:
    print(f"[react-smoke] ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def _info(message: str) -> None:
    print(f"[react-smoke] {message}")


def _stream_chat(base_url: str, payload: dict) -> tuple[bool, bool]:
    stream_url = f"{base_url}/api/get_chat_response_stream"
    _info(f"POST {stream_url}")
    tool_call_seen = False
    final_seen = False
    try:
        with requests.post(stream_url, json=payload, stream=True, timeout=300) as resp:
            if resp.status_code != 200:
                _fail(f"Stream request failed: HTTP {resp.status_code}")
            for raw_line in resp.iter_lines():
                if not raw_line:
                    continue
                try:
                    event = json.loads(raw_line.decode("utf-8"))
                except Exception:
                    continue
                event_type = event.get("type")
                if event_type == "error":
                    _fail(f"Stream error: {event}")
                if event_type == "step" and event.get("step_type") == "tool_call":
                    tool_call_seen = True
                if event_type == "final":
                    final_seen = True
                    break
    except Exception as exc:
        _fail(f"Stream request failed: {exc}")
    return tool_call_seen, final_seen


def main() -> None:
    base_url = os.getenv("BASE_URL", "http://localhost:2786").rstrip("/")
    timeout = int(os.getenv("TIMEOUT", "180"))
    client_id = os.getenv("CLIENT_ID", str(uuid.uuid4()))
    prompt = os.getenv(
        "REACT_SMOKE_PROMPT",
        "Use the search_local_files tool to find the phrase "
        "'Smoke test seed document' and summarize the result.",
    )
    config_name = os.getenv("A2RCHI_CONFIG_NAME")

    _info(f"Waiting for {base_url}/api/health (timeout {timeout}s) ...")
    start_ts = time.time()
    while True:
        try:
            resp = requests.get(f"{base_url}/api/health", timeout=5)
            if resp.status_code == 200:
                break
        except Exception:
            pass
        if time.time() - start_ts > timeout:
            _fail("Timed out waiting for chat app health endpoint")
        time.sleep(2)

    payload = {
        "last_message": [["User", prompt]],
        "conversation_id": None,
        "is_refresh": False,
        "client_sent_msg_ts": int(time.time() * 1000),
        "client_timeout": 300000,
        "client_id": client_id,
        "include_agent_steps": False,
        "include_tool_steps": True,
    }
    if config_name:
        payload["config_name"] = config_name

    tool_call_seen, final_seen = _stream_chat(base_url, payload)
    if not tool_call_seen:
        _fail("No tool_call events observed in stream")
    if not final_seen:
        _fail("No final response observed in stream")
    _info("ReAct streaming smoke passed")


if __name__ == "__main__":
    main()
