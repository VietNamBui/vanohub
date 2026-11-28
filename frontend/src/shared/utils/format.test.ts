import { describe, expect, it } from 'vitest'
import {
  APP_TIME_ZONE,
  formatCsvFileDate,
  formatCsvTimestamp,
  formatDate,
  formatDateTime,
  formatDateTimeLocalVN,
  formatNumber,
  formatPercent,
  formatRelative,
  formatShortDate,
  formatShortDateTime,
  formatTimeFirstDateTime,
  formatViPercent,
  getCurrentHourVN,
  parseDateTimeLocalVN,
} from './format'

describe('format utilities (fixed Asia/Ho_Chi_Minh UTC+7)', () => {
  it('locks APP_TIME_ZONE to Asia/Ho_Chi_Minh', () => {
    expect(APP_TIME_ZONE).toBe('Asia/Ho_Chi_Minh')
  })

  it('formats UTC timestamps across midnight boundary in UTC+7', () => {
    // 2026-11-26T18:30:00Z == 2026-11-27 01:30 UTC+7
    const iso = '2026-11-26T18:30:00Z'
    expect(formatDateTime(iso)).toBe('27/11/2026 01:30')
    expect(formatDate(iso)).toBe('27/11/2026')
    expect(formatShortDate(iso)).toBe('27/11')
    expect(formatShortDateTime(iso)).toBe('27/11 01:30')
    expect(formatTimeFirstDateTime(iso)).toBe('01:30 · 27/11/2026')
    expect(getCurrentHourVN(new Date(iso))).toBe(1)
  })

  it('preserves ISO date-only strings without shifting timezone', () => {
    expect(formatDate('2026-11-27')).toBe('27/11/2026')
    expect(formatShortDate('2026-11-27')).toBe('27/11')
    expect(formatDate('2026-02-30')).toBe('—')
  })

  it('round-trips datetime-local values cleanly between UTC and UTC+7', () => {
    const utcIso = '2026-11-26T17:15:00.000Z'
    const localInput = formatDateTimeLocalVN(utcIso)
    expect(localInput).toBe('2026-11-27T00:15')
    expect(parseDateTimeLocalVN(localInput)).toBe(utcIso)
    expect(parseDateTimeLocalVN('')).toBeNull()
    expect(parseDateTimeLocalVN('invalid')).toBeNull()
  })

  it('formats CSV timestamps and file dates in UTC+7', () => {
    const dt = new Date('2026-11-26T20:05:00Z')
    expect(formatCsvTimestamp(dt)).toBe('27/11/2026 03:05 (UTC+7)')
    expect(formatCsvFileDate(dt)).toBe('20261127')
  })

  it('handles null/invalid values gracefully', () => {
    expect(formatDateTime(null)).toBe('—')
    expect(formatDateTime('not-a-date')).toBe('—')
    expect(formatPercent(null)).toBe('—')
    expect(formatPercent(87.5)).toBe('87.5%')
    expect(formatViPercent(null)).toBe('—')
    expect(formatViPercent(85.7)).toBe('85,7%')
    expect(formatViPercent(80)).toBe('80%')
    expect(formatNumber(null)).toBe('—')
    expect(formatRelative(null)).toBe('—')
    expect(formatRelative(new Date(Date.now() - 5 * 60_000).toISOString())).toContain('phút')
  })
})
