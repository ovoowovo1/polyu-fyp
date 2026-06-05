import React, { useState } from 'react'
import { Card, InputNumber, message, Modal, Radio, Typography } from 'antd'
import { useSelector } from 'react-redux'
import { generateQuiz } from '../../../api/quiz'

const { Title } = Typography

export default function QuizCard({ onQuizGenerated }) {
    const { selectedFileIds } = useSelector((state) => state.documents)
    const [loading, setLoading] = useState(false)
    const [open, setOpen] = useState(false)
    const [difficulty, setDifficulty] = useState('medium')
    const [numQuestions, setNumQuestions] = useState(10)

    const handleGenerateQuiz = async (nextDifficulty = 'medium', nextNumQuestions = 10) => {
        if (!selectedFileIds?.length) {
            message.warning('Please select at least one file to generate quiz')
            return
        }

        setLoading(true)
        try {
            const response = await generateQuiz(selectedFileIds, {
                difficulty: nextDifficulty,
                numQuestions: nextNumQuestions,
            })
            message.success(`Successfully generated ${response.data.questions.length} quiz questions!`)
            onQuizGenerated?.()
        } catch (error) {
            console.error('Generate quiz failed:', error)
            message.error(error.response?.data?.detail || 'Generate Quiz Failed, Please try again later')
        } finally {
            setLoading(false)
        }
    }

    const handleOk = () => {
        setOpen(false)
        handleGenerateQuiz(difficulty, numQuestions)
    }

    return (
        <>
            <Card
                className="bg-green-100 hover:bg-green-200 cursor-pointer"
                styles={{ body: { padding: '0.5rem', backgroundColor: 'transparent' } }}
                onClick={() => handleGenerateQuiz()}
                loading={loading}
            >
                <div className="flex justify-between">
                    <span className="material-symbols-outlined text-lime-600">quiz</span>
                    <span
                        className="material-symbols-outlined text-lime-600"
                        onClick={(event) => {
                            event.stopPropagation()
                            setOpen(true)
                        }}
                    >
                        edit
                    </span>
                </div>
                <Title level={5} style={{ color: '#65a30d', marginTop: '1rem' }}>
                    Quiz
                </Title>
            </Card>

            <Modal
                title="Custom Quiz"
                open={open}
                onOk={handleOk}
                confirmLoading={loading}
                onCancel={() => setOpen(false)}
                cancelText="Cancel"
                okText="Generate"
            >
                <div className="grid grid-cols-2 grid-rows-2 gap-1">
                    <div>Number of Questions</div>
                    <div>Difficulty</div>
                    <div>
                        <InputNumber
                            value={numQuestions}
                            min={1}
                            max={100}
                            onChange={(value) => setNumQuestions(value || 1)}
                        />
                    </div>
                    <div>
                        <Radio.Group
                            optionType="button"
                            buttonStyle="solid"
                            value={difficulty}
                            options={[
                                { label: 'Easy', value: 'easy' },
                                { label: 'Medium', value: 'medium' },
                                { label: 'Difficult', value: 'difficult' },
                            ]}
                            onChange={(event) => setDifficulty(event.target.value)}
                        />
                    </div>
                </div>
            </Modal>
        </>
    )
}
