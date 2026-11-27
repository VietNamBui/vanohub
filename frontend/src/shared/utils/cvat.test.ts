import { describe, expect, it } from 'vitest'
import { cvatFrameUrl } from './cvat'

describe('cvatFrameUrl', () => {
  it('appends ?frame= when the base CVAT job URL has no query string', () => {
    expect(cvatFrameUrl('http://localhost:8080/tasks/12/jobs/34', 15)).toBe(
      'http://localhost:8080/tasks/12/jobs/34?frame=15',
    )
  })

  it('appends &frame= when the CVAT job URL already includes ?org=', () => {
    expect(cvatFrameUrl('http://localhost:8080/tasks/12/jobs/34?org=acme', 15)).toBe(
      'http://localhost:8080/tasks/12/jobs/34?org=acme&frame=15',
    )
  })
})
