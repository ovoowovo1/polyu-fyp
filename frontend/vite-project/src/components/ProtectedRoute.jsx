import React, { useEffect, useState } from 'react'
import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { Spin } from 'antd'
import { useDispatch } from 'react-redux'

import { isAuthenticated, verifyToken } from '../api/auth'
import { resetDocumentState } from '../redux/documentSlice'
import { resetStudioState } from '../redux/studioSlice'

export default function ProtectedRoute() {
  const dispatch = useDispatch()
  const location = useLocation()
  const [authStatus, setAuthStatus] = useState(() => (isAuthenticated() ? 'authenticated' : 'checking'))

  useEffect(() => {
    let active = true

    const verifySession = async () => {
      if (isAuthenticated()) {
        if (active) setAuthStatus('authenticated')
        return
      }

      try {
        await verifyToken()
        if (active) setAuthStatus('authenticated')
      } catch {
        if (active) setAuthStatus('unauthenticated')
      }
    }

    verifySession()
    return () => {
      active = false
    }
  }, [location.pathname])

  useEffect(() => {
    if (authStatus === 'unauthenticated') {
      dispatch(resetDocumentState())
      dispatch(resetStudioState())
    }
  }, [authStatus, dispatch])

  if (authStatus === 'checking') {
    return (
      <div className="flex h-full items-center justify-center p-8">
        <Spin size="large" />
      </div>
    )
  }

  if (authStatus === 'unauthenticated') {
    return <Navigate to="/" replace state={{ from: location.pathname }} />
  }

  return <Outlet />
}
