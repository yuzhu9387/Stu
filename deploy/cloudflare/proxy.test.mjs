// node --test deploy/cloudflare/proxy.test.mjs
import assert from 'node:assert/strict';
import { afterEach, test } from 'node:test';
import proxy from './proxy.mjs';

const SECRET = 'e'.repeat(48);
const env = { EDGE_PROXY_SECRET: SECRET };
const realFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = realFetch; });

function upstream(respond = () => new Response('ok')) {
  const seen = [];
  globalThis.fetch = async request => { seen.push(request); return respond(request); };
  return seen;
}

test('api paths go to the API with the edge token; caller-supplied proxy headers are dropped', async () => {
  const seen = upstream();
  const request = new Request('https://stu.dodofamily.com/api/v1/kitchen?week=1', {
    method: 'POST', body: '{}',
    headers: { 'CF-Connecting-IP': '203.0.113.9', 'X-Stu-Proxy-Token': 'forged', 'X-Forwarded-For': '10.0.0.1', Cookie: 'recipe_session=abc' },
  });
  await proxy.fetch(request, env);
  const sent = seen[0];
  assert.equal(new URL(sent.url).host, 'stu-api-314788321213.us-west2.run.app');
  assert.equal(new URL(sent.url).search, '?week=1');
  assert.equal(sent.headers.get('X-Stu-Proxy-Token'), SECRET);
  assert.equal(sent.headers.get('X-Stu-Proxy-IP'), '203.0.113.9');
  assert.equal(sent.headers.get('X-Forwarded-For'), null);
  assert.equal(sent.headers.get('Cookie'), 'recipe_session=abc');
  assert.equal(sent.method, 'POST');
});

test('pages go to the web app, which never sees the edge token', async () => {
  const seen = upstream();
  await proxy.fetch(new Request('https://stu.dodofamily.com/calendar', { headers: { 'X-Stu-Proxy-Token': 'forged' } }), env);
  assert.equal(new URL(seen[0].url).host, 'stu-web-314788321213.us-west2.run.app');
  assert.equal(seen[0].headers.get('X-Stu-Proxy-Token'), null);
});

test('http redirects to https, other hosts are refused, a missing secret closes the API', async () => {
  upstream();
  const insecure = await proxy.fetch(new Request('http://stu.dodofamily.com/plan'), env);
  assert.equal(insecure.status, 308);
  assert.equal(insecure.headers.get('Location'), 'https://stu.dodofamily.com/plan');
  assert.equal((await proxy.fetch(new Request('https://evil.example/api/v1'), env)).status, 404);
  assert.equal((await proxy.fetch(new Request('https://stu.dodofamily.com/api/v1/x'), {})).status, 503);
});

test('a redirect naming a Cloud Run host is sent back to the public host', async () => {
  upstream(() => new Response(null, { status: 307, headers: { Location: 'https://stu-web-314788321213.us-west2.run.app/calendar' } }));
  const response = await proxy.fetch(new Request('https://stu.dodofamily.com/'), env);
  assert.equal(response.headers.get('Location'), 'https://stu.dodofamily.com/calendar');
});
