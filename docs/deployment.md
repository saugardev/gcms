# Jio deployment

[Documentation](README.md) · [Project](../README.md)

Pushing `main` or manually running **Deploy GCMS** in GitHub Actions deploys the
exact commit to the dedicated Jio VM. The workflow builds a new release, tests
it, switches a `current` symlink, restarts systemd and
restores the previous release if local health checks fail. The action summary
and production environment contain the allocated HTTPS link even when deployment
checks fail; the summary reports their status separately. Both Python and Rust
sample reviews are checked.

The VM uses the **gcms** Jio account, Large size (4 vCPU, 8 GiB). GitHub needs
secrets `JIO_API_KEY` and `JIO_SSH_KEY`, plus variable `JIO_VM_ID`. The SSH secret
is the VM's generated `id_ed25519` private key; GitHub recreates its local Jio
session state per run. Optional `JIO_ENDPOINT` selects a different Jio endpoint.
Credentials belong in GitHub secrets and private local state, never this repository.

For a new VM, authenticate to the gcms account in an isolated `JIO_STATE_DIR`,
select Large with `jio config`, and run `jio create`. Provision these external
inputs over the VM's authenticated SSH connection before the first deployment:

```text
/var/lib/gcms/data/library.msp
/var/lib/gcms/data/sample.D/data.ms
```

The sample directory may contain its other acquisition files. Neither input is
downloaded from Git or stored in Actions artifacts. Deployments preserve this
directory, restrict its permissions, and run the API as the `gcms` service user.
The configured sample is available to visitors through the public dashboard.

The runtime pins uv 0.11.6, Python 3.12.13 and Rust 1.94.0. Each release has an
editable Python environment and its own native library. Download/build caches
are shared; application tests run against the external inputs before activation.
The API runs one worker with one numerical thread and rejects concurrent analyses
with a retryable `503`. Jio publishes port 8000 with HTTPS; no nginx is required.
This is a public demo without user authentication. Uploaded files are temporary.

Useful operations (with the deployment account and VM session configured):

```sh
jio ports "$JIO_VM_ID"
jio exec "$JIO_VM_ID" 'sudo -n systemctl status gcms --no-pager'
jio exec "$JIO_VM_ID" 'sudo -n journalctl -u gcms -n 80 --no-pager'
GIT_REF=$(git rev-parse HEAD) bash deploy/jio.sh
```

Releases remain in `/var/lib/gcms/releases` for rollback. The installed revision
is recorded in `/var/lib/gcms/deployed-revision`. No database migration is needed.
