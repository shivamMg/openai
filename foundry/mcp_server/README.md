# Customer Service MCP Server

MCP server implementing customer service tools (order management, user lookup, product catalog) over Streamable HTTP transport.

## Tools

16 tools available: `calculate`, `find_user_id_by_email`, `find_user_id_by_name_zip`, `list_all_product_types`, `get_product_details`, `get_user_details`, `get_order_details`, `cancel_pending_order`, `modify_pending_order_items`, `modify_pending_order_payment`, `modify_pending_order_address`, `modify_user_address`, `exchange_delivered_order_items`, `return_delivered_order_items`, `transfer_to_human_agents`.

## Run Locally

```bash
pip install -r requirements.txt
MCP_API_KEY=your-secret-key python mcp_server.py
```

Server starts at `http://localhost:8000`. Health check: `GET /health`.

## Run with Docker

```bash
docker build -t mcp-server .
docker run -p 8000:8000 -e MCP_API_KEY=your-secret-key mcp-server
```

## Deploy to Azure Container Apps

Prerequisites: [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli), an Azure subscription.

```bash
# Set variables
RESOURCE_GROUP=mcp-server-rg
LOCATION=eastus
MCP_API_KEY=your-secret-key

# Create resource group
az group create -n $RESOURCE_GROUP -l $LOCATION

# Deploy infrastructure (ACR + Container App Environment + Container App)
az deployment group create -g $RESOURCE_GROUP \
  --template-file deploy_to_azure.bicep \
  --parameters mcpApiKey=$MCP_API_KEY

# Get ACR name from outputs
ACR_NAME=$(az deployment group show -g $RESOURCE_GROUP -n deploy_to_azure \
  --query properties.outputs.acrName.value -o tsv)

# Build and push image to ACR
az acr build -t mcp-server:latest -r $ACR_NAME .

# Update container app with the built image
az containerapp update -n mcp-server -g $RESOURCE_GROUP \
  --image ${ACR_NAME}.azurecr.io/mcp-server:latest

# Get the app URL
az containerapp show -n mcp-server -g $RESOURCE_GROUP \
  --query properties.configuration.ingress.fqdn -o tsv
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `MCP_API_KEY` | API key for authentication (checked via `X-MCP-API-Key` header) |
| `PORT` | Server port (default: `8000`) |

## MCP Client Configuration

```json
{
  "mcpServers": {
    "customer-service": {
      "url": "https://<your-app>.azurecontainerapps.io/mcp/",
      "headers": {
        "X-MCP-API-Key": "your-secret-key"
      }
    }
  }
}
```
