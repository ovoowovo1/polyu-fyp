import React from 'react'
import { Dropdown, Avatar } from 'antd'
import { UserOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import SwitchLanguage from './SwitchLanguage'

/**
 * 頭像下拉選單：顯示使用者資訊與登出按鈕
 */
export default function ProfileMenu({ user, onLogout, placement = 'bottomRight' }) {
  const { t } = useTranslation()

  const profileItems = [
    {
      key: 'language',
      label: (
        <div className="px-2 py-1">
          <SwitchLanguage />
        </div>
      ),
      disabled: true,
    },
    { type: 'divider' },
    {
      key: 'profile',
      label: <div className="px-2 text-gray-500">{user?.username || user?.email || t('common.user')}</div>,
      disabled: true,
    },
    { type: 'divider' },
    { key: 'logout', label: t('common.logout'), danger: true },
  ]

  const onProfileMenuClick = ({ key }) => {
    if (key === 'logout' && typeof onLogout === 'function') onLogout()
  }

  return (
    <Dropdown
      menu={{ items: profileItems, onClick: onProfileMenuClick }}
      placement={placement}
      trigger={['click']}
    >
      <Avatar
        style={{ backgroundColor: '#1677ff', cursor: 'pointer' }}
        size="large"
        icon={<UserOutlined />}
      />
    </Dropdown>
  )
}

