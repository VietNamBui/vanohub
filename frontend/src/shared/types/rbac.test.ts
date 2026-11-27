import { describe, expect, it } from 'vitest'
import { CAPABILITY_LABELS, type Capability } from './capabilities'
import { GRANTABLE_ROLES, ROLE_LABELS, ROLE_ORDER, ROLE_SHORT_LABELS, type Role } from './roles'

describe('RBAC frontend contracts', () => {
  it('enforces the flat 4-role model without Director or Team Leader', () => {
    const expectedRoles: Role[] = ['project_manager', 'qc2', 'qc1', 'annotator']
    expect(ROLE_ORDER).toEqual(expectedRoles)
    expect(Object.keys(ROLE_LABELS).sort()).toEqual([...expectedRoles].sort())
    expect(Object.keys(ROLE_SHORT_LABELS).sort()).toEqual([...expectedRoles].sort())
    expect(GRANTABLE_ROLES).toEqual(['qc2', 'qc1', 'annotator'])
    expect(GRANTABLE_ROLES).not.toContain('project_manager')
  })

  it('defines labels for all 16 backend capabilities', () => {
    const capabilities = Object.keys(CAPABILITY_LABELS) as Capability[]
    expect(capabilities).toHaveLength(16)
    for (const cap of capabilities) {
      expect(CAPABILITY_LABELS[cap].trim().length).toBeGreaterThan(0)
    }
  })
})
