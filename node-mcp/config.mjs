export function resolveMcpPort(rawPort = process.env.MCP_PORT) {
  const requestedPort = Number.parseInt(String(rawPort || '').trim(), 10);
  return Number.isInteger(requestedPort) && requestedPort > 0 && requestedPort <= 65535
    ? requestedPort
    : 7777;
}
