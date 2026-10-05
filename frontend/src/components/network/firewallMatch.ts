import { FirewallAllowedPort, NetworkOverview } from '../../types/system';

export type FirewallVerdict =
  | { kind: 'allowed'; detail?: string }
  | { kind: 'blocked' }
  | { kind: 'local' }
  | { kind: 'unknown' };

// ss local address -> host and port: 0.0.0.0:22, [::]:22, *:22, 127.0.0.53%lo:53, [fe80::1%eth0]:546
const splitAddress = (addr: string): { host: string; port: number } => {
  const i = addr.lastIndexOf(':');
  const host = addr.slice(0, i).replace(/^\[|\]$/g, '').replace(/%.*$/, '');
  return { host, port: Number(addr.slice(i + 1)) };
};

const isLoopback = (host: string) =>
  host.startsWith('127.') || host === '::1' || host === 'localhost' || host.startsWith('::ffff:127.');

export const allowedPortLabel = (p: FirewallAllowedPort) => {
  const ports = p.end_port !== p.port ? `${p.port}-${p.end_port}` : `${p.port}`;
  return p.protocol === 'any' ? ports : `${ports}/${p.protocol}`;
};

/** Whether the firewall lets outside traffic reach a listening socket. */
export const firewallVerdict = (
  socket: { proto: string; local_address: string },
  firewall: NetworkOverview['firewall'] | undefined,
): FirewallVerdict => {
  const { host, port } = splitAddress(socket.local_address);
  if (isLoopback(host)) return { kind: 'local' };
  if (!firewall?.active) return { kind: 'unknown' };
  if (firewall.allow_all) return { kind: 'allowed', detail: 'default policy' };
  if (!firewall.allowed_ports) return { kind: 'unknown' };

  const proto = socket.proto.toLowerCase().startsWith('udp') ? 'udp' : 'tcp';
  const matches = firewall.allowed_ports.filter(
    (p) => (p.protocol === 'any' || p.protocol === proto) && port >= p.port && port <= p.end_port,
  );
  if (!matches.length) return { kind: 'blocked' };
  // Prefer a rule open to everyone over a source-restricted one
  const best = matches.find((p) => !p.source) ?? matches[0];
  const detail = [best.name, best.source && `from ${best.source}`].filter(Boolean).join(', ');
  return { kind: 'allowed', detail: detail || undefined };
};
