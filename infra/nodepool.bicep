@description('AKS cluster name.')
param aksName string

@description('Node pool name.')
param nodePoolName string

@description('Azure Linux node VM size.')
param nodeVmSize string = 'Standard_D4s_v3'

@minValue(1)
@description('Node count for the user node pool.')
param nodeCount int = 1

@allowed([
  'kata'
  'gvisor'
  'firecracker'
])
@description('Runtime experiment hosted by this node pool.')
param runtimeExperiment string

@allowed([
  'KataMshvVmIsolation'
])
@description('AKS pod sandboxing workload runtime for the Kata node pool.')
param workloadRuntime string = 'KataMshvVmIsolation'

var nodeTaint = runtimeExperiment == 'kata' ? 'kata=true:NoSchedule' : runtimeExperiment == 'gvisor' ? 'gvisor=true:NoSchedule' : 'firecracker=true:NoSchedule'
var runtimeProperties = runtimeExperiment == 'kata' ? {
  workloadRuntime: workloadRuntime
} : {}

resource aks 'Microsoft.ContainerService/managedClusters@2024-10-01' existing = {
  name: aksName
}

resource nodePool 'Microsoft.ContainerService/managedClusters/agentPools@2024-10-01' = {
  parent: aks
  name: nodePoolName
  properties: union({
    mode: 'User'
    count: nodeCount
    vmSize: nodeVmSize
    osType: 'Linux'
    osSKU: 'AzureLinux'
    type: 'VirtualMachineScaleSets'
    enableAutoScaling: false
    nodeTaints: [
      nodeTaint
    ]
    nodeLabels: {
      'runtime-experiment': runtimeExperiment
    }
  }, runtimeProperties)
}

output nodePoolName string = nodePool.name
