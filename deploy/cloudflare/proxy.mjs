// stu.dodofamily.com → Cloud Run. /api/ goes to the API service, everything
// else to the web app. The API admits only requests carrying the edge token,
// so nothing reaches it except through this Worker.
const PUBLIC_HOST = 'stu.dodofamily.com';
const API_HOST = 'stu-api-314788321213.us-west2.run.app';
const WEB_HOST = 'stu-web-314788321213.us-west2.run.app';
const PROXY_HEADERS = ['Forwarded', 'X-Forwarded-For', 'X-Forwarded-Host', 'X-Real-IP', 'True-Client-IP', 'X-Stu-Proxy-IP', 'X-Stu-Proxy-Token'];

const unavailable = (message, status) => new Response(message, { status, headers: { 'Cache-Control': 'no-store', 'Content-Type': 'text/plain; charset=utf-8' } });

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.hostname !== PUBLIC_HOST) return unavailable('Not found', 404);
    if (url.protocol === 'http:') {
      url.protocol = 'https:';
      return Response.redirect(url.href, 308);
    }
    const api = url.pathname === '/api' || url.pathname.startsWith('/api/');
    const secret = env?.EDGE_PROXY_SECRET;
    if (api && (typeof secret !== 'string' || secret.length < 32)) return unavailable('Service temporarily unavailable', 503);

    // Set the destination directly; a path can never select another origin.
    const upstream = api ? API_HOST : WEB_HOST;
    url.hostname = upstream;
    url.protocol = 'https:';
    url.port = '';
    const headers = new Headers(request.headers);
    for (const name of PROXY_HEADERS) headers.delete(name);
    headers.set('Host', upstream);
    const clientIp = request.headers.get('CF-Connecting-IP');
    if (clientIp) headers.set('X-Stu-Proxy-IP', clientIp);
    if (api) headers.set('X-Stu-Proxy-Token', secret);
    // Keep method, body, cookies and redirects as the app sent them.
    const forwarded = new Request(new Request(url.href, request), { headers, redirect: 'manual' });
    let response;
    try { response = await fetch(forwarded, { cache: 'no-store' }); }
    catch { return unavailable('Service temporarily unavailable', 502); }
    // A redirect that names a Cloud Run host is sent back to the public one.
    const location = response.headers.get('Location');
    if (location) {
      const target = new URL(location, url.href);
      if (target.hostname === API_HOST || target.hostname === WEB_HOST) {
        target.hostname = PUBLIC_HOST;
        const rewritten = new Response(response.body, response);
        rewritten.headers.set('Location', target.href);
        return rewritten;
      }
    }
    return response;
  },
};
