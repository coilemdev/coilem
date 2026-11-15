import { createServer, type Server } from 'node:net';

/** Choose distinct free loopback ports once; configured ports are inherited by test workers. */
export async function publicTestPorts(env: NodeJS.ProcessEnv = process.env) {
  const configured = (name: string) => {
    const value = env[name];
    if (!value) return null;
    const port = /^\d+$/.test(value) ? Number(value) : NaN;
    if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error(`${name} must be a port from 1 to 65535.`);
    return port;
  };
  const requestedApi = configured('COILEM_TEST_API_PORT');
  const requestedUi = configured('COILEM_TEST_UI_PORT');
  if (requestedApi !== null && requestedApi === requestedUi) throw new Error('The test API and UI must use different ports.');
  const held: Server[] = [];
  const available = async (excluded: number | null) => {
    let port: number;
    do {
      const server = createServer();
      await new Promise<void>((resolve, reject) => server.once('error', reject).listen(0, '127.0.0.1', resolve));
      held.push(server);
      port = (server.address() as { port: number }).port;
    } while (port === excluded);
    return port;
  };
  try {
    const apiPort = requestedApi ?? await available(requestedUi);
    const uiPort = requestedUi ?? await available(apiPort);
    return { apiPort, uiPort };
  } finally {
    await Promise.all(held.map(server => new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()))));
  }
}
