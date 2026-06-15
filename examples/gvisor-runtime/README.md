# gVisor runtime on AKS

This example installs the gVisor `runsc` runtime handler on AKS nodes and creates a
Kubernetes `RuntimeClass` named `gvisor`.

This is not a supported AKS feature. It mutates managed node host files and restarts
`containerd`. Node image upgrades, scale-out, or reimage operations can remove these
changes. Use this only for disposable experiments or isolated test node pools.

## Install

Run from the repository root after `make aks-credentials`:

```bash
make gvisor-install
make gvisor-smoke-test
```

The installer:

- downloads `runsc` and `containerd-shim-runsc-v1` from the latest gVisor release
- verifies the SHA-512 checksums
- installs the binaries to `/usr/local/bin` on each node
- appends the `runsc` containerd runtime handler if missing
- writes `/etc/containerd/runsc.toml`
- restarts `containerd`

The installer writes a backup before changing containerd config:

```text
/etc/containerd/config.toml.opensandbox-gvisor.<timestamp>.bak
```

## Use with OpenSandbox

Configure the OpenSandbox server with:

```toml
[secure_runtime]
type = "gvisor"
k8s_runtime_class = "gvisor"
```

OpenSandbox-created Kubernetes sandboxes should then use:

```yaml
runtimeClassName: gvisor
```

## Rollback

Restore the backup on each node and restart `containerd`, then remove the RuntimeClass:

```bash
sudo cp /etc/containerd/config.toml.opensandbox-gvisor.<timestamp>.bak /etc/containerd/config.toml
sudo systemctl restart containerd
kubectl delete runtimeclass gvisor
```

For a clean AKS-supported state, reimage the affected node pool.
