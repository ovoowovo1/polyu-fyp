import React, { useState, useEffect } from 'react'
import { Button, Radio, Typography, Space, Progress, Card, message, Spin } from 'antd'
import { ArrowLeftOutlined, ArrowRightOutlined, CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons'
import { getQuizById, submitQuiz, generateQuizFeedback } from '../../api/quiz'

const { Title, Text, Paragraph } = Typography

// Toggle to bypass API cost and show fixed sample feedback
const USE_MOCK_FEEDBACK = false
const MOCK_FEEDBACK_TEXT = `Great job on the quiz with a solid 7/10! You showed strong understanding in evaluating database concepts. Focus a bit more on 'create' tasks, particularly practicing SQL DDL commands for defining tables and constraints. Review the functions of core DBMS components like the buffer manager to strengthen your design application skills.`

export default function QuizReader({ quizId, quizName, onClose }) {
    const [loading, setLoading] = useState(true)
    const [questions, setQuestions] = useState([])
    const [currentIndex, setCurrentIndex] = useState(0)
    const [selectedAnswer, setSelectedAnswer] = useState(null)
    const [showResult, setShowResult] = useState(false)
    const [userAnswers, setUserAnswers] = useState([])
    const [isFinished, setIsFinished] = useState(false)
    const [feedbackLoading, setFeedbackLoading] = useState(false)
    const [feedbackText, setFeedbackText] = useState('')
    const [feedbackError, setFeedbackError] = useState(null)
    const [finalScore, setFinalScore] = useState(null)

    // 加載測驗數據
    useEffect(() => {
        const loadQuiz = async () => {
            setLoading(true)
            try {
                const response = await getQuizById(quizId)
                setQuestions(response.data.quiz.questions || [])
                setUserAnswers(new Array(response.data.quiz.questions.length).fill(null))
            } catch (error) {
                console.error('加載測驗失敗:', error)
                message.error('Failed to load quiz. Please try again later.')
            } finally {
                setLoading(false)
            }
        }
        loadQuiz()
    }, [quizId])

    const currentQuestion = questions[currentIndex]

    const handleAnswerSelect = (answerIndex) => {
        if (showResult) return // 已經顯示結果就不能再選擇
        setSelectedAnswer(answerIndex)
    }

    const handleSubmitAnswer = () => {
        if (selectedAnswer === null) {
            message.warning('Please select an answer before submitting.')
            return
        }

        // 保存答案
        const newAnswers = [...userAnswers]
        newAnswers[currentIndex] = selectedAnswer
        setUserAnswers(newAnswers)

        // 顯示結果
        setShowResult(true)
    }

    const handleNext = () => {
        if (currentIndex < questions.length - 1) {
            // 下一題
            setCurrentIndex(currentIndex + 1)
            setSelectedAnswer(userAnswers[currentIndex + 1])
            setShowResult(userAnswers[currentIndex + 1] !== null)
        } else {
            // 完成測驗
            setIsFinished(true)
        }
    }

    const handlePrevious = () => {
        if (currentIndex > 0) {
            setCurrentIndex(currentIndex - 1)
            setSelectedAnswer(userAnswers[currentIndex - 1])
            setShowResult(userAnswers[currentIndex - 1] !== null)
        }
    }

    const calculateScore = () => {
        let correct = 0
        questions.forEach((question, index) => {
            if (userAnswers[index] === question.answer_index) {
                correct++
            }
        })
        return { correct, total: questions.length, percentage: Math.round((correct / questions.length) * 100) }
    }

    // 整理成 AI 回饋所需的摘要 payload
    const buildFeedbackPayload = (score) => {
        const bloomStats = {}

        questions.forEach((q, idx) => {
            const key = q.bloom_level || 'general'
            if (!bloomStats[key]) {
                bloomStats[key] = { correct: 0, total: 0 }
            }
            bloomStats[key].total += 1
            if (userAnswers[idx] === q.answer_index) {
                bloomStats[key].correct += 1
            }
        })

        const bloom_summary = Object.entries(bloomStats).map(([level, stats]) => ({
            level,
            correct: stats.correct,
            total: stats.total,
            accuracy: stats.total ? Math.round((stats.correct / stats.total) * 100) : 0
        }))

        const questionsSummary = questions.map((q, idx) => ({
            question: q.question,
            choices: q.choices,
            correct_answer_index: q.answer_index,
            user_answer_index: userAnswers[idx],
            bloom_level: q.bloom_level || 'general',
            rationale: q.rationale
        }))

        return {
            quiz_name: quizName,
            score: score.correct,
            total_questions: score.total,
            percentage: score.percentage,
            bloom_summary,
            questions: questionsSummary
        }
    }

    const requestFeedback = async (score) => {
        if (!questions || !questions.length) {
            return
        }
        setFeedbackLoading(true)
        setFeedbackError(null)
        try {
            if (USE_MOCK_FEEDBACK) {
                setFeedbackText(MOCK_FEEDBACK_TEXT)
                return
            }
            const payload = buildFeedbackPayload(score)
            const res = await generateQuizFeedback(quizId, payload)
            const text = res?.data?.feedback || res?.data?.message || ''
            setFeedbackText(text || 'AI feedback not available yet.')
        } catch (error) {
            console.error('Generate feedback failed', error)
            setFeedbackError('Failed to generate AI feedback. Please try again.')
        } finally {
            setFeedbackLoading(false)
        }
    }

    // Auto-submit when finished
    useEffect(() => {
        if (isFinished) {
            const score = calculateScore()
            setFinalScore(score)
            const answersPayload = userAnswers.map((ans, idx) => ({
                question_index: idx,
                answer_index: ans
            }))

            submitQuiz(quizId, {
                answers: answersPayload,
                score: score.correct,
                total_questions: score.total
            }).then(() => {
                message.success('Quiz result submitted.')
            }).catch(err => {
                console.error('Submit failed', err)
            })

            requestFeedback(score)
        }
    }, [isFinished])

    // 將目前題目、使用者選擇與正確答案組成要自動填入聊天欄的文字，並廣播事件
    const handleExplainClick = () => {
        if (!currentQuestion) return

        // 優先使用已保存的答案，否則使用當前選擇（selectedAnswer）
        const userIdx = (userAnswers && userAnswers[currentIndex] !== null && userAnswers[currentIndex] !== undefined)
            ? userAnswers[currentIndex]
            : selectedAnswer

        if (userIdx === null || userIdx === undefined) {
            message.warning('尚未作答，無法產生說明')
            return
        }

        const toLetter = (i) => String.fromCharCode(65 + i)
        const userChoiceText = `${toLetter(userIdx)}. ${currentQuestion.choices[userIdx]}`
        const correctIdx = currentQuestion.answer_index
        const correctChoiceText = `${toLetter(correctIdx)}. ${currentQuestion.choices[correctIdx]}`

        const isCorrect = userIdx === correctIdx

        const autoText = `When I took a quiz on this textbook, I saw this question:"${currentQuestion.question}"\n\nI chose the following answer:" ${userChoiceText}"\n\n` +
            (isCorrect ? `That answer is correct.` : `That answer is incorrect. The correct answer is " ${correctChoiceText} "`) +
            `\n\nHelp me understand the reason why I got it wrong.`

        // 發送自定事件給 Chat 元件
        try {
            window.dispatchEvent(new CustomEvent('autofill_chat', { detail: { text: autoText, send: true } }))
        } catch (e) {
            // fallback for older browsers
            const evt = document.createEvent('CustomEvent')
            evt.initCustomEvent('autofill_chat', true, true, { text: autoText, send: true })
            window.dispatchEvent(evt)
        }

        // 同時嘗試複製到剪貼簿並顯示提示
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(autoText).then(() => {
                message.success('Already autofilled the explanation into the chat box and copied to clipboard');
            }).catch(() => {
                message.success('Failed to copy to clipboard, but already autofilled the explanation into the chat box');
            })
        } else {
            message.success('Already autofilled the explanation into the chat box');
        }
    }

    if (loading) {
        return (
            <div className="flex items-center justify-center h-full">
                <Spin size="large" />
            </div>
        )
    }

    if (isFinished) {
        const score = calculateScore()
        return (
            <div className="flex flex-col h-full p-6">
                <div className="flex items-center mb-6">
                    <Button
                        type="text"
                        icon={<ArrowLeftOutlined />}
                        onClick={onClose}
                    >
                        Back
                    </Button>
                </div>

                <div className="flex-1 flex flex-col items-center justify-center overflow-y-auto">
                    <div className="text-center mb-8">
                        <Title level={2}>Quiz Completed!</Title>
                        <Title level={1} className="text-green-600">
                            {score.correct}/{score.total}
                        </Title>
                        <Title level={3} className="text-gray-600">
                            {score.percentage}%
                        </Title>
                    </div>

                    <Progress
                        type="circle"
                        percent={score.percentage}
                        size={200}
                        strokeColor={{
                            '0%': '#87d068',
                            '100%': '#52c41a'
                        }}
                    />

                    <Space className="mt-8">
                        <Button size="large" onClick={onClose}>
                            Back to List
                        </Button>
                        <Button
                            size="large"
                            type="primary"
                            onClick={() => {
                                setCurrentIndex(0)
                                setUserAnswers(new Array(questions.length).fill(null))
                                setSelectedAnswer(null)
                                setShowResult(false)
                                setIsFinished(false)
                                setFeedbackText('')
                                setFeedbackError(null)
                                setFeedbackLoading(false)
                                setFinalScore(null)
                            }}
                        >
                            Retake Quiz
                        </Button>
                    </Space>


                        <div className="flex items-center justify-between mt-4 mb-2">
                            <Title level={4} className="m-0">AI Feedback</Title>
                        </div>
                        {feedbackLoading && (
                            <div className="flex items-center gap-2">
                                <Spin size="small" />
                                <Text>Generating personalized feedback…</Text>
                            </div>
                        )}
                        {!feedbackLoading && feedbackError && (
                            <Space direction="vertical" size="small">
                                <Text type="danger">{feedbackError}</Text>
                                <Button onClick={() => requestFeedback(finalScore || calculateScore())}>Try again</Button>
                            </Space>
                        )}
                        {!feedbackLoading && !feedbackError && (
                            <Paragraph className="whitespace-pre-line mb-0">
                                {feedbackText || 'AI feedback will appear here after generation.'}
                            </Paragraph>
                        )}

                </div>
            </div>
        )
    }

    const isCorrect = selectedAnswer === currentQuestion.answer_index

    return (
        <div className="flex flex-col h-full">
            {/* Header */}
            <div className="flex items-center justify-between p-4 border-b">
                <div className="flex items-center gap-2">
                    <Button
                        type="text"
                        icon={<ArrowLeftOutlined />}
                        onClick={onClose}
                    />
                    <Title level={5} className="m-0">{quizName || 'Quiz'}</Title>
                </div>
                <Text className="text-gray-500">
                    {currentIndex + 1} / {questions.length}
                </Text>
            </div>

            {/* Progress Bar */}
            <Progress
                percent={Math.round(((currentIndex + 1) / questions.length) * 100)}
                showInfo={false}
                strokeColor="#52c41a"
            />

            {/* Question Content */}
            <div className="flex-1 overflow-y-auto p-6">
                <Card className="mb-4">
                    <Title level={4}>{currentQuestion.question}</Title>
                </Card>

                <Space direction="vertical" className="w-full" size="middle">
                    {currentQuestion.choices.map((choice, index) => {
                        let className = "w-full text-left p-4 rounded-lg border-2 transition-all"

                        if (showResult) {
                            if (index === currentQuestion.answer_index) {
                                className += " border-green-500 bg-green-50"
                            } else if (index === selectedAnswer && selectedAnswer !== currentQuestion.answer_index) {
                                className += " border-red-500 bg-red-50"
                            } else {
                                className += " border-gray-200"
                            }
                        } else {
                            if (index === selectedAnswer) {
                                className += " border-blue-500 bg-blue-50"
                            } else {
                                className += " border-gray-300 hover:border-blue-300"
                            }
                        }

                        return (
                            <button
                                key={index}
                                className={className}
                                onClick={() => handleAnswerSelect(index)}
                                disabled={showResult}
                            >
                                <div className="flex items-center justify-between">
                                    <Text>{choice}</Text>
                                    {showResult && index === currentQuestion.answer_index && (
                                        <CheckCircleOutlined className="text-green-600 text-xl" />
                                    )}
                                    {showResult && index === selectedAnswer && selectedAnswer !== currentQuestion.answer_index && (
                                        <CloseCircleOutlined className="text-red-600 text-xl" />
                                    )}
                                </div>
                            </button>
                        )
                    })}
                </Space>

                {/* Rationale */}
                {showResult && (
                    <>
                        <Card className="mt-4" style={{ backgroundColor: isCorrect ? '#f6ffed' : '#fff2e8' }}>
                            <Space direction="vertical" size="small">
                                <Text strong className={isCorrect ? 'text-green-600' : 'text-orange-600'}>
                                    {isCorrect ? '✓ Correct!' : '✗ Incorrect'}
                                </Text>
                                <Paragraph className="mb-0">
                                    <Text strong></Text> {currentQuestion.rationale}
                                </Paragraph>
                            </Space>
                        </Card>

                        <Button onClick={handleExplainClick}>
                            Explain
                        </Button>
                    </>
                )}
            </div>

            {/* Footer Navigation */}
            <div className="flex justify-between items-center p-4 border-t">
                <Button
                    onClick={handlePrevious}
                    disabled={currentIndex === 0}
                    icon={<ArrowLeftOutlined />}
                >
                    Previous
                </Button>

                {!showResult ? (
                    <Button
                        type="primary"
                        onClick={handleSubmitAnswer}
                    >
                        Submit Answer
                    </Button>
                ) : (
                    <Button
                        type="primary"
                        onClick={handleNext}
                        icon={currentIndex === questions.length - 1 ? undefined : <ArrowRightOutlined />}
                    >
                        {currentIndex === questions.length - 1 ? 'Finish Quiz' : 'Next Question'}
                    </Button>
                )}
            </div>
        </div>
    )
}
