import { describe, expect, it } from 'vitest'
import { appendCvatOrg, cvatFrameUrl, cvatProjectUrl, cvatTaskUrl } from './cvat'

describe('cvat URL helpers', () => {
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

  it('appends ?org=<slug> cleanly without duplicating existing org params', () => {
    expect(appendCvatOrg('http://localhost:8080/projects/5', 'acme')).toBe(
      'http://localhost:8080/projects/5?org=acme',
    )
    expect(appendCvatOrg('http://localhost:8080/projects/5?org=existing', 'acme')).toBe(
      'http://localhost:8080/projects/5?org=existing',
    )
    expect(appendCvatOrg('http://localhost:8080/projects/5', '')).toBe('http://localhost:8080/projects/5')
  })

  it('builds project and task URLs with optional ?org=<slug> and strips trailing slashes', () => {
    expect(cvatProjectUrl('http://localhost:8080/', 900, 'acme')).toBe(
      'http://localhost:8080/projects/900?org=acme',
    )
    expect(cvatProjectUrl('http://localhost:8080', 900, null)).toBe('http://localhost:8080/projects/900')
    expect(cvatTaskUrl('http://localhost:8080/', 55, 'acme-team')).toBe(
      'http://localhost:8080/tasks/55?org=acme-team',
    )
    expect(cvatTaskUrl('', 55, 'acme')).toBe('')
  })
})
