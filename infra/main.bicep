@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('AKS cluster name.')
param aksName string

@description('Globally unique Azure Container Registry name. Leave empty to skip ACR for Helm-only deployments that use public images.')
param acrName string = ''

@description('Azure Linux node VM size used by the system pool and all runtime test pools. Standard_D4s_v3 is Gen2 and supports nested virtualization.')
param nodeVmSize string = 'Standard_D4s_v3'

@minValue(1)
@description('Number of nodes in the Kata-enabled user node pool.')
param kataNodeCount int = 3

@minValue(1)
@description('Number of nodes in the non-Kata system node pool.')
param systemNodeCount int = 1

@description('Optional Kubernetes version. Leave empty to use the AKS default for the region.')
param kubernetesVersion string = ''

@allowed([
  'KataMshvVmIsolation'
])
@description('AKS pod sandboxing workload runtime. Newer AKS API versions require KataMshvVmIsolation.')
param workloadRuntime string = 'KataMshvVmIsolation'

@description('Kata experiment node pool name.')
param kataNodePoolName string = 'katauser'

@description('Create an AcrPull role assignment for the AKS kubelet/nodepool managed identity. Requires Microsoft.Authorization/roleAssignments/write.')
param assignAcrPullRole bool = true

@description('Enable ACR admin credentials. Intended for examples when role assignment permissions are unavailable.')
param acrAdminUserEnabled bool = false

@description('Create an additional tainted user node pool for experimental Firecracker runtime work.')
param enableFirecrackerNodePool bool = false

@description('Create an additional tainted user node pool for experimental gVisor runtime work.')
param enableGvisorNodePool bool = false

@description('Firecracker experiment node pool name.')
param firecrackerNodePoolName string = 'fcpool'

@description('gVisor experiment node pool name.')
param gvisorNodePoolName string = 'gvisorpool'

@minValue(1)
@description('Node count for the Firecracker experiment node pool.')
param firecrackerNodeCount int = 1

@minValue(1)
@description('Node count for the gVisor experiment node pool.')
param gvisorNodeCount int = 1

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
      name: 'systempool'
      mode: 'System'
      count: systemNodeCount
      vmSize: nodeVmSize
      osType: 'Linux'
      osSKU: 'AzureLinux'
      type: 'VirtualMachineScaleSets'
      enableAutoScaling: false
    }
  ]
}

var aksVersionProperties = empty(kubernetesVersion) ? {} : {
  kubernetesVersion: kubernetesVersion
}

var hasAcr = !empty(acrName)
var kubeletIdentityObjectId = aks.properties.identityProfile.kubeletidentity.objectId

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = if (hasAcr) {
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

resource kataPool 'Microsoft.ContainerService/managedClusters/agentPools@2024-10-01' = {
  parent: aks
  name: kataNodePoolName
  properties: {
    mode: 'User'
    count: kataNodeCount
    vmSize: nodeVmSize
    osType: 'Linux'
    osSKU: 'AzureLinux'
    type: 'VirtualMachineScaleSets'
    workloadRuntime: workloadRuntime
    enableAutoScaling: false
    nodeTaints: [
      'kata=true:NoSchedule'
    ]
    nodeLabels: {
      'runtime-experiment': 'kata'
    }
  }
}

resource firecrackerPool 'Microsoft.ContainerService/managedClusters/agentPools@2024-10-01' = if (enableFirecrackerNodePool) {
  parent: aks
  name: firecrackerNodePoolName
  properties: {
    mode: 'User'
    count: firecrackerNodeCount
    vmSize: nodeVmSize
    osType: 'Linux'
    osSKU: 'AzureLinux'
    type: 'VirtualMachineScaleSets'
    enableAutoScaling: false
    nodeTaints: [
      'firecracker=true:NoSchedule'
    ]
    nodeLabels: {
      'runtime-experiment': 'firecracker'
    }
  }
}

resource gvisorPool 'Microsoft.ContainerService/managedClusters/agentPools@2024-10-01' = if (enableGvisorNodePool) {
  parent: aks
  name: gvisorNodePoolName
  properties: {
    mode: 'User'
    count: gvisorNodeCount
    vmSize: nodeVmSize
    osType: 'Linux'
    osSKU: 'AzureLinux'
    type: 'VirtualMachineScaleSets'
    enableAutoScaling: false
    nodeTaints: [
      'gvisor=true:NoSchedule'
    ]
    nodeLabels: {
      'runtime-experiment': 'gvisor'
    }
  }
}

resource acrPullRoleDefinition 'Microsoft.Authorization/roleDefinitions@2022-04-01' existing = {
  scope: subscription()
  name: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
}

resource aksAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (assignAcrPullRole && hasAcr) {
  name: guid(aks.id, acr.id, acrPullRoleDefinition.id)
  scope: acr
  properties: {
    principalId: kubeletIdentityObjectId
    principalType: 'ServicePrincipal'
    roleDefinitionId: acrPullRoleDefinition.id
  }
}

output aksName string = aks.name
output acrLoginServer string = hasAcr ? acr!.properties.loginServer : ''
output kataRuntimeClass string = 'kata-vm-isolation'
output kataNodePoolName string = kataPool.name
output recommendedSku string = nodeVmSize
output confidentialContainerSku string = 'Standard_DC8as_cc_v5'
output acrAdminUserEnabled bool = hasAcr ? acrAdminUserEnabled : false
output workloadRuntime string = workloadRuntime
output firecrackerNodePoolName string = enableFirecrackerNodePool ? firecrackerPool.name : ''
output gvisorNodePoolName string = enableGvisorNodePool ? gvisorPool.name : ''
