@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('AKS cluster name.')
param aksName string

@description('Globally unique Azure Container Registry name.')
param acrName string

@description('Azure Linux node VM size for AKS Pod Sandboxing. Standard_D4s_v3 is Gen2 and supports nested virtualization.')
param nodeVmSize string = 'Standard_D4s_v3'

@minValue(1)
@description('Number of nodes in the Kata-enabled node pool.')
param nodeCount int = 3

@description('Optional Kubernetes version. Leave empty to use the AKS default for the region.')
param kubernetesVersion string = ''

@allowed([
  'KataMshvVmIsolation'
])
@description('AKS pod sandboxing workload runtime. Newer AKS API versions require KataMshvVmIsolation.')
param workloadRuntime string = 'KataMshvVmIsolation'

@description('Create an AcrPull role assignment for the AKS kubelet identity. Requires Microsoft.Authorization/roleAssignments/write.')
param assignAcrPullRole bool = true

@description('Enable ACR admin credentials. Intended for examples when role assignment permissions are unavailable.')
param acrAdminUserEnabled bool = false

@description('Tags applied to all resources.')
param tags object = {
  workload: 'opensandbox-kata-example'
}

var aksBaseProperties = {
  dnsPrefix: aksName
  enableRBAC: true
  oidcIssuerProfile: {
    enabled: true
  }
  securityProfile: {
    workloadIdentity: {
      enabled: true
    }
  }
  networkProfile: {
    networkPlugin: 'azure'
    networkPluginMode: 'overlay'
    loadBalancerSku: 'standard'
    outboundType: 'loadBalancer'
  }
  agentPoolProfiles: [
    {
      name: 'katapool'
      mode: 'System'
      count: nodeCount
      vmSize: nodeVmSize
      osType: 'Linux'
      osSKU: 'AzureLinux'
      type: 'VirtualMachineScaleSets'
      workloadRuntime: workloadRuntime
      enableAutoScaling: false
    }
  ]
}

var aksVersionProperties = empty(kubernetesVersion) ? {} : {
  kubernetesVersion: kubernetesVersion
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: acrAdminUserEnabled
    publicNetworkAccess: 'Enabled'
  }
}

resource aks 'Microsoft.ContainerService/managedClusters@2024-10-01' = {
  name: aksName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: union(aksBaseProperties, aksVersionProperties)
}

resource acrPullRoleDefinition 'Microsoft.Authorization/roleDefinitions@2022-04-01' existing = {
  scope: subscription()
  name: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
}

resource aksAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (assignAcrPullRole) {
  name: guid(aks.id, acr.id, acrPullRoleDefinition.id)
  scope: acr
  properties: {
    principalId: aks.properties.identityProfile.kubeletidentity.objectId
    principalType: 'ServicePrincipal'
    roleDefinitionId: acrPullRoleDefinition.id
  }
}

output aksName string = aks.name
output acrLoginServer string = acr.properties.loginServer
output kataRuntimeClass string = 'kata-vm-isolation'
output recommendedSku string = nodeVmSize
output confidentialContainerSku string = 'Standard_DC8as_cc_v5'
output acrAdminUserEnabled bool = acrAdminUserEnabled
output workloadRuntime string = workloadRuntime
