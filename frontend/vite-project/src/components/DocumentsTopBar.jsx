import React, { useEffect, useState, useCallback } from 'react'
import { Button, Modal, Form, Input, message } from 'antd'
import { useSelector, useDispatch } from 'react-redux'
import { setCurrentClassId } from '../redux/documentSlice'
import { useNavigate } from 'react-router-dom'
import { logout, getCurrentUser } from '../api/auth'
import { listMyClasses, inviteStudent } from '../api/classes'
import { useTranslation } from 'react-i18next'
import ProfileMenu from './ProfileMenu'

/**
 * DocumentsTopBar
 * Props:
 * - title: string: custom title (defaults to localized documents.title)
 * - showInvite: boolean: whether to show the invite button (defaults true)
 * - showClassesList: boolean: whether to show the 'classes list' button (defaults true)
 * - extraActions: ReactNode: custom actions inserted to right-hand side
 * - onInvite: function: optional override for click handler of invite button
 */
export default function DocumentsTopBar({ title, showInvite = true, showClassesList = true, extraActions = null, onInvite: onInviteProp = null }) {
  const navigate = useNavigate()
  const { t } = useTranslation()
  const user = getCurrentUser()
  const isTeacher = user?.role === 'teacher'

  const [inviteOpen, setInviteOpen] = useState(false)
  const [form] = Form.useForm()
  const [classes, setClasses] = useState([])
  const [loadingClasses, setLoadingClasses] = useState(false)
  const [showMembers, setShowMembers] = useState(false)
  const currentClassId = useSelector(state => state.documents.currentClassId)

  const dispatch = useDispatch()
  const handleLogout = () => { logout(); navigate('/') }
  const currentClass = classes.find(c => c.id === currentClassId)
  const openInvite = () => {
    if (!currentClassId) {
      message.warning(t('classes.noClassSelected'))
      return
    }
    form.setFieldsValue({ classId: currentClassId })
    setInviteOpen(true)
  }
  const handleInviteClick = onInviteProp || openInvite
  const closeInvite = () => { setInviteOpen(false); form.resetFields(); setShowMembers(false) }

  const fetchClasses = useCallback(async () => {
    if (!isTeacher) return
    try {
      setLoadingClasses(true)
      const res = await listMyClasses()
      setClasses(res.classes || [])
    } catch (err) {
      message.error(err.message || t('classes.loadClassesFailed'))
    } finally {
      setLoadingClasses(false)
    }
  }, [isTeacher, t, form])

  useEffect(() => { fetchClasses() }, [fetchClasses])

  useEffect(() => {
    if (!isTeacher) return
    if (!classes || classes.length === 0) return
    const exists = classes.some(c => c.id === currentClassId)
    if (currentClassId && exists) {
      form.setFieldsValue({ classId: currentClassId })
    }
  }, [classes, currentClassId, form, isTeacher])

  const onInvite = async (values) => {
    try {
      const targetClassId = currentClassId || values.classId
      if (!targetClassId) {
        message.error(t('classes.noClassSelected'))
        return
      }
      await inviteStudent(targetClassId, values.email)
      await fetchClasses() // 重新拉最新學生名單
      message.success(t('classes.invitationSent'))
      closeInvite()
    } catch (err) {
      message.error(err.message || t('classes.invitationFailed'))
    }
  }

  return (
    <>
      <div className="px-4 py-2 flex items-center justify-between bg-white shadow-sm">
        <div className="text-lg font-semibold">{currentClass?.name || title }</div>
        <div className="flex items-center gap-2">
          {showClassesList && (
            <Button onClick={() => { dispatch(setCurrentClassId(null)); navigate('/class-list'); }}>{t('common.classesList')}</Button>
          )}
          {extraActions}
          {showInvite && isTeacher && (<Button onClick={handleInviteClick}>{t('common.invite')}</Button>)}
          <ProfileMenu user={user} onLogout={handleLogout} />
        </div>
      </div>

      <Modal
        title={t('classes.inviteStudent')}
        open={inviteOpen}
        onOk={() => form.submit()}
        onCancel={closeInvite}
        okText={t('common.invite')}
      >
        <Form layout="vertical" form={form} onFinish={onInvite}>
          <Form.Item name="email" label={t('classes.studentEmail')} rules={[{ required: true, type: 'email', message: t('classes.studentEmailPlaceholder') }]}>
            <Input placeholder={t('classes.studentEmailPlaceholder')} />
          </Form.Item>
          <div className="text-sm text-gray-500 mb-1">{t('classes.inviteToClass')}</div>
          <div className="px-3 py-2 rounded border bg-gray-50 mb-2">
            {currentClass ? currentClass.name : t('classes.noClassSelected')}
          </div>
          {currentClass && (
            <div className="mb-2">
              <Button type="link" size="small" onClick={() => setShowMembers(prev => !prev)}>
                {showMembers ? t('classes.hideStudents') : t('classes.showStudents')}
              </Button>
              {showMembers && (
                <div className="mt-1 max-h-40 overflow-auto border rounded px-3 py-2 bg-white">
                  {(currentClass.students && currentClass.students.length > 0) ? (
                    currentClass.students.map((s, idx) => (
                      <div key={s.id || idx} className="flex items-center justify-between py-1 border-b last:border-b-0">
                        <span>{s.name || s.email || t('common.user')}</span>
                        {s.email && <span className="text-gray-500 text-xs">{s.email}</span>}
                      </div>
                    ))
                  ) : (
                    <div className="text-gray-500 text-sm">{t('classes.noStudents') || 'No students yet'}</div>
                  )}
                </div>
              )}
            </div>
          )}
        </Form>
      </Modal>
    </>
  )
}
