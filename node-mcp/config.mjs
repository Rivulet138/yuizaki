export function resolveMcpPort(rawPort = process.env.MCP_PORT) {
  const raw = String(rawPort ?? '').trim();
  if (!/^\d+$/.test(raw)) return 7777;
  const requestedPort = Number(raw);
  return Number.isInteger(requestedPort) && requestedPort > 0 && requestedPort <= 65535
    ? requestedPort
    : 7777;
}
