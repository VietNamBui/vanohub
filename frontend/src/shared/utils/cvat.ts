/** Gắn query param `frame` vào URL CVAT, giữ nguyên các query sẵn có (vd. `?org=`). */
export function cvatFrameUrl(url: string, frame: number): string {
  return `${url}${url.includes('?') ? '&' : '?'}frame=${frame}`
}

/** Gắn query param `?org=<slug>` vào URL CVAT nếu có `orgSlug` và URL chưa có `org=`. */
export function appendCvatOrg(url: string, orgSlug?: string | null): string {
  const slug = orgSlug?.trim()
  if (!url || !slug) return url
  try {
    const parsed = new URL(url)
    if (!parsed.searchParams.has('org')) {
      parsed.searchParams.set('org', slug)
    }
    return parsed.toString()
  } catch {
    if (/[?&]org=/.test(url)) return url
    const [base, hash] = url.split('#', 2)
    const joined = `${base}${base.includes('?') ? '&' : '?'}org=${encodeURIComponent(slug)}`
    return hash != null ? `${joined}#${hash}` : joined
  }
}

/** Tạo URL mở CVAT Project kèm `?org=<slug>` (khi organization gắn CVAT). */
export function cvatProjectUrl(baseUrl: string, cvatProjectId: number, orgSlug?: string | null): string {
  const base = baseUrl.trim().replace(/\/+$/, '')
  if (!base) return ''
  return appendCvatOrg(`${base}/projects/${cvatProjectId}`, orgSlug)
}

/** Tạo URL mở CVAT Task kèm `?org=<slug>` (khi organization gắn CVAT). */
export function cvatTaskUrl(baseUrl: string, cvatTaskId: number, orgSlug?: string | null): string {
  const base = baseUrl.trim().replace(/\/+$/, '')
  if (!base) return ''
  return appendCvatOrg(`${base}/tasks/${cvatTaskId}`, orgSlug)
}
