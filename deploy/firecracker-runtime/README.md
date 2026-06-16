# Firecracker runtime on AKS

This example installs a Firecracker-backed Kubernetes `RuntimeClass` named
`kata-fc` on a dedicated AKS user node pool.

This is not a supported AKS feature. It mutates managed node host files,
configures a loopback devmapper thinpool, modifies containerd configuration, and
restarts `containerd`. Node image upgrades, scale-out, or reimage operations can
remove these changes. Use this only for disposable experiments or isolated test
node pools.

## Requirements

- A dedicated user node pool whose nodes expose `/dev/kvm`.
- The node pool must be tainted with `firecracker=true:NoSchedule`.
- `kube-proxy` must be healthy on the Firecracker node pool before installing.

Create the node pool through Bicep with:

```bash
make firecracker-nodepool-add
```

## Install

Run from the repository root after `make aks-credentials`:

```bash
make firecracker-install
make firecracker-example
```

The installer:

- installs Kata Deploy with only the `fc` shim enabled
- creates `RuntimeClass/kata-fc`
- configures a loopback devmapper thinpool on each Firecracker node
- enables the containerd devmapper snapshotter
- enables containerd local image pulls for the CRI plugin
- pins the containerd sandbox image to the linux/amd64 pause manifest digest
- pre-pulls the pause and example images with devmapper

## Use with OpenSandbox

Configure the OpenSandbox server with:

```toml
[secure_runtime]
type = "firecracker"
k8s_runtime_class = "kata-fc"
```

OpenSandbox-created Kubernetes sandboxes should then use:

```yaml
runtimeClassName: kata-fc
```

## Rollback

Remove Kubernetes resources:

```bash
make firecracker-clean
```

To fully undo host changes, restore the containerd backups on each node and
restart `containerd`, or reimage/delete the Firecracker node pool:

```bash
az aks nodepool delete \
  --resource-group "$RESOURCE_GROUP" \
  --cluster-name "$AKS_NAME" \
  --name "$FIRECRACKER_NODEPOOL_NAME"
```

Host config backups use these patterns:

```text
/etc/containerd/config.toml.opensandbox-devmapper.<timestamp>.bak
/etc/containerd/config.toml.opensandbox-local-pull.<timestamp>.bak
/etc/containerd/config.toml.opensandbox-pause-digest.<timestamp>.bak
```
