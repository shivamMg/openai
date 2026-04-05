<#
.SYNOPSIS
    Deploy or redeploy the MCP server to Azure Container Apps.

.DESCRIPTION
    Deploys infrastructure via Bicep (ACR + Container App Environment + Container App),
    builds the Docker image in ACR, and updates the container app.
    On redeploy, skips infrastructure if it already exists and just rebuilds + updates.

.PARAMETER ResourceGroup
    Azure resource group name.

.PARAMETER Subscription
    Azure subscription name or ID.

.PARAMETER McpApiKey
    API key for MCP server authentication.

.PARAMETER Location
    Azure region (default: location of existing resource group, or eastus2).

.EXAMPLE
    .\deploy.ps1 -Subscription "AutoML Demo" -ResourceGroup "smamgain-rg" -McpApiKey "my-secret-key"
#>

param(
    [Parameter(Mandatory)][string]$Subscription,
    [Parameter(Mandatory)][string]$ResourceGroup,
    [Parameter(Mandatory)][string]$McpApiKey,
    [string]$Location
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "`n=== Setting subscription ===" -ForegroundColor Cyan
az account set --subscription $Subscription
if ($LASTEXITCODE -ne 0) { throw "Failed to set subscription." }

# Resolve location from existing RG or default
if (-not $Location) {
    $Location = az group show -n $ResourceGroup --query location -o tsv 2>$null
    if (-not $Location) { $Location = "eastus2" }
}

# Ensure resource group exists
Write-Host "`n=== Ensuring resource group '$ResourceGroup' in '$Location' ===" -ForegroundColor Cyan
az group create -n $ResourceGroup -l $Location -o none

# Deploy Bicep template
Write-Host "`n=== Deploying infrastructure (Bicep) ===" -ForegroundColor Cyan
$deployment = az deployment group create -g $ResourceGroup `
    --template-file "$ScriptDir\deploy_to_azure.bicep" `
    --parameters mcpApiKey=$McpApiKey location=$Location `
    --query "properties.outputs" -o json | ConvertFrom-Json

if ($LASTEXITCODE -ne 0) { throw "Bicep deployment failed." }

$AcrName = $deployment.acrName.value
$AppName = $deployment.appName.value
$AppUrl = $deployment.appUrl.value

Write-Host "  ACR: $AcrName" -ForegroundColor Green
Write-Host "  App: $AppName" -ForegroundColor Green
Write-Host "  URL: $AppUrl" -ForegroundColor Green

# Build and push image
Write-Host "`n=== Building image in ACR ===" -ForegroundColor Cyan
az acr build -t mcp-server:latest -r $AcrName $ScriptDir --no-logs
if ($LASTEXITCODE -ne 0) { throw "ACR build failed." }
Write-Host "  Image built successfully." -ForegroundColor Green

# Update container app with new image
Write-Host "`n=== Updating container app '$AppName' ===" -ForegroundColor Cyan
az containerapp update -n $AppName -g $ResourceGroup `
    --image "$AcrName.azurecr.io/mcp-server:latest" -o none
if ($LASTEXITCODE -ne 0) { throw "Container app update failed." }

# Verify health
Write-Host "`n=== Verifying deployment ===" -ForegroundColor Cyan
$healthUrl = "$AppUrl/tools"
try {
    $response = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 30
    if ($response.status -eq "ok") {
        Write-Host "  Health check passed." -ForegroundColor Green
    } else {
        Write-Host "  Health check returned unexpected response: $($response | ConvertTo-Json)" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  Health check failed (server may still be starting): $_" -ForegroundColor Yellow
}

Write-Host "`n=== Deployment complete ===" -ForegroundColor Green
Write-Host "  URL: $AppUrl"
Write-Host "  MCP endpoint: $AppUrl/mcp/"
Write-Host "  Tools endpoint: $AppUrl/tools"
