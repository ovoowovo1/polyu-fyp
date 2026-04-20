import React, { useState } from 'react'
import { Form, Input, Button, message, Segmented } from 'antd'
import { UserOutlined, LockOutlined, TeamOutlined, BookOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useDispatch } from 'react-redux'
import { setCurrentClassId } from '../redux/documentSlice'
import { login } from '../api/auth'
import { useTranslation } from 'react-i18next'

export default function LoginPage() {
    const { t } = useTranslation()
    const [loading, setLoading] = useState(false)
    const [loginType, setLoginType] = useState('student') // 'student' 或 'teacher'
    const navigate = useNavigate()
    const dispatch = useDispatch()
    const [form] = Form.useForm()

    const handleLoginTypeChange = (value) => {
        setLoginType(value)
        form.resetFields() // Clear form when switching login type
    }

    const onFinish = async (values) => {
        setLoading(true)
        try {
            // 調用登入 API (包含前端選擇的角色)
            const response = await login(values.email, values.password, loginType)

            // 登入成功
            message.success(`${loginType === 'student' ? t('login.studentLogin') : t('login.teacherLogin')} ${t('login.loginSuccess')}`)

            // 清空目前選取的 class，然後導覽到文檔頁面
            dispatch(setCurrentClassId(null))
            navigate('/class-list')
        } catch (error) {
            // 顯示錯誤訊息
            const errorMessage = error.message || t('login.loginFailed')
            message.error(errorMessage)
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-50 via-white to-blue-50">
            {/* 背景裝飾 */}
            <div className="absolute inset-0 overflow-hidden pointer-events-none">
                <div className="absolute -top-40 -right-40 w-80 h-80 bg-blue-200 rounded-full mix-blend-multiply filter blur-xl opacity-30 animate-blob"></div>
                <div className="absolute -bottom-40 -left-40 w-80 h-80 bg-blue-300 rounded-full mix-blend-multiply filter blur-xl opacity-30 animate-blob animation-delay-2000"></div>
                <div className="absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 w-80 h-80 bg-blue-400 rounded-full mix-blend-multiply filter blur-xl opacity-30 animate-blob animation-delay-4000"></div>
            </div>

            {/* 登入表單容器 */}
            <div className="relative z-10 w-full max-w-md px-6">
                <div className="bg-white rounded-2xl shadow-2xl p-8 backdrop-blur-sm border border-blue-100">
                    {/* 登入類型切換 */}
                    <div className="mb-6 flex justify-center">
                        <Segmented
                            value={loginType}
                            onChange={handleLoginTypeChange}
                            options={[
                                {
                                    label: (
                                        <div className="flex items-center gap-2 px-2">
                                            <BookOutlined />
                                            <span>{t('login.studentLogin')}</span>
                                        </div>
                                    ),
                                    value: 'student',
                                },
                                {
                                    label: (
                                        <div className="flex items-center gap-2 px-2">
                                            <TeamOutlined />
                                            <span>{t('login.teacherLogin')}</span>
                                        </div>
                                    ),
                                    value: 'teacher',
                                },
                            ]}
                            size="large"
                        />
                    </div>

                    {/* 標題區塊 */}
                    <div className="text-center mb-8">
                        <div className="inline-flex items-center justify-center w-16 h-16 bg-gradient-to-br from-blue-500 to-blue-600 rounded-2xl mb-4 shadow-lg">
                            {loginType === 'student' ? (
                                <BookOutlined className="text-3xl text-white" />
                            ) : (
                                <TeamOutlined className="text-3xl text-white" />
                            )}
                        </div>
                        <h1 className="text-3xl font-bold text-gray-800 mb-2">
                            {loginType === 'student' ? t('login.studentLoginTitle') : t('login.teacherLoginTitle')}
                        </h1>
                        <p className="text-gray-500">
                            {loginType === 'student'
                                ? t('login.studentLoginDesc')
                                : t('login.teacherLoginDesc')}
                        </p>
                    </div>

                    {/* 表單 */}
                    <Form
                        form={form}
                        name="login"
                        onFinish={onFinish}
                        layout="vertical"
                        size="large"
                        autoComplete="off"
                    >
                        <Form.Item
                            name="email"
                            rules={[
                                { required: true, message: t('login.emailRequired') },
                                { type: 'email', message: t('login.emailInvalid') }
                            ]}
                        >
                            <Input
                                prefix={<UserOutlined className="text-blue-500" />}
                                placeholder={loginType === 'student' ? t('login.studentEmail') : t('login.teacherEmail')}
                                className="rounded-lg"
                            />
                        </Form.Item>

                        <Form.Item
                            name="password"
                            rules={[
                                { required: true, message: t('login.passwordRequired') },
                                { min: 6, message: t('login.passwordMinLength') }
                            ]}
                        >
                            <Input.Password
                                prefix={<LockOutlined className="text-blue-500" />}
                                placeholder={t('login.passwordPlaceholder')}
                                className="rounded-lg"
                            />
                        </Form.Item>

                        <Form.Item className="mb-0">
                            <Button
                                type="primary"
                                htmlType="submit"
                                loading={loading}
                                block
                                className="h-12 rounded-lg bg-gradient-to-r from-blue-500 to-blue-600 border-none text-white font-semibold text-base hover:from-blue-600 hover:to-blue-700 transition-all duration-300 shadow-lg hover:shadow-xl transform hover:-translate-y-0.5"
                            >
                                {loading ? t('login.loggingIn') : t('login.login')}
                            </Button>
                        </Form.Item>
                    </Form>

                    {/* 額外選項 */}
                    <div className="mt-6 text-center">
                        <a
                            href="#"
                            className="text-sm text-blue-600 hover:text-blue-700 font-medium transition-colors"
                        >
                            {t('login.forgotPassword')}
                        </a>
                    </div>
                </div>

                {/* 底部提示 */}
                <p className="text-center text-gray-500 text-sm mt-6">
                    {t('login.noAccount')}{' '}
                    <a href="#" className="text-blue-600 hover:text-blue-700 font-medium">
                        {t('login.signUp')}
                    </a>
                </p>
            </div>

            {/* 動畫樣式 */}
            <style>{`
                @keyframes blob {
                    0% {
                        transform: translate(0px, 0px) scale(1);
                    }
                    33% {
                        transform: translate(30px, -50px) scale(1.1);
                    }
                    66% {
                        transform: translate(-20px, 20px) scale(0.9);
                    }
                    100% {
                        transform: translate(0px, 0px) scale(1);
                    }
                }
                .animate-blob {
                    animation: blob 7s infinite;
                }
                .animation-delay-2000 {
                    animation-delay: 2s;
                }
                .animation-delay-4000 {
                    animation-delay: 4s;
                }
            `}</style>
        </div>
    )
}