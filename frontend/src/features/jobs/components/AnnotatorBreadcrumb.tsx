import ProjectBreadcrumb, { type BreadcrumbItem } from '../../../shared/components/ui/ProjectBreadcrumb'

export type Crumb = BreadcrumbItem

/** Wrapper tương thích cho các màn hình Annotator (Home tự điều hướng theo vai trò). */
export default function AnnotatorBreadcrumb({ projectId, items }: { projectId: number | null; items: Crumb[] }) {
  return <ProjectBreadcrumb projectId={projectId} items={items} />
}
