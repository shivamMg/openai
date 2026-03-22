import os
import json
import ast
import logging
import operator
import uuid
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

logger = logging.getLogger(__name__)

MCP_API_KEY = os.environ["MCP_API_KEY"]

base_dir = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(base_dir, "db.json")) as f:
    db = json.load(f)

mcp = FastMCP(
    "Retail MCP",
    # Disable DNS rebinding protection to avoid "Invalid Host header" error in Azure Container Apps.
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

# Safe math evaluator
SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval(node):
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in SAFE_OPS:
        return SAFE_OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in SAFE_OPS:
        return SAFE_OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("Unsupported expression")


@mcp.tool(description="Calculate the result of a mathematical expression.")
def calculate(expression: str) -> str:
    try:
        result = _safe_eval(ast.parse(expression, mode="eval"))
        return json.dumps({"result": result})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool(description="Find user id by email.")
def find_user_id_by_email(email: str) -> str:
    for uid, user in db["users"].items():
        if user["email"] == email:
            return json.dumps({"user_id": uid})
    return json.dumps({"error": "User not found"})


@mcp.tool(description="Find user id by first name, last name, and zip code.")
def find_user_id_by_name_zip(first_name: str, last_name: str, zip: str) -> str:
    for uid, user in db["users"].items():
        if (
            user["name"]["first_name"].lower() == first_name.lower()
            and user["name"]["last_name"].lower() == last_name.lower()
            and user["address"]["zip"] == zip
        ):
            return json.dumps({"user_id": uid})
    return json.dumps({"error": "User not found"})


@mcp.tool(description="List the name and product id of all product types.")
def list_all_product_types() -> str:
    return json.dumps(
        [{"name": p["name"], "product_id": pid} for pid, p in db["products"].items()]
    )


@mcp.tool(description="Get the inventory details of a product.")
def get_product_details(product_id: str) -> str:
    if product_id in db["products"]:
        return json.dumps(db["products"][product_id])
    return json.dumps({"error": "Product not found"})


@mcp.tool(description="Get the details of a user.")
def get_user_details(user_id: str) -> str:
    if user_id in db["users"]:
        return json.dumps(db["users"][user_id])
    return json.dumps({"error": "User not found"})


@mcp.tool(description="Get the status and details of an order.")
def get_order_details(order_id: str) -> str:
    if order_id in db["orders"]:
        return json.dumps(db["orders"][order_id])
    return json.dumps({"error": "Order not found"})


@mcp.tool(
    description="Cancel a pending order. Reason must be 'no longer needed' or 'ordered by mistake'."
)
def cancel_pending_order(order_id: str, reason: str) -> str:
    if order_id not in db["orders"]:
        return json.dumps({"error": "Order not found"})
    order = db["orders"][order_id]
    if order.get("status") != "pending":
        return json.dumps(
            {"error": f"Order is '{order.get('status')}', only pending orders can be cancelled"}
        )
    if reason not in ("no longer needed", "ordered by mistake"):
        return json.dumps({"error": "Reason must be 'no longer needed' or 'ordered by mistake'"})
    order["status"] = "cancelled"
    total = sum(item["price"] for item in order["items"])
    pm = order["payment_history"][0]["payment_method_id"]
    order["payment_history"].append(
        {"transaction_type": "refund", "amount": total, "payment_method_id": pm, "reason": reason}
    )
    return json.dumps(order)


@mcp.tool(description="Modify items in a pending order to new items of the same product type.")
def modify_pending_order_items(
    order_id: str, item_ids: list[str], new_item_ids: list[str], payment_method_id: str
) -> str:
    if order_id not in db["orders"]:
        return json.dumps({"error": "Order not found"})
    order = db["orders"][order_id]
    if order.get("status") != "pending":
        return json.dumps(
            {"error": f"Order is '{order.get('status')}', only pending orders can be modified"}
        )
    if len(item_ids) != len(new_item_ids):
        return json.dumps({"error": "item_ids and new_item_ids must have the same length"})
    old_total = sum(i["price"] for i in order["items"])
    for old_id, new_id in zip(item_ids, new_item_ids):
        item = next((i for i in order["items"] if i["item_id"] == old_id), None)
        if not item:
            return json.dumps({"error": f"Item {old_id} not found in order"})
        product = db["products"].get(item["product_id"])
        if not product or new_id not in product["variants"]:
            return json.dumps({"error": f"Item {new_id} is not a valid variant of {item['name']}"})
        variant = product["variants"][new_id]
        item["item_id"] = new_id
        item["price"] = variant["price"]
        item["options"] = variant["options"]
    new_total = sum(i["price"] for i in order["items"])
    diff = round(new_total - old_total, 2)
    if diff != 0:
        order["payment_history"].append(
            {
                "transaction_type": "payment" if diff > 0 else "refund",
                "amount": abs(diff),
                "payment_method_id": payment_method_id,
            }
        )
    return json.dumps(order)


@mcp.tool(description="Modify the payment method of a pending order.")
def modify_pending_order_payment(order_id: str, payment_method_id: str) -> str:
    if order_id not in db["orders"]:
        return json.dumps({"error": "Order not found"})
    order = db["orders"][order_id]
    if order.get("status") != "pending":
        return json.dumps(
            {"error": f"Order is '{order.get('status')}', only pending orders can be modified"}
        )
    order["payment_history"][0]["payment_method_id"] = payment_method_id
    return json.dumps(order)


@mcp.tool(description="Modify the shipping address of a pending order.")
def modify_pending_order_address(
    order_id: str, address1: str, address2: str, city: str, state: str, country: str, zip: str
) -> str:
    if order_id not in db["orders"]:
        return json.dumps({"error": "Order not found"})
    order = db["orders"][order_id]
    if order.get("status") != "pending":
        return json.dumps(
            {"error": f"Order is '{order.get('status')}', only pending orders can be modified"}
        )
    order["address"] = {
        "address1": address1,
        "address2": address2,
        "city": city,
        "state": state,
        "country": country,
        "zip": zip,
    }
    return json.dumps(order)


@mcp.tool(description="Modify the default address of a user.")
def modify_user_address(
    user_id: str, address1: str, address2: str, city: str, state: str, country: str, zip: str
) -> str:
    if user_id not in db["users"]:
        return json.dumps({"error": "User not found"})
    db["users"][user_id]["address"] = {
        "address1": address1,
        "address2": address2,
        "city": city,
        "state": state,
        "country": country,
        "zip": zip,
    }
    return json.dumps(db["users"][user_id])


@mcp.tool(description="Exchange items in a delivered order to new items of the same product type.")
def exchange_delivered_order_items(
    order_id: str, item_ids: list[str], new_item_ids: list[str], payment_method_id: str
) -> str:
    if order_id not in db["orders"]:
        return json.dumps({"error": "Order not found"})
    order = db["orders"][order_id]
    if order.get("status") != "delivered":
        return json.dumps(
            {"error": f"Order is '{order.get('status')}', only delivered orders can be exchanged"}
        )
    if len(item_ids) != len(new_item_ids):
        return json.dumps({"error": "item_ids and new_item_ids must have the same length"})
    for old_id, new_id in zip(item_ids, new_item_ids):
        item = next((i for i in order["items"] if i["item_id"] == old_id), None)
        if not item:
            return json.dumps({"error": f"Item {old_id} not found in order"})
        product = db["products"].get(item["product_id"])
        if not product or new_id not in product["variants"]:
            return json.dumps({"error": f"Item {new_id} is not a valid variant of {item['name']}"})
        variant = product["variants"][new_id]
        diff = round(variant["price"] - item["price"], 2)
        item["item_id"] = new_id
        item["price"] = variant["price"]
        item["options"] = variant["options"]
        if diff != 0:
            order["payment_history"].append(
                {
                    "transaction_type": "payment" if diff > 0 else "refund",
                    "amount": abs(diff),
                    "payment_method_id": payment_method_id,
                }
            )
    order["status"] = "exchange requested"
    return json.dumps(order)


@mcp.tool(description="Return some items of a delivered order.")
def return_delivered_order_items(order_id: str, item_ids: list[str], payment_method_id: str) -> str:
    if order_id not in db["orders"]:
        return json.dumps({"error": "Order not found"})
    order = db["orders"][order_id]
    if order.get("status") != "delivered":
        return json.dumps(
            {"error": f"Order is '{order.get('status')}', only delivered orders can be returned"}
        )
    refund = 0.0
    for item_id in item_ids:
        item = next((i for i in order["items"] if i["item_id"] == item_id), None)
        if not item:
            return json.dumps({"error": f"Item {item_id} not found in order"})
        refund += item["price"]
    order["status"] = "return requested"
    order["payment_history"].append(
        {"transaction_type": "refund", "amount": round(refund, 2), "payment_method_id": payment_method_id}
    )
    return json.dumps(order)


@mcp.tool(description="Transfer the user to a human agent, with a summary of the user's issue.")
def transfer_to_human_agents(summary: str) -> str:
    return json.dumps(
        {"message": "Transfer initiated. A human agent will follow up shortly.", "summary": summary}
    )


mcp_http_app = mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(app):
    async with mcp_http_app.router.lifespan_context(mcp_http_app):
        yield


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)
    if MCP_API_KEY and request.headers.get("x-mcp-api-key") != MCP_API_KEY:
        return Response("Unauthorized", status_code=401)
    return await call_next(request)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/tools")
async def tools(request: Request):
    """OpenAI function_call compatible endpoint."""
    body = await request.json()
    name = body.get("name")
    call_id = body.get("call_id") or f"call_{uuid.uuid4().hex[:24]}"
    request_id = body.get("id")
    arguments_raw = body.get("arguments", "{}")

    logger.info("[call_id:%s] /tools Request: id=%s name=%s arguments=%s", call_id, request_id, name, arguments_raw)

    try:
        kwargs = json.loads(arguments_raw)
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning("[call_id:%s] Invalid arguments for tool %s: %s", call_id, name, e)
        return JSONResponse(
            status_code=400,
            content={"error": f"Invalid arguments: {e}"},
        )

    try:
        result = await mcp.call_tool(name, kwargs)
        # call_tool returns (content_blocks, structured); extract text from first block
        content_blocks = result[0] if isinstance(result, tuple) else result
        output = content_blocks[0].text if content_blocks else ""
    except Exception as e:
        logger.warning("[call_id:%s] Tool call failed: name=%s error=%s", call_id, name, e)
        return JSONResponse(
            status_code=400,
            content={"error": str(e)},
        )

    response = {
        "type": "function_call_output",
        "id": request_id,
        "call_id": call_id,
        "output": output,
    }
    logger.info("[call_id:%s] /tools Response: %s", call_id, response)
    return response


app.mount("/", mcp_http_app)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
