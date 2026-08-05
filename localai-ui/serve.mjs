import { createReadStream, statSync } from 'node:fs'
import { createServer, request as proxyRequest } from 'node:http'
import { connect } from 'node:net'
import { extname, join, normalize, resolve } from 'node:path'

const host = process.env.UI_HOST || '0.0.0.0'
const port = Number(process.env.UI_PORT || 5199)
const backend = new URL(process.env.LOCALAI_URL || 'http://127.0.0.1:8080')
const root = resolve(new URL('./dist', import.meta.url).pathname)
const proxyPrefixes = [
  '/api', '/v1', '/tts', '/video', '/backend', '/models', '/backends',
  '/swagger', '/static', '/generated-audio', '/generated-images',
  '/generated-videos', '/version', '/system', '/ws',
]
const mime = {
  '.css': 'text/css; charset=utf-8', '.html': 'text/html; charset=utf-8',
  '.ico': 'image/x-icon', '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8', '.map': 'application/json; charset=utf-8',
  '.png': 'image/png', '.svg': 'image/svg+xml', '.webp': 'image/webp',
  '.woff': 'font/woff', '.woff2': 'font/woff2',
}

function isBackendPath(url = '/') {
  const pathname = new URL(url, 'http://localhost').pathname
  return proxyPrefixes.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`))
}

function proxy(req, res) {
  const upstream = proxyRequest({
    hostname: backend.hostname,
    port: backend.port || 80,
    method: req.method,
    path: req.url,
    headers: { ...req.headers, host: backend.host },
  }, (upstreamRes) => {
    res.writeHead(upstreamRes.statusCode || 502, upstreamRes.headers)
    upstreamRes.pipe(res)
  })
  upstream.on('error', (error) => {
    if (!res.headersSent) res.writeHead(502, { 'content-type': 'text/plain; charset=utf-8' })
    res.end(`LocalAI upstream unavailable: ${error.message}`)
  })
  req.pipe(upstream)
}

function serveStatic(req, res) {
  const pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname)
  const candidate = resolve(root, `.${normalize(pathname)}`)
  let file = candidate.startsWith(`${root}/`) ? candidate : join(root, 'index.html')
  try {
    if (!statSync(file).isFile()) file = join(root, 'index.html')
  } catch {
    file = join(root, 'index.html')
  }
  const fingerprintedAsset = pathname.startsWith('/assets/')
  res.writeHead(200, {
    'content-type': mime[extname(file)] || 'application/octet-stream',
    'cache-control': fingerprintedAsset
      ? 'public, max-age=31536000, immutable'
      : 'no-cache',
  })
  createReadStream(file).pipe(res)
}

const server = createServer((req, res) => isBackendPath(req.url) ? proxy(req, res) : serveStatic(req, res))

server.on('upgrade', (req, socket, head) => {
  if (!isBackendPath(req.url)) return socket.destroy()
  const upstream = connect(Number(backend.port || 80), backend.hostname, () => {
    const headers = Object.entries({ ...req.headers, host: backend.host })
      .map(([key, value]) => `${key}: ${value}`).join('\r\n')
    upstream.write(`${req.method} ${req.url} HTTP/${req.httpVersion}\r\n${headers}\r\n\r\n`)
    if (head.length) upstream.write(head)
    socket.pipe(upstream).pipe(socket)
  })
  upstream.on('error', () => socket.destroy())
})

server.listen(port, host, () => console.log(`DaolVision UI listening on http://${host}:${port}; backend=${backend.origin}`))
