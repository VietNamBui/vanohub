/** Gắn query param `frame` vào URL CVAT, giữ nguyên các query sẵn có (vd. `?org=`). */
export function cvatFrameUrl(url: string, frame: number): string {
  return `${url}${url.includes('?') ? '&' : '?'}frame=${frame}`
}
