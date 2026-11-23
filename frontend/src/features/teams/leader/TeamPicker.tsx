import { Select } from '@/components/base/select/select'

/** Chọn team khi leader phụ trách nhiều team. Chỉ 1 team → không hiện gì. */
export default function TeamPicker({ teams, value, onChange }: {
  teams: { id: number; name: string }[]
  value: number | null
  onChange: (teamId: number | null) => void
}) {
  if (teams.length < 2) return null
  return (
    <Select
      aria-label="Chọn team"
      size="sm"
      className="w-48"
      selectedKey={value ?? 0}
      onSelectionChange={(k) => onChange(Number(k) || null)}
      items={[{ id: 0, label: 'Tất cả team của tôi' }, ...teams.map((t) => ({ id: t.id, label: t.name }))]}
    >
      {(item) => <Select.Item id={item.id} label={item.label} />}
    </Select>
  )
}
