import packageJsonRaw from '../../package.json?raw'
import viteConfigRaw from '../../vite.config.ts?raw'
import routerRaw from '../app/router.tsx?raw'
import { describe, expect, it } from 'vitest'
import { CAPABILITY_LABELS } from './types/capabilities'

const sourceFiles = import.meta.glob('../**/*.{ts,tsx}', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

describe('frontend architecture regressions', () => {
  it('keeps Ant Design completely removed from dependencies, Vite config, and source imports', () => {
    const pkg = JSON.parse(packageJsonRaw) as {
      dependencies?: Record<string, string>
      devDependencies?: Record<string, string>
    }
    const allDeps = [
      ...Object.keys(pkg.dependencies ?? {}),
      ...Object.keys(pkg.devDependencies ?? {}),
    ]
    expect(allDeps.filter((dep) => dep === 'antd' || dep.startsWith('@ant-design/'))).toEqual([])
    expect(viteConfigRaw).not.toMatch(/antd|vendor-rc/)

    const antdImportPattern = /(?:from|import)\s+['"](?:antd|@ant-design\/[^'"]+)['"]/
    const offenders: string[] = []
    for (const [path, content] of Object.entries(sourceFiles)) {
      if (path.endsWith('/architecture.test.ts')) continue
      if (antdImportPattern.test(content)) {
        offenders.push(path)
      }
    }
    expect(offenders).toEqual([])
  })

  it('ensures every guarded() route capability in router.tsx maps to a known capability key', () => {
    const guardedCalls = Array.from(
      routerRaw.matchAll(/\bguarded\s*\(\s*'[^']+'\s*,\s*(\[[^\]]+\]|'[^']+')\s*,/g),
    )
    expect(guardedCalls.length).toBeGreaterThanOrEqual(25)

    const validCaps = new Set(Object.keys(CAPABILITY_LABELS))
    const foundCaps: string[] = []
    for (const match of guardedCalls) {
      const routeCaps = Array.from(match[1].matchAll(/'([a-z0-9_]+)'/g)).map((m) => m[1])
      expect(routeCaps.length).toBeGreaterThanOrEqual(1)
      for (const cap of routeCaps) {
        foundCaps.push(cap)
        expect(validCaps.has(cap), `Unknown capability "${cap}" in ${match[0]}`).toBe(true)
      }
    }
    expect(foundCaps.length).toBeGreaterThanOrEqual(27)
  })
})
