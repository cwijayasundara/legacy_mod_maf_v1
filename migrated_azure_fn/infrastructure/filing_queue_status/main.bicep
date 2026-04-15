param location string = resourceGroup().location
param functionAppName string
param storageAccountName string
param serviceBusNamespaceName string
param cosmosAccountName string
param cosmosDatabaseName string = 'filingdb'
param botStatusContainerName string = 'botStatus'
param filingCounterContainerName string = 'filingCounter'
param keyVaultName string
param appInsightsName string
param filerTopicName string = 'filer'

resource storage 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageAccountName
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: { allowBlobPublicAccess: false }
}

resource ai 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: { Application_Type: 'web' }
}

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: cosmosAccountName
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    locations: [ { locationName: location, failoverPriority: 0 } ]
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
  }
}

resource cosmosDb 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = {
  name: '${cosmos.name}/${cosmosDatabaseName}'
  properties: { resource: { id: cosmosDatabaseName } }
}

resource botStatus 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  name: '${cosmos.name}/${cosmosDb.name}/${botStatusContainerName}'
  properties: { resource: { id: botStatusContainerName, partitionKey: { paths: ['/id'], kind: 'Hash' } } }
}

resource filingCounter 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  name: '${cosmos.name}/${cosmosDb.name}/${filingCounterContainerName}'
  properties: { resource: { id: filingCounterContainerName, partitionKey: { paths: ['/id'], kind: 'Hash' } } }
}

resource serviceBus 'Microsoft.ServiceBus/namespaces@2022-10-01-preview' = {
  name: serviceBusNamespaceName
  location: location
  sku: { name: 'Standard', tier: 'Standard' }
}

resource filerTopic 'Microsoft.ServiceBus/namespaces/topics@2022-10-01-preview' = {
  name: '${serviceBus.name}/${filerTopicName}'
  properties: { defaultMessageTimeToLive: 'P14D' }
}

resource functionApp 'Microsoft.Web/sites@2023-12-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: resourceId('Microsoft.Web/serverfarms', '${functionAppName}-plan')
    siteConfig: {
      appSettings: [
        { name: 'AzureWebJobsStorage', value: storage.listKeys().keys[0].value }
        { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: ai.properties.ConnectionString }
        { name: 'SERVICEBUS_CONNECTION', value: '@Microsoft.KeyVault(VaultName=${keyVaultName};SecretName=servicebus-connection)' }
        { name: 'SERVICEBUS_FQDN', value: '${serviceBusNamespaceName}.servicebus.windows.net' }
        { name: 'COSMOS_ENDPOINT', value: cosmos.properties.documentEndpoint }
        { name: 'COSMOS_DATABASE_NAME', value: cosmosDb.name }
        { name: 'BOT_STATUS_CONTAINER_NAME', value: botStatus.name }
        { name: 'FILING_COUNTER_CONTAINER_NAME', value: filingCounter.name }
        { name: 'FILER_TOPIC_NAME', value: filerTopicName }
      ]
    }
  }
}
