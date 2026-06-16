@description('AKS cluster name.')
param aksName string

@description('Azure Container Registry name. Leave empty to skip AcrPull assignment.')
param acrName string = ''

var hasAcr = !empty(acrName)
var kubeletIdentityObjectId = aks.properties.identityProfile.kubeletidentity.objectId

resource aks 'Microsoft.ContainerService/managedClusters@2024-10-01' existing = {
  name: aksName
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = if (hasAcr) {
  name: acrName
}

resource acrPullRoleDefinition 'Microsoft.Authorization/roleDefinitions@2022-04-01' existing = {
  scope: subscription()
  name: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
}

resource aksAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (hasAcr) {
  name: guid(aks.id, acr!.id, acrPullRoleDefinition.id)
  scope: acr!
  properties: {
    principalId: kubeletIdentityObjectId
    principalType: 'ServicePrincipal'
    roleDefinitionId: acrPullRoleDefinition.id
  }
}

output acrPullRoleAssignmentName string = hasAcr ? aksAcrPull.name : ''
