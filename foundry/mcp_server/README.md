# Retail MCP Server

MCP server implementing customer service tools (order management, user lookup, product catalog) over Streamable HTTP transport.

| File | Description |
|------|-------------|
| `mcp_server.py` | Server to expose MCP `/mcp` and OpenAI `/tools` endpoints |
| `db.json` | Mock database (users, orders, products) |
| `requirements.txt` | Python dependencies |
| `Dockerfile` | Container image definition |
| `deploy_to_azure.bicep` | Azure infrastructure (ACR + Container App) |
| `deploy_to_azure.ps1` | One-command deploy/redeploy script |

## Run Locally

```bash
pip install -r requirements.txt
$env:MCP_API_KEY="your-secret-key"  # powershell
python mcp_server.py
```

Server starts at `http://localhost:8000`. Health check: `GET /health`.

### Run with Docker

```bash
docker build -t mcp-server .
docker run -p 8000:8000 -e MCP_API_KEY=your-secret-key mcp-server
```

## Deploy to Azure Container Apps

Prerequisites: [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli), an Azure subscription, PowerShell.

```powershell
.\deploy_to_azure.ps1 -Subscription "your-azure-subscription" -ResourceGroup "your-rg" -McpApiKey "your-secret-key"
```

The script handles everything: resource group creation, Bicep infrastructure deployment (ACR + Container App), Docker image build, container app update, and health check verification. Rerun the same command to redeploy after code changes.

## Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/health` | GET | No | Health check |
| `/mcp/` | POST | Yes | MCP Streamable HTTP transport |
| `/tools` | POST | Yes | OpenAI function-call compatible endpoint |

For authentication, set `X-MCP-API-Key` header to the value of `MCP_API_KEY` env var.

### `/tools` endpoint

Request:
```json
{
  "type": "function_call",
  "id": "fc_123",
  "call_id": "call_123",
  "name": "calculate",
  "arguments": "{\"expression\": \"2 + 3\"}"
}
```

Response:
```json
{
  "type": "function_call_output",
  "id": "fc_123",
  "call_id": "call_123",
  "output": "{\"result\": 5}"
}
```

### Available tools

16 tools available: `calculate`, `find_user_id_by_email`, `find_user_id_by_name_zip`, `list_all_product_types`, `get_product_details`, `get_user_details`, `get_order_details`, `cancel_pending_order`, `modify_pending_order_items`, `modify_pending_order_payment`, `modify_pending_order_address`, `modify_user_address`, `exchange_delivered_order_items`, `return_delivered_order_items`, `transfer_to_human_agents`.

### MCP Client Configuration

```json
{
  "mcpServers": {
    "retail-mcp": {
      "url": "https://<your-app>.azurecontainerapps.io/mcp/",
      "headers": {
        "X-MCP-API-Key": "your-secret-key"
      }
    }
  }
}
```
