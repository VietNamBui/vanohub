import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Input, Modal, type InputRef } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import { useStore } from '../mock/store'
import { searchFor } from '../mock/search'
export function QuickSearch() {
  const s = useStore()
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const input = useRef<InputRef | null>(null)
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement
      const editing = target.closest('input, textarea, select, [contenteditable="true"]')
      if ((e.key === '/' && !editing) || ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k')) {
        e.preventDefault(); setOpen(v => !v)
      }
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [])
  useLayoutEffect(() => { if (open) input.current?.focus() }, [open])
  const focusInput = useCallback((node: InputRef | null) => { input.current = node; if (node && open) node.focus() }, [open])
  const results = searchFor(s, s.currentUser.id, query)
  return <>
    <button type="button" className="cvd-qs-trigger" onClick={() => setOpen(true)} aria-label="Tìm nhanh"><SearchOutlined /> Tìm nhanh <kbd>/</kbd></button>
    <Modal transitionName="" title="Tìm nhanh" open={open} footer={null} onCancel={() => setOpen(false)} afterOpenChange={shown => { if (shown) input.current?.focus() }}>
      <Input ref={focusInput} aria-label="Tìm job, batch, dự án, dataset" placeholder="Job ID, CVAT ID, tên hoặc mã…" value={query} onChange={e => setQuery(e.target.value)} allowClear />
      <div className="cvd-qs-results">
        {(['Job', 'Batch', 'Dự án', 'Dataset'] as const).map(type => {
          const group = results.filter(r => r.type === type)
          return group.length ? <section key={type}><h3>{type}</h3>{group.map(r => <Link key={r.id} to={r.link} onClick={() => setOpen(false)}>{r.title}</Link>)}</section> : null
        })}
        <p>{!query.trim() ? 'Nhập từ khoá để tìm' : !results.length ? 'Không có kết quả' : `${results.length} kết quả`}</p>
      </div>
    </Modal>
  </>
}
