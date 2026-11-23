// Khai báo kiểu cho biến môi trường của Vite để TypeScript biết import.meta.env có gì.
interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
