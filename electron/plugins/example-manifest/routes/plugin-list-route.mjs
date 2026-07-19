export async function handle(request) {
  const prompt = typeof request?.query?.prompt === 'string'
    ? request.query.prompt.trim()
    : typeof request?.body?.prompt === 'string'
      ? request.body.prompt.trim()
      : ''

  if (prompt && request?.context?.runAgent) {
    const agent = await request.context.runAgent({
      prompt,
      sessionId: `plugin:${request.context.pluginId}:${request.context.routeId}`,
    })
    return {
      status: 200,
      body: {
        ok: true,
        plugin: 'example-manifest-plugin',
        route: 'plugin-list-route',
        agent,
      },
    }
  }

  return {
    status: 200,
    body: {
      ok: true,
      plugin: 'example-manifest-plugin',
      route: 'plugin-list-route',
      request,
    },
  }
}

export default handle
