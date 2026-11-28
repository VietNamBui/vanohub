import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { ConfigProvider, App as AntApp } from 'antd'
import viVN from 'antd/locale/vi_VN'
import dayjs from 'dayjs'
import 'dayjs/locale/vi'
import { StoreProvider } from './mock/store'
import { AppRoutes } from './routes'
import './design/dashboard.scss'

dayjs.locale('vi')

const FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <StoreProvider>
      <BrowserRouter>
        <ConfigProvider
          locale={viVN}
          theme={{
            token: { colorPrimary: '#1d6ff2', borderRadius: 10, fontFamily: FONT, colorText: '#303030', colorBgLayout: '#efefef' },
            components: { Table: { headerBg: 'transparent', colorBgContainer: 'transparent' } },
          }}
        >
          <AntApp>
            <AppRoutes />
          </AntApp>
        </ConfigProvider>
      </BrowserRouter>
    </StoreProvider>
  </StrictMode>,
)
