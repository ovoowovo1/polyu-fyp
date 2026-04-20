import React, { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Button, Input, Card, Space, Radio, Typography, message, Spin, Select } from 'antd'
import { PlusOutlined, DeleteOutlined, ArrowUpOutlined, ArrowDownOutlined } from '@ant-design/icons'
import { getQuizById, createQuiz, updateQuiz, getBloomLevels } from '../api/quiz'
import { useTranslation } from 'react-i18next'

const { TextArea } = Input
const { Title, Text } = Typography

const defaultQuestion = () => ({
    question: '',
    choices: ['', ''],
    answer_index: 0,
    rationale: '',
    bloom_level: '',
})

export default function EditQuiz() {
    const { t } = useTranslation()
    const { quizId } = useParams()
    const navigate = useNavigate()
    const [loading, setLoading] = useState(false)
    const [saving, setSaving] = useState(false)
    const [name, setName] = useState('')
    const [questions, setQuestions] = useState([defaultQuestion()])
    const [bloomOptions, setBloomOptions] = useState([])

    useEffect(() => {
        // load bloom levels for a nicer select UI
        getBloomLevels().then(res => {
            const list = (res.data && res.data.levels) || []
            setBloomOptions(list.map(l => ({ value: l.value, label: l.value })))
        }).catch(() => { })
    }, [])

    useEffect(() => {
        if (!quizId) return
        setLoading(true)
        getQuizById(quizId).then(res => {
            const quiz = res.data.quiz || res.data
            setName(quiz.name || '')
            setQuestions((quiz.questions && quiz.questions.length) ? quiz.questions : [defaultQuestion()])
        }).catch(err => {
            console.error(err)
            message.error(t('quiz.loadFailed'))
        }).finally(() => setLoading(false))
    }, [quizId, t])

    const updateQuestion = (idx, partial) => {
        setQuestions(prev => {
            const copy = [...prev]
            copy[idx] = { ...copy[idx], ...partial }
            return copy
        })
    }

    const addQuestion = () => setQuestions(prev => [...prev, defaultQuestion()])
    const removeQuestion = (idx) => setQuestions(prev => prev.filter((_, i) => i !== idx))
    const moveQuestion = (idx, dir) => {
        setQuestions(prev => {
            const copy = [...prev]
            const swp = copy[idx + dir]
            copy[idx + dir] = copy[idx]
            copy[idx] = swp
            return copy
        })
    }

    const addChoice = (qIdx) => {
        setQuestions(prev => {
            const copy = [...prev]
            copy[qIdx] = { ...copy[qIdx], choices: [...(copy[qIdx].choices || []), ''] }
            return copy
        })
    }

    const removeChoice = (qIdx, cIdx) => {
        setQuestions(prev => {
            const copy = [...prev]
            const choices = [...(copy[qIdx].choices || [])]
            choices.splice(cIdx, 1)
            // ensure at least 2 choices
            if (choices.length < 2) choices.push('')
            const answer_index = Math.min(copy[qIdx].answer_index || 0, choices.length - 1)
            copy[qIdx] = { ...copy[qIdx], choices, answer_index }
            return copy
        })
    }

    const handleSave = async () => {
        // basic validation
        if (!name || !name.trim()) {
            message.warning(t('quiz.provideQuizName'))
            return
        }
        for (let i = 0; i < questions.length; i++) {
            const q = questions[i]
            if (!q.question || !q.question.trim()) {
                message.warning(t('quiz.questionEmpty', { number: i + 1 }))
                return
            }
            if (!Array.isArray(q.choices) || q.choices.length < 2) {
                message.warning(t('quiz.questionMinChoices', { number: i + 1 }))
                return
            }
            if (q.answer_index == null || q.answer_index < 0 || q.answer_index >= q.choices.length) {
                message.warning(t('quiz.questionInvalidAnswer', { number: i + 1 }))
                return
            }
        }

        const payload = { name, questions }
        setSaving(true)
        try {
            if (quizId) {
                await updateQuiz(quizId, payload)
                message.success(t('quiz.quizUpdated'))
            } else {
                await createQuiz(payload)
                message.success(t('quiz.quizCreated'))
            }
            navigate(-1)
        } catch (err) {
            console.error(err)
            message.error(t('quiz.saveFailed'))
        } finally {
            setSaving(false)
        }
    }

    if (loading) return <div className="flex items-center justify-center h-full"><Spin size="large" /></div>

    return (
        <div className=" bg-gray-100 h-screen overflow-auto">

            <div className="bg-white sticky top-0 z-20 bg-gray-100 p-4 border-b border-gray-300">
                <div className="flex items-center justify-between mb-0">
                    <Title level={3} className="m-0">{quizId ? t('quiz.editQuiz') : t('quiz.createQuiz')}</Title>
                    <Space>
                        <Button onClick={() => navigate(-1)}>{t('common.cancel')}</Button>
                        <Button type="primary" loading={saving} onClick={handleSave}>{t('quiz.saveQuiz')}</Button>
                    </Space>
                </div>
            </div>

            <div className="p-6">
                <Card className="mb-6">
                    <Space direction="vertical" style={{ width: '100%' }}>
                        <Text strong>{t('quiz.quizName')}</Text>
                        <Input value={name} onChange={e => setName(e.target.value)} placeholder={t('quiz.enterQuizName')} />
                    </Space>
                </Card>

                <Space direction="vertical" style={{ width: '100%' }}>
                    {questions.map((q, qi) => (
                        <Card key={qi} title={<Text>{t('quiz.question')} {qi + 1}</Text>} extra={<Space>
                            <Button icon={<ArrowUpOutlined />} disabled={qi === 0} onClick={() => moveQuestion(qi, -1)} />
                            <Button icon={<ArrowDownOutlined />} disabled={qi === questions.length - 1} onClick={() => moveQuestion(qi, 1)} />
                            <Button danger icon={<DeleteOutlined />} onClick={() => removeQuestion(qi)} />
                        </Space>}>
                            <Space direction="vertical" style={{ width: '100%' }}>
                                <TextArea value={q.question} onChange={e => updateQuestion(qi, { question: e.target.value })} placeholder={t('quiz.questionText')} rows={3} />

                                <div>
                                    <Text strong>{t('quiz.choices')}</Text>
                                    <div className="mt-2">
                                        <Radio.Group value={q.answer_index} onChange={e => updateQuestion(qi, { answer_index: e.target.value })}>
                                            <Space direction="vertical" style={{ width: '100%' }}>
                                                {(q.choices || []).map((choice, ci) => (
                                                    <div key={ci} className="flex items-center gap-2">
                                                        <Radio value={ci} />
                                                        <TextArea
                                                            className='w-96'
                                                            value={choice} onChange={e => {
                                                                const newChoices = [...(q.choices || [])]
                                                                newChoices[ci] = e.target.value
                                                                updateQuestion(qi, { choices: newChoices })
                                                            }} placeholder={`${t('quiz.choice')} ${ci + 1}`} />
                                                        <Button danger onClick={() => removeChoice(qi, ci)}>{t('quiz.remove')}</Button>
                                                    </div>
                                                ))}
                                            </Space>
                                        </Radio.Group>
                                        <Button className="mt-2" icon={<PlusOutlined />} onClick={() => addChoice(qi)}>{t('quiz.addChoice')}</Button>
                                    </div>
                                </div>

                                <Text strong>{t('quiz.rationale')}</Text>
                                <TextArea value={q.rationale} onChange={e => updateQuestion(qi, { rationale: e.target.value })} rows={2} />

                                <Text strong>{t('quiz.bloomLevel')}</Text>
                                <div>
                                    <Select
                                        value={q.bloom_level || undefined}
                                        onChange={val => updateQuestion(qi, { bloom_level: val })}
                                        options={bloomOptions}
                                        style={{ minWidth: 200 }}
                                        allowClear
                                    />
                                </div>
                            </Space>
                        </Card>
                    ))}
                </Space>

                <div className="mt-4">
                    <Button icon={<PlusOutlined />} onClick={addQuestion}>{t('quiz.addQuestion')}</Button>
                </div>
            </div>
        </div>
    )
}
