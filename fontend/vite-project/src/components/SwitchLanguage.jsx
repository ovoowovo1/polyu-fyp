import React from 'react'
import { Select } from 'antd'
import { useTranslation } from 'react-i18next'
import { GlobalOutlined } from '@ant-design/icons'

export default function SwitchLanguage() {
  const { i18n } = useTranslation()

  const handleLanguageChange = (value) => {
    i18n.changeLanguage(value)
  }

  return (
    <Select
      value={i18n.language || 'en'}
      onChange={handleLanguageChange}
      style={{ width: 120 }}
      suffixIcon={<GlobalOutlined />}
      options={[
        { value: 'en', label: 'English' },
        { value: 'zh-TW', label: '繁體中文' }
      ]}
    />
  )
}
