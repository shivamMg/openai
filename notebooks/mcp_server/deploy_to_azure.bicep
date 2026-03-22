@description('Location for all resources')
param location string = resourceGroup().location

@secure()
@description('API key for MCP server authentication')
param mcpApiKey string

@description('Name of the container app')
param appName string = 'retail-mcp'

var uniqueSuffix = substring(uniqueString(resourceGroup().id), 0, 5)
var fullAppName = '${appName}-${uniqueSuffix}'
var acrName = 'retailmcp${uniqueSuffix}acr'

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: true
  }
}

resource env 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: '${fullAppName}-env'
  location: location
  properties: {}
}

resource app 'Microsoft.App/containerApps@2023-05-01' = {
  name: fullAppName
  location: location
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      secrets: [
        {
          name: 'mcp-api-key'
          value: mcpApiKey
        }
        {
          name: 'acr-password'
          value: acr.listCredentials().passwords[0].value
        }
      ]
      registries: [
        {
          server: acr.properties.loginServer
          username: acr.listCredentials().username
          passwordSecretRef: 'acr-password'
        }
      ]
      ingress: {
        external: true
        targetPort: 8000
        transport: 'http'
      }
    }
    template: {
      containers: [
        {
          name: fullAppName
          image: 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            {
              name: 'MCP_API_KEY'
              secretRef: 'mcp-api-key'
            }
            {
              name: 'PORT'
              value: '8000'
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
    }
  }
}

output acrName string = acr.name
output acrLoginServer string = acr.properties.loginServer
output appName string = app.name
output appUrl string = 'https://${app.properties.configuration.ingress.fqdn}'
