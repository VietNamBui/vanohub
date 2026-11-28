import { useState } from 'react'
import { Badge } from '@/components/base/badges/badges'
import { Button } from '@/components/base/buttons/button'
import { Input } from '@/components/base/input/input'
import { InputNumber } from '@/components/base/input/input-number'
import { Select } from '@/components/base/select/select'
import { Toggle } from '@/components/base/toggle/toggle'
import { getErrorMessage } from '../../../shared/api/errors'
import PageState from '../../../shared/components/ui/PageState'
import ProjectBreadcrumb from '../../../shared/components/ui/ProjectBreadcrumb'
import SectionCard from '../../../shared/components/ui/SectionCard'
import { useAction } from '../../../shared/hooks/useAction'
import { useRequest } from '../../../shared/hooks/useRequest'
import { formatDateTime } from '../../../shared/utils/format'
import { getSettings, updateSettings } from '../api'
import { useProject } from '../projectContext'
import { validateProjectSettingsDraft, type ProjectSettingsDraft } from '../projectHelpers'
import type { EscalationPolicy, ProjectSettings } from '../types'

const ESCALATION_ITEMS: { id: EscalationPolicy; label: string }[] = [
  { id: 'block', label: 'Khoá job chờ PM xử lý' },
  { id: 'warn_only', label: 'Chỉ cảnh báo (vẫn cho sửa)' },
]

function toDraft(settings: ProjectSettings): ProjectSettingsDraft {
  return {
    max_rework_rounds: settings.max_rework_rounds,
    escalation_policy: settings.escalation_policy,
    annotator_wip_limit: settings.annotator_wip_limit,
    sampling_rate: settings.sampling_rate,
    issue_gate_enabled: Boolean(settings.issue_gate_enabled),
    quality_cl_threshold: settings.quality_cl_threshold ?? '',
    defect_rate_threshold: settings.defect_rate_threshold ?? '',
    kpi_annotation_target: settings.kpi_annotation_target != null ? String(settings.kpi_annotation_target) : '',
    kpi_qc1_target: settings.kpi_qc1_target != null ? String(settings.kpi_qc1_target) : '',
    kpi_qc2_target: settings.kpi_qc2_target != null ? String(settings.kpi_qc2_target) : '',
  }
}

/** Cấu hình organization (PM): giới hạn rework, chính sách escalation, WIP, tỉ lệ QC2, ngưỡng chất lượng & KPI. */
export default function ProjectSettingsPage() {
  const { project, projectId, reload: reloadProject } = useProject()
  const [version, setVersion] = useState(0)
  const { data, error, isLoading, retry } = useRequest(`project-settings:${projectId}:${version}`, () =>
    getSettings(projectId),
  )

  const handleSaved = () => {
    setVersion((v) => v + 1)
    reloadProject()
  }

  const formKey = data
    ? `${projectId}:${version}:${data.max_rework_rounds}:${data.escalation_policy}:${data.annotator_wip_limit}:${data.sampling_rate}:${Boolean(data.issue_gate_enabled)}:${data.quality_cl_threshold ?? ''}:${data.defect_rate_threshold ?? ''}:${data.kpi_annotation_target ?? ''}:${data.kpi_qc1_target ?? ''}:${data.kpi_qc2_target ?? ''}`
    : `empty:${projectId}`

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-5 p-4 md:p-6">
      <ProjectBreadcrumb projectId={projectId} items={[{ label: 'Cấu hình organization' }]} />

      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-display-xs font-semibold text-primary">Cấu hình organization</h1>
          <p className="mt-1 text-sm text-tertiary">
            Thiết lập giới hạn rework, xử lý escalation, tỉ lệ QC2 và chỉ tiêu KPI cho{' '}
            <span className="font-medium text-secondary">{project.name}</span>.
          </p>
        </div>
        {data && (
          <Badge type="pill-color" size="md" color={data.cvat_org_id != null ? 'brand' : 'gray'}>
            {data.cvat_org_id != null ? `CVAT: ${data.cvat_org_slug || `#${data.cvat_org_id}`}` : 'Organization nội bộ'}
          </Badge>
        )}
      </header>

      {error != null ? (
        <SectionCard>
          <PageState kind="error" description={getErrorMessage(error)} onRetry={retry} />
        </SectionCard>
      ) : isLoading && !data ? (
        <SectionCard>
          <PageState kind="loading" />
        </SectionCard>
      ) : data ? (
        <>
          {data.cvat_org_id != null && (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-primary px-4 py-3 text-sm text-tertiary ring-1 ring-secondary">
              <span>
                CVAT Organization #{data.cvat_org_id}
                {data.cvat_org_slug ? ` (${data.cvat_org_slug})` : ''}
              </span>
              <span>Đồng bộ gần nhất: {formatDateTime(data.cvat_synced_at)}</span>
            </div>
          )}
          <SettingsForm key={formKey} projectId={projectId} initial={data} onSaved={handleSaved} />
        </>
      ) : null}
    </div>
  )
}

function SettingsForm({
  projectId,
  initial,
  onSaved,
}: {
  projectId: number
  initial: ProjectSettings
  onSaved: () => void
}) {
  const [draft, setDraft] = useState<ProjectSettingsDraft>(() => toDraft(initial))
  const [showErrors, setShowErrors] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const { run, pending } = useAction()

  const validation = validateProjectSettingsDraft(draft)

  function reset() {
    setDraft(toDraft(initial))
    setShowErrors(false)
    setSubmitError(null)
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setShowErrors(true)
    setSubmitError(null)
    if (!validation.valid || !validation.payload) return

    const payload = validation.payload
    const updated = await run(
      () =>
        updateSettings(projectId, payload).catch((err: unknown) => {
          setSubmitError(getErrorMessage(err))
          throw err
        }),
      'Đã lưu cấu hình organization',
    )
    if (updated) onSaved()
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-5">
      <SectionCard
        title="Quy trình & Giới hạn làm việc"
        description="Kiểm soát số vòng rework trước khi cảnh báo/khoá và số job tối đa mỗi Annotator giữ cùng lúc."
      >
        <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
          <InputNumber
            label="Số vòng rework tối đa"
            minValue={1}
            maxValue={32767}
            value={draft.max_rework_rounds}
            onChange={(v) => setDraft((prev) => ({ ...prev, max_rework_rounds: Number.isNaN(v) ? initial.max_rework_rounds : v }))}
            isInvalid={showErrors && Boolean(validation.errors.max_rework_rounds)}
            hint={
              (showErrors && validation.errors.max_rework_rounds) ||
              'Vượt số vòng này thì job chuyển trạng thái Escalated.'
            }
          />

          <Select
            label="Chế độ Escalated"
            items={ESCALATION_ITEMS}
            selectedKey={draft.escalation_policy}
            onSelectionChange={(k) =>
              setDraft((prev) => ({ ...prev, escalation_policy: (k as EscalationPolicy) || 'block' }))
            }
            hint="Áp dụng khi job vượt quá số vòng rework tối đa."
          >
            {(item) => <Select.Item id={item.id} label={item.label} />}
          </Select>

          <InputNumber
            label="Giới hạn job giữ cùng lúc (WIP)"
            minValue={1}
            maxValue={50}
            value={draft.annotator_wip_limit}
            onChange={(v) => setDraft((prev) => ({ ...prev, annotator_wip_limit: Number.isNaN(v) ? initial.annotator_wip_limit : v }))}
            isInvalid={showErrors && Boolean(validation.errors.annotator_wip_limit)}
            hint={
              (showErrors && validation.errors.annotator_wip_limit) ||
              'Số job tối đa mỗi Annotator được giữ đồng thời (1–50).'
            }
          />
        </div>

        <div className="mt-5 border-t border-secondary pt-5">
          <Toggle
            size="sm"
            isSelected={draft.issue_gate_enabled}
            onChange={(checked) => setDraft((prev) => ({ ...prev, issue_gate_enabled: checked }))}
            label="Bắt buộc đóng issue CVAT trước khi nộp / duyệt"
            hint="Chặn Annotator nộp bài khi còn issue mức Nặng/Nghiêm trọng (hoặc đã có phán quyết PM) đang mở, và chặn QC1/QC2 duyệt đạt hoặc bàn giao khi còn issue/yêu cầu làm rõ chưa xử lý."
          />
        </div>
      </SectionCard>

      <SectionCard
        title="Kiểm tra chất lượng QC2 & Ngưỡng cảnh báo"
        description="Cấu hình tỉ lệ lấy mẫu frame cho QC2 và các ngưỡng chất lượng mục tiêu."
      >
        <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
          <InputNumber
            label="Tỉ lệ frame QC2 kiểm (%)"
            minValue={1}
            maxValue={100}
            value={draft.sampling_rate}
            onChange={(v) => setDraft((prev) => ({ ...prev, sampling_rate: Number.isNaN(v) ? initial.sampling_rate : v }))}
            isInvalid={showErrors && Boolean(validation.errors.sampling_rate)}
            hint={
              (showErrors && validation.errors.sampling_rate) ||
              '% số frame của mỗi job đạt QC1 được QC2 kiểm ngẫu nhiên (1–100%).'
            }
          />

          <Input
            label="Ngưỡng Quality CL (%)"
            value={draft.quality_cl_threshold}
            onChange={(v) => setDraft((prev) => ({ ...prev, quality_cl_threshold: v }))}
            isInvalid={showErrors && Boolean(validation.errors.quality_cl_threshold)}
            hint={
              (showErrors && validation.errors.quality_cl_threshold) ||
              'Để trống nếu chưa đặt ngưỡng (0.00–100.00).'
            }
            placeholder="VD: 95.00"
          />

          <Input
            label="Ngưỡng Defect error rate (%)"
            value={draft.defect_rate_threshold}
            onChange={(v) => setDraft((prev) => ({ ...prev, defect_rate_threshold: v }))}
            isInvalid={showErrors && Boolean(validation.errors.defect_rate_threshold)}
            hint={
              (showErrors && validation.errors.defect_rate_threshold) ||
              'Để trống nếu chưa đặt ngưỡng (0.00–100.00).'
            }
            placeholder="VD: 5.00"
          />
        </div>
      </SectionCard>

      <SectionCard
        title="Chỉ tiêu KPI theo ngày"
        description="Đặt chỉ tiêu sản lượng hằng ngày cho từng vai trò (để trống nếu chưa áp dụng)."
      >
        <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
          <Input
            label="Chỉ tiêu Annotation (object / ngày)"
            value={draft.kpi_annotation_target}
            onChange={(v) => setDraft((prev) => ({ ...prev, kpi_annotation_target: v }))}
            isInvalid={showErrors && Boolean(validation.errors.kpi_annotation_target)}
            hint={(showErrors && validation.errors.kpi_annotation_target) || 'Tính theo tổng object-frame mỗi ngày.'}
            placeholder="VD: 150"
          />

          <Input
            label="Chỉ tiêu QC1 (job / ngày)"
            value={draft.kpi_qc1_target}
            onChange={(v) => setDraft((prev) => ({ ...prev, kpi_qc1_target: v }))}
            isInvalid={showErrors && Boolean(validation.errors.kpi_qc1_target)}
            hint={(showErrors && validation.errors.kpi_qc1_target) || 'Số job kiểm tra QC1 hoàn thành mỗi ngày.'}
            placeholder="VD: 20"
          />

          <Input
            label="Chỉ tiêu QC2 (job / ngày)"
            value={draft.kpi_qc2_target}
            onChange={(v) => setDraft((prev) => ({ ...prev, kpi_qc2_target: v }))}
            isInvalid={showErrors && Boolean(validation.errors.kpi_qc2_target)}
            hint={(showErrors && validation.errors.kpi_qc2_target) || 'Số mẫu audit QC2 hoàn thành mỗi ngày.'}
            placeholder="VD: 10"
          />
        </div>
      </SectionCard>

      {submitError && (
        <div role="alert" className="rounded-xl bg-error-primary px-4 py-3 text-sm text-error-primary ring-1 ring-error_subtle ring-inset">
          {submitError}
        </div>
      )}

      <div className="flex items-center justify-end gap-3">
        <Button color="secondary" size="md" onPress={reset} isDisabled={pending}>
          Đặt lại
        </Button>
        <Button type="submit" color="primary" size="md" isLoading={pending}>
          Lưu cấu hình
        </Button>
      </div>
    </form>
  )
}
