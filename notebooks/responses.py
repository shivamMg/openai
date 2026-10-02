import json


def convert_chat_messages_to_responses(messages):
    """Convert chat completion messages to Responses API input format.

    Mapping:
    - system  → developer role
    - user    → user role (unchanged)
    - assistant (text only) → assistant role
    - assistant with tool_calls → assistant role text entries (keeps role on every item)
    - tool    → assistant role text entry (keeps role on every item)

    Note: Some eval backends require each trajectory item to include a "role" key.
    This converter intentionally avoids emitting role-less typed items.
    """
    result = []
    for msg in messages:
        role = msg.get("role")
        if role == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                fn = tc["function"]
                arguments = fn["arguments"]
                if isinstance(arguments, dict):
                    arguments = json.dumps(arguments)
                call_id = tc.get("id", "")
                result.append({
                    "role": "assistant",
                    "content": f"[tool_call:{call_id}] {fn['name']}({arguments})",
                })

        elif role == "tool":
            call_id = msg.get("tool_call_id", "")
            result.append({
                "role": "assistant",
                "content": f"[tool_result:{call_id}] {msg.get('content', '')}",
            })

        else:
            result.append(msg)

    return result
