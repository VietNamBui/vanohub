import PageState from '../../../shared/components/ui/PageState'
import SectionCard from '../../../shared/components/ui/SectionCard'

/** Leader chưa được PM đặt làm leader của team nào trong dự án. */
export default function NoTeamNotice() {
  return (
    <SectionCard>
      <PageState kind="empty" title="Bạn chưa phụ trách team nào"
        description="PM cần đặt bạn làm Team Leader của một team (Nhân sự › Team & Members) thì các màn hình này mới có dữ liệu." />
    </SectionCard>
  )
}
