/** Nội dung hiển thị khi bảng (Untitled UI Table) không có dòng nào. */
export default function EmptyRow({ text }: { text: string }) {
  return <div className="px-6 py-10 text-center text-sm text-tertiary">{text}</div>
}
