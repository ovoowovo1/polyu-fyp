import React, { useEffect } from 'react'
import { Navigate, useLocation, Outlet } from 'react-router-dom'
import { isAuthenticated } from '../api/auth'
import { useDispatch } from 'react-redux'
import { resetDocumentState } from '../redux/documentSlice'
import { resetStudioState } from '../redux/studioSlice'

// 路由保護元件：未登入則導回登入頁
export default function ProtectedRoute() {
  const dispatch = useDispatch()
  const location = useLocation()
  const authed = isAuthenticated()

  useEffect(() => {
    if (!authed) {
      dispatch(resetDocumentState())
      dispatch(resetStudioState())
    }
  }, [authed, dispatch])

  if (!authed) {
    return <Navigate to="/" replace state={{ from: location.pathname }} />
  }
  return <Outlet />
}

