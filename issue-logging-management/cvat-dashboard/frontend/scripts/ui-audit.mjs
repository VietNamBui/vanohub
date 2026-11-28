// Quét giao diện tự động: mỗi vai demo × mọi trang × (desktop, mobile).
// Bắt: lỗi JS/console, chữ bị cắt, tiêu đề cột bị cắt/bẻ dòng, chữ nhỏ bị giãn âm, trang tràn ngang; bấm thử từng nút (desktop).
// Dùng: npm run ui-audit            (build + preview tự bật, cổng 4799)
//       npm run ui-audit -- --no-click --base=http://localhost:5173
// Kết quả: <tmpdir>/cvat-ui-audit/findings.json + shots/*.png. Mã thoát 1 nếu có phát hiện.
import { chromium } from 'playwright'
import { preview } from 'vite'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const arg = (k) => process.argv.find((a) => a.startsWith(`--${k}=`))?.slice(k.length + 3)
const CLICK = !process.argv.includes('--no-click')
const outDir = arg('out') ?? path.join(os.tmpdir(), 'cvat-ui-audit')
fs.rmSync(outDir, { recursive: true, force: true })
fs.mkdirSync(path.join(outDir, 'shots'), { recursive: true })

const STATIC = ['/queue', '/pm', '/pm/distribute', '/pm/config', '/pm/drift', '/lead/members', '/me', '/me/kpi',
  '/admin', '/admin/teams', '/profile', '/audits', '/stats']
const DETAIL = [/^\/jobs\/[^/]+$/, /^\/audits\/[^/]+$/, /^\/pm\/teams\/[^/]+$/, /^\/pm\/users\/[^/]+$/]
const VIEWPORTS = { desktop: { width: 1440, height: 900 }, mobile: { width: 390, height: 844 } }
const SKIP_BUTTON = /đăng xuất|logout/i
// Bỏ nút nội bộ của AntD (nút tăng/giảm InputNumber chỉ hiện khi rê chuột).
const BTN = ':is(button, [role=button], .cvd-pill):visible:not(.ant-input-number-handler)'
const OVERLAY = '.ant-modal-wrap:visible, .ant-drawer-open, .ant-popover:visible, .ant-dropdown:visible'
const MAX_CLICKS_PER_PAGE = 30

/** Chạy trong trình duyệt: trả về danh sách lỗi hiển thị trên trang hiện tại. */
function inspect() {
  const out = []
  const vis = (el) => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none' }
  const label = (el) => (el.innerText || el.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ').slice(0, 60)
  const sel = (el) => { const c = typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : ''; return el.tagName.toLowerCase() + c }
  for (const el of document.querySelectorAll('body *')) {
    if (!vis(el) || el.closest('.ant-select-dropdown,.ant-picker-dropdown,.ant-tooltip,svg,canvas')) continue
    if (![...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())) continue
    const cs = getComputedStyle(el)
    if (el.scrollWidth > el.clientWidth + 1 && ['hidden', 'clip'].includes(cs.overflowX) && cs.textOverflow !== 'ellipsis') {
      out.push({ kind: 'text-clipped', el: sel(el), text: label(el), detail: `${el.scrollWidth}>${el.clientWidth}` })
    }
    const size = parseFloat(cs.fontSize); const ls = parseFloat(cs.letterSpacing)
    if (!Number.isNaN(ls) && ls <= -0.5 && size < 20) out.push({ kind: 'squeezed-text', el: sel(el), text: label(el), detail: `font ${size}px, letter-spacing ${ls}px` })
  }
  for (const th of document.querySelectorAll('th.ant-table-cell')) {
    if (!vis(th) || !th.innerText.trim()) continue
    const range = document.createRange(); range.selectNodeContents(th)
    const rects = [...range.getClientRects()]
    const textW = range.getBoundingClientRect().width
    const cs = getComputedStyle(th)
    const inner = th.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight)
    if (textW > inner + 2) out.push({ kind: 'header-clipped', el: 'th', text: label(th), detail: `${Math.round(textW)}>${Math.round(inner)}` })
    const words = th.innerText.trim().split(/\s+/).length
    const lines = new Set(rects.map((r) => Math.round(r.top))).size
    if (lines > words) out.push({ kind: 'header-broken', el: 'th', text: label(th), detail: `${lines} dòng cho ${words} từ` })
  }
  if (document.documentElement.scrollWidth > window.innerWidth + 1) out.push({ kind: 'page-hscroll', el: 'html', text: '', detail: `${document.documentElement.scrollWidth}>${window.innerWidth}` })
  return out
}

/** Chờ mọi hộp thoại/lớp mờ AntD ẩn hẳn (hiệu ứng đóng ~300ms vẫn chặn chuột). */
const overlaysGone = (page) => page.waitForFunction(() => [...document.querySelectorAll('.ant-modal-wrap, .ant-modal-mask, .ant-drawer-mask')]
  .every((w) => getComputedStyle(w).display === 'none' || w.getBoundingClientRect().width === 0), null, { timeout: 3000 }).catch(() => {})
const goto = (page, to) => page.evaluate((p) => { history.pushState({}, '', p); dispatchEvent(new PopStateEvent('popstate')) }, to)
const settle = async (page) => { await page.waitForLoadState('networkidle').catch(() => {}); await page.waitForTimeout(250) }
const login = async (page, base, i) => { await page.goto(`${base}/login`); await page.locator('.lg-chip').nth(i).click(); await settle(page) }

async function auditUser(browser, base, u) {
  const findings = []
  for (const [vp, viewport] of Object.entries(VIEWPORTS)) {
    const page = await (await browser.newContext({ viewport })).newPage()
    const errs = []
    page.on('pageerror', (e) => errs.push(e.message))
    page.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()) })
    await login(page, base, u.i)
    const routes = [...STATIC]
    const seen = new Set()
    for (let ri = 0; ri < routes.length; ri++) {
      const r = routes[ri]
      errs.length = 0
      await goto(page, r)
      await settle(page)
      const final = new URL(page.url()).pathname
      if (seen.has(final)) continue // trang bị chặn quyền ⇒ chuyển về trang đã quét
      seen.add(final)
      const where = { user: u.name, vp, route: final }
      for (const f of await page.evaluate(inspect)) findings.push({ ...where, ...f })
      for (const e of errs) findings.push({ ...where, kind: 'js-error', text: e.slice(0, 200) })
      await page.screenshot({ path: path.join(outDir, 'shots', `${u.i}-${vp}${final.replace(/\//g, '_')}.png`), fullPage: true })
      if (vp === 'desktop') {
        const hrefs = await page.$$eval('a[href]', (as) => as.map((a) => new URL(a.href).pathname))
        for (const h of hrefs) for (const re of DETAIL) if (re.test(h) && !routes.some((x) => re.test(x))) routes.push(h)
      }
      if (!CLICK || vp !== 'desktop') continue
      // Mỗi tên nút bấm một lần (nút lặp theo dòng chỉ thử dòng đầu); trước mỗi lần bấm đưa trang về trạng thái sạch.
      const btnNames = () => page.locator(BTN).evaluateAll((els) => els.map((e) => (e.innerText || e.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ').slice(0, 50)))
      const picks = [...new Set((await btnNames()).filter((n) => !SKIP_BUTTON.test(n)))]
      for (const name of picks.slice(0, MAX_CLICKS_PER_PAGE)) {
        if (new URL(page.url()).pathname !== final || await page.locator(OVERLAY).count()) {
          // đóng như người dùng: bấm ✕ của hộp thoại (Escape chỉ ăn khi focus đã vào trong hộp thoại)
          for (const x of await page.locator('.ant-modal-close:visible, .ant-drawer-close:visible').all()) await x.click({ timeout: 1000 }).catch(() => {})
          await page.keyboard.press('Escape').catch(() => {})
          // hộp thoại gắn ở layout không mất khi đổi trang; chờ hiệu ứng đóng xong kẻo lớp mờ chặn cú bấm sau
          await goto(page, final)
          await settle(page)
        }
        await overlaysGone(page)
        // tìm lại theo tên: lần bấm trước có thể làm danh sách nút đổi thứ tự
        const bi = (await btnNames()).indexOf(name)
        if (bi < 0) continue
        const btn = page.locator(BTN).nth(bi)
        if (!(await btn.isEnabled().catch(() => false))) continue
        errs.length = 0
        try {
          await btn.click({ timeout: 3000 })
          await page.waitForTimeout(300)
          if (await page.locator('.ant-modal-wrap:visible, .ant-drawer-open').count()) {
            for (const f of await page.evaluate(inspect)) if (f.kind !== 'page-hscroll') findings.push({ ...where, ...f, detail: `${f.detail} (sau khi bấm "${name}")` })
          }
        } catch (e) {
          const lines = e.message.split('\n')
          let why = lines.find((l) => /intercepts|not visible|not enabled|detached/.test(l)) ?? lines[0]
          if (/intercepts/.test(why)) {
            const open = await page.$$eval('.ant-modal-wrap', (ws) => ws.filter((w) => getComputedStyle(w).display !== 'none').map((w) => w.querySelector('.ant-modal-title')?.textContent ?? '?'))
            why = `bị hộp thoại đang mở chặn: ${open.join(', ') || '?'}`
          }
          findings.push({ ...where, kind: 'click-failed', text: name, detail: why.replace(/\x1b\[[0-9;]*m/g, '').trim().slice(0, 200) })
        }
        for (const e of errs) findings.push({ ...where, kind: 'js-error', text: `bấm "${name}": ${e.slice(0, 200)}` })
        if (new URL(page.url()).pathname === '/login') await login(page, base, u.i)
      }
    }
    await page.context().close()
  }
  console.log(`✓ ${u.name}: ${findings.length} phát hiện`)
  return findings
}

let server
let base = arg('base')
if (!base) {
  server = await preview({ preview: { port: 4799, strictPort: true }, logLevel: 'error' })
  base = 'http://localhost:4799'
}
const browser = await chromium.launch()
try {
  const page = await browser.newPage()
  await page.goto(`${base}/login`)
  const users = await page.$$eval('.lg-chip', (els) => els.map((e, i) => ({ i, name: e.innerText.trim().replace(/\s+/g, ' ') })))
  await page.close()
  if (users.length === 0) throw new Error('Không thấy tài khoản demo (.lg-chip) ở /login')
  const all = (await Promise.all(users.map((u) => auditUser(browser, base, u)))).flat()
  const uniq = [...new Map(all.map((f) => [[f.kind, f.vp, f.route, f.el, f.text].join('|'), f])).values()]
  fs.writeFileSync(path.join(outDir, 'findings.json'), JSON.stringify(uniq, null, 2))
  const byKind = {}
  for (const f of uniq) byKind[f.kind] = (byKind[f.kind] ?? 0) + 1
  for (const f of uniq) console.log(`✗ ${f.kind} · ${f.user} · ${f.vp} · ${f.route} · ${f.text ?? ''} ${f.detail ?? ''}`)
  console.log(`\nTổng: ${uniq.length} phát hiện ${JSON.stringify(byKind)} · báo cáo: ${outDir}`)
  process.exitCode = uniq.length ? 1 : 0
} finally {
  await browser.close()
  await new Promise((res) => (server ? server.httpServer.close(res) : res()))
}
