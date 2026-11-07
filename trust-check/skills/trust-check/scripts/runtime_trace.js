#!/usr/bin/env node
// Runtime trace for a trust check: loads pages in headless Chromium, records every request,
// storage write and sensitive browser-API call, and aborts analytics collection requests
// after recording them, so the trace never writes into the site owner's statistics.
//
// Usage:
//   node runtime_trace.js --out DIR [--idle 30] [--mobile] [--abort REGEX] URL [URL ...]
// Needs the playwright or playwright-core package and a Chromium build. Set TC_CHROME to a
// Chromium executable when Playwright's own browser is not installed.
'use strict';
const fs = require('fs');
const path = require('path');

const MAX_LOADS = 8; // a trace is a sample, not a crawl
const ANALYTICS = [
  'gateway\\.umami\\.is', 'cloudflareinsights\\.com', 'google-analytics\\.com',
  'analytics\\.google\\.com', 'googletagmanager\\.com/.*collect', 'stats\\.g\\.doubleclick\\.net',
  'plausible\\.io/api', 'api\\.segment\\.io', 'api-js\\.mixpanel\\.com', 'in\\.hotjar\\.com',
  'clarity\\.ms/collect', 'px\\.ads\\.linkedin\\.com', 'facebook\\.com/tr', 'posthog\\.com/[ei]/',
].join('|');
const IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 ' +
  '(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1';

function loadPlaywright() {
  for (const name of ['playwright', 'playwright-core']) {
    try { return require(name).chromium; } catch (e) { /* try the next one */ }
  }
  console.error('runtime_trace: install playwright-core (npm i playwright-core) next to this ' +
    'script or on NODE_PATH, then retry.');
  process.exit(3);
}

function findChrome() {
  if (process.env.TC_CHROME) return process.env.TC_CHROME;
  const root = path.join(process.env.HOME || '', '.cache', 'ms-playwright');
  if (!fs.existsSync(root)) return undefined;
  const builds = fs.readdirSync(root).filter(d => /^chromium-\d+$/.test(d))
    .sort((a, b) => Number(b.split('-')[1]) - Number(a.split('-')[1]));
  for (const b of builds) {
    for (const rel of ['chrome-linux64/chrome', 'chrome-linux/chrome',
      'chrome-mac/Chromium.app/Contents/MacOS/Chromium', 'chrome-win/chrome.exe']) {
      const p = path.join(root, b, rel);
      if (fs.existsSync(p)) return p;
    }
  }
  return undefined;
}

// Wraps sensitive APIs before any page script runs and logs each call with its caller.
const INIT = `(() => {
  const L = window.__tcLog = [];
  const caller = () => { try { throw new Error(); } catch (e) {
    return (e.stack || '').split('\\n').slice(3, 5).map(s => s.trim()).join(' | '); } };
  const log = (api, info) => L.push({ api, info: String(info || '').slice(0, 200), at: caller() });
  const S = window.__tcWrap = {};
  const wrap = (obj, name, label) => { try { const o = obj && obj[name];
    if (typeof o !== 'function') return (S[label] = 'absent');
    obj[name] = function (...a) { log(label, a.map(x => typeof x === 'string' ? x : typeof x)
      .join(',')); return o.apply(this, a); }; S[label] = 'ok'; } catch (e) { S[label] = 'err'; } };
  const getter = (proto, prop, label) => { try {
    const d = Object.getOwnPropertyDescriptor(proto, prop);
    if (!d || !d.get) return (S[label] = 'absent');
    Object.defineProperty(proto, prop, { ...d, get() { log(label); return d.get.call(this); } });
    S[label] = 'ok'; } catch (e) { S[label] = 'err'; } };
  wrap(HTMLCanvasElement.prototype, 'toDataURL', 'canvas.toDataURL');
  wrap(HTMLCanvasElement.prototype, 'toBlob', 'canvas.toBlob');
  wrap(CanvasRenderingContext2D.prototype, 'getImageData', 'canvas.getImageData');
  wrap(WebGLRenderingContext.prototype, 'getParameter', 'webgl.getParameter');
  if (window.WebGL2RenderingContext) {
    wrap(WebGL2RenderingContext.prototype, 'getParameter', 'webgl2.getParameter');
  }
  for (const c of ['AudioContext', 'OfflineAudioContext', 'RTCPeerConnection', 'WebSocket',
    'EventSource', 'Worker', 'SharedWorker']) { try { const O = window[c];
    if (!O) { S['new ' + c] = 'absent'; continue; }
    window[c] = new Proxy(O, { construct(t, a, n) {
      log('new ' + c, a[0]); return Reflect.construct(t, a, n); } });
    S['new ' + c] = 'ok'; } catch (e) { S['new ' + c] = 'err'; } }
  for (const p of ['plugins', 'mimeTypes', 'hardwareConcurrency', 'deviceMemory', 'userAgentData',
    'languages', 'platform', 'webdriver', 'clipboard', 'geolocation', 'mediaDevices', 'connection'])
    getter(Navigator.prototype, p, 'navigator.' + p);
  wrap(Navigator.prototype, 'getBattery', 'navigator.getBattery');
  wrap(Navigator.prototype, 'sendBeacon', 'navigator.sendBeacon');
  wrap(window, 'fetch', 'fetch');
  wrap(XMLHttpRequest.prototype, 'open', 'xhr.open');
  try { const d = Object.getOwnPropertyDescriptor(Document.prototype, 'cookie');
    Object.defineProperty(Document.prototype, 'cookie', { ...d,
      set(v) { log('document.cookie=', v); return d.set.call(this, v); },
      get() { log('document.cookie (read)'); return d.get.call(this); } });
    S['document.cookie'] = 'ok';
  } catch (e) { S['document.cookie'] = 'err'; }
  wrap(Storage.prototype, 'setItem', 'Storage.setItem');
  wrap(Storage.prototype, 'getItem', 'Storage.getItem');
  wrap(window, 'open', 'window.open');
  if (window.Notification) {
    wrap(Notification, 'requestPermission', 'Notification.requestPermission');
  }
  wrap(window, 'eval', 'eval');
  try { const F = Function; window.Function = new Proxy(F, {
    construct(t, a, n) { log('new Function', a.join(';')); return Reflect.construct(t, a, n); },
    apply(t, th, a) { log('Function()', a.join(';')); return Reflect.apply(t, th, a); } });
    S.Function = 'ok'; } catch (e) { S.Function = 'err'; }
  const ce = Document.prototype.createElement;
  Document.prototype.createElement = function (t, ...r) {
    if (/^(script|iframe|img|link|object|embed)$/i.test(t)) log('createElement', t);
    return ce.call(this, t, ...r); }; S.createElement = 'ok';
  const ael = EventTarget.prototype.addEventListener;
  const WATCH = new RegExp('^(keydown|keyup|keypress|input|change|mousemove|pointermove|copy|' +
    'paste|cut|beforeunload|visibilitychange|click|submit|devicemotion|deviceorientation)$');
  EventTarget.prototype.addEventListener = function (t, ...r) {
    if (WATCH.test(t)) log('addEventListener', t + ' on ' + (this === document ? 'document'
      : this === window ? 'window' : (this.nodeName || this.constructor.name)));
    return ael.call(this, t, ...r); }; S.addEventListener = 'ok';
  wrap(Location.prototype, 'assign', 'location.assign');
  wrap(Location.prototype, 'replace', 'location.replace');
  S['location.href='] = 'not wrappable in Chromium';
  document.addEventListener('securitypolicyviolation', e =>
    (window.__tcCsp = window.__tcCsp || []).push(e.violatedDirective + ' ' + e.blockedURI), true);
})();`;

function parseArgs(argv) {
  const a = { out: null, idle: 30, mobile: false, abort: ANALYTICS, urls: [] };
  for (let i = 0; i < argv.length; i++) {
    const v = argv[i];
    if (v === '--out') a.out = argv[++i];
    else if (v === '--idle') a.idle = Number(argv[++i]);
    else if (v === '--mobile') a.mobile = true;
    else if (v === '--abort') a.abort = argv[++i];
    else if (/^https?:\/\//.test(v)) a.urls.push(v);
    else { console.error('runtime_trace: unknown argument ' + v); process.exit(2); }
  }
  if (!a.out || !a.urls.length) {
    console.error('usage: runtime_trace.js --out DIR [--idle 30] [--mobile] ' +
      '[--abort REGEX] URL...');
    process.exit(2);
  }
  if (a.urls.length * (a.mobile ? 2 : 1) > MAX_LOADS) {
    console.error(`runtime_trace: at most ${MAX_LOADS} page loads per run`); process.exit(2);
  }
  return a;
}

async function visit(chromium, exe, url, mobile, abortRe, idle) {
  const host = new URL(url).host;
  const out = { url, mobile, requests: [], aborted: [], failed: [], console: [], errors: [],
    dialogs: [], popups: [], downloads: [] };
  const browser = await chromium.launch({ executablePath: exe, args: ['--no-sandbox'] });
  const ctx = await browser.newContext(mobile
    ? { userAgent: IPHONE, viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true }
    : { viewport: { width: 1366, height: 768 } });
  await ctx.addInitScript(INIT);
  const t0 = Date.now();
  await ctx.route('**/*', r => {
    const q = r.request();
    if (abortRe.test(q.url())) {
      out.aborted.push({ t: Date.now() - t0, url: q.url(), method: q.method(),
        type: q.resourceType(), body: (q.postData() || '').slice(0, 4000) });
      return r.abort();
    }
    return r.continue();
  });
  const page = await ctx.newPage();
  page.on('request', q => out.requests.push({ t: Date.now() - t0, url: q.url(), method: q.method(),
    type: q.resourceType(), thirdParty: new URL(q.url()).host !== host,
    body: q.method() === 'POST' ? (q.postData() || '').slice(0, 4000) : undefined }));
  page.on('requestfailed', q => out.failed.push({ url: q.url(), error: q.failure()?.errorText }));
  page.on('console', m => out.console.push(m.type() + ': ' + m.text().slice(0, 300)));
  page.on('pageerror', e => out.errors.push(String(e).slice(0, 300)));
  page.on('dialog', d => { out.dialogs.push(d.type() + ': ' + d.message()); d.dismiss(); });
  page.on('popup', p => out.popups.push(p.url()));
  page.on('download', d => out.downloads.push(d.url()));
  const resp = await page.goto(url, { waitUntil: 'load', timeout: 45000 });
  out.status = resp ? resp.status() : null;
  await page.waitForTimeout(3000);
  out.requestsAfterLoad = out.requests.length;
  const storage = async () => ({
    cookies: await ctx.cookies(),
    ...(await page.evaluate(async () => ({
      localStorage: { ...localStorage }, sessionStorage: { ...sessionStorage },
      indexedDB: indexedDB.databases ? (await indexedDB.databases()).map(d => d.name) : 'n/a',
      caches: await caches.keys().catch(() => []),
      serviceWorkers: navigator.serviceWorker
        ? (await navigator.serviceWorker.getRegistrations()).map(r => r.scope) : [],
    }))),
  });
  out.storageAfterLoad = await storage();
  if (idle > 0 && !mobile) {
    await page.waitForTimeout(idle * 1000);
    out.requestsAfterIdle = out.requests.length;
    await page.mouse.move(100, 100); await page.mouse.move(400, 300, { steps: 10 });
    for (let i = 0; i < 4; i++) { await page.mouse.wheel(0, 400); await page.waitForTimeout(300); }
    await page.keyboard.press('Tab'); await page.keyboard.press('a');
    for (const a of await page.$$('a')) { try { await a.hover({ timeout: 1500 }); } catch (e) {} }
    await page.waitForTimeout(5000);
    out.requestsAfterInteraction = out.requests.length;
    out.storageAfterInteraction = await storage();
  }
  // Playwright's own page.evaluate runs through eval; drop those so only page code remains.
  out.apiCalls = (await page.evaluate(() => window.__tcLog))
    .filter(c => !/UtilityScript\.evaluate/.test(c.at));
  out.wrapStatus = await page.evaluate(() => window.__tcWrap);
  out.cspViolations = await page.evaluate(() => window.__tcCsp || []);
  out.scripts = await page.evaluate(() => [...document.scripts].map(s => ({ src: s.src,
    inlineChars: s.src ? 0 : s.textContent.length, integrity: s.integrity || null })));
  out.finalUrl = page.url();
  await browser.close();
  return out;
}

(async () => {
  const a = parseArgs(process.argv.slice(2));
  const chromium = loadPlaywright();
  const exe = findChrome();
  fs.mkdirSync(a.out, { recursive: true });
  const abortRe = new RegExp(a.abort);
  const runs = [];
  for (const url of a.urls) {
    runs.push(await visit(chromium, exe, url, false, abortRe, a.idle));
    if (a.mobile) runs.push(await visit(chromium, exe, url, true, abortRe, 0));
  }
  const file = path.join(a.out, 'runtime.json');
  fs.writeFileSync(file, JSON.stringify({ tool: 'trust-check runtime_trace.js', runs }, null, 1));
  for (const r of runs) {
    const third = [...new Set(r.requests.filter(q => q.thirdParty).map(q => new URL(q.url).host))];
    console.log(`${r.mobile ? 'mobile ' : 'desktop'} ${r.url}: ${r.requests.length} requests, ` +
      `third-party ${third.join(', ') || 'none'}, aborted ${r.aborted.length}, ` +
      `cookies ${r.storageAfterLoad.cookies.length}, api calls ${r.apiCalls.length}`);
  }
  console.log('trace ->', file);
})().catch(e => { console.error('runtime_trace:', e.message); process.exit(1); });
