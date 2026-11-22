import { ConfigProvider } from 'antd'
import { RouterProvider } from 'react-router'
import { router } from './app/router'

function App() {
  return (
    <ConfigProvider>
      <RouterProvider router={router} />
    </ConfigProvider>
  )
}

export default App
