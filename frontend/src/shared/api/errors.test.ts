import { describe, expect, it } from 'vitest'
import { getErrorKind, getErrorMessage } from './errors'

function fakeAxiosError(status?: number, data?: unknown) {
  return {
    isAxiosError: true,
    response: status === undefined ? undefined : { status, data },
  }
}

describe('shared/api/errors', () => {
  it('classifies HTTP status codes and network failures', () => {
    expect(getErrorKind(fakeAxiosError(undefined))).toBe('network')
    expect(getErrorKind(fakeAxiosError(400, { detail: 'Bad' }))).toBe('validation')
    expect(getErrorKind(fakeAxiosError(401, { detail: 'Unauth' }))).toBe('unauthorized')
    expect(getErrorKind(fakeAxiosError(403, { detail: 'Denied' }))).toBe('forbidden')
    expect(getErrorKind(fakeAxiosError(404, { detail: 'Missing' }))).toBe('not_found')
    expect(getErrorKind(fakeAxiosError(500, {}))).toBe('unknown')
    expect(getErrorKind(new Error('boom'))).toBe('unknown')
  })

  it('extracts DRF detail, field errors, and protects against raw HTML bodies', () => {
    expect(getErrorMessage(fakeAxiosError(400, { detail: 'Task đang bị khoá.' }))).toBe('Task đang bị khoá.')
    expect(getErrorMessage(fakeAxiosError(400, { recipient: ['Trường này là bắt buộc.'] }))).toBe(
      'recipient: Trường này là bắt buộc.',
    )
    expect(getErrorMessage(fakeAxiosError(400, { non_field_errors: ['Lỗi nghiệp vụ.'] }))).toBe('Lỗi nghiệp vụ.')
    expect(getErrorMessage(fakeAxiosError(500, '<html><body>500</body></html>'))).toBe(
      'Đã có lỗi xảy ra. Vui lòng thử lại.',
    )
    expect(getErrorMessage(fakeAxiosError(401, { detail: 'Token expired' }))).toBe(
      'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.',
    )
  })
})
