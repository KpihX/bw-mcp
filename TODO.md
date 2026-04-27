# TODO: BW-Proxy 🛡️

## Appliance Roadmap
- [ ] **Sovereign Dashboard**: A full React/Vite web interface (hosted inside the container) for real-time vault monitoring and proxy management.
- [ ] **Hardware Key Support**: Integrate YubiKey (FIDO2/U2F) passthrough for hardware-backed vault unlocking.
- [ ] **OIDC Bridge**: Allow the proxy to act as an OIDC provider for other self-hosted services using Bitwarden as the backend.

## Security Hardening
- [ ] **Cosign Signing**: Sign the Docker images in GHCR to ensure supply chain integrity.
- [ ] **Network Egress Firewall**: Implement strict eBPF or iptables rules inside the container to block all non-Bitwarden traffic.

## Developer Experience
- [ ] **Plugin System**: Allow custom Python "Logic Plugins" to be mounted into `/app/plugins` for domain-specific refactoring rules.
