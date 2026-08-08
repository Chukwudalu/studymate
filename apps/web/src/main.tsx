import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import './index.css'
import { AuthProvider } from './AuthContext.tsx'
import RequireAuth from './RequireAuth.tsx'
import Layout from './Layout.tsx'
import UploadPage from './UploadPage.tsx'
import SubjectPage from './SubjectPage.tsx'
import LectureDetailPage from './LectureDetailPage.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AuthProvider>
      <RequireAuth>
        <BrowserRouter>
          <Routes>
            <Route element={<Layout />}>
              <Route path="/" element={<UploadPage />} />
              <Route path="/subject/:name" element={<SubjectPage />} />
              <Route path="/lecture/:id" element={<LectureDetailPage />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </RequireAuth>
    </AuthProvider>
  </StrictMode>,
)
