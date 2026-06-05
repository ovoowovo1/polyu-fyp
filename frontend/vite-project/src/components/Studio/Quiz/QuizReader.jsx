import React, { useEffect, useState } from 'react'
import { Button, Card, message, Progress, Space, Spin, Typography } from 'antd'
import { ArrowLeftOutlined, ArrowRightOutlined, CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons'
import { generateQuizFeedback, getQuizById, submitQuiz } from '../../../api/quiz'
import {
    buildExplanationPrompt,
    buildQuizAnswerPayload,
    buildQuizFeedbackPayload,
    calculateQuizScore,
    createEmptyAnswers,
    nextQuizNavigationState,
    previousQuizNavigationState,
    storedAnswerAt,
} from './quizReaderLogic.js'

const { Title, Text, Paragraph } = Typography

const USE_MOCK_FEEDBACK = false
const MOCK_FEEDBACK_TEXT = `Great job on the quiz with a solid 7/10! You showed strong understanding in evaluating database concepts. Focus a bit more on 'create' tasks, particularly practicing SQL DDL commands for defining tables and constraints. Review the functions of core DBMS components like the buffer manager to strengthen your design application skills.`

function dispatchChatAutofill(text) {
    try {
        window.dispatchEvent(new CustomEvent('autofill_chat', { detail: { text, send: true } }))
    } catch {
        const event = document.createEvent('CustomEvent')
        event.initCustomEvent('autofill_chat', true, true, { text, send: true })
        window.dispatchEvent(event)
    }
}

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

    useEffect(() => {
        const loadQuiz = async () => {
            setLoading(true)
            try {
                const response = await getQuizById(quizId)
                const loadedQuestions = response.data.quiz.questions || []
                setQuestions(loadedQuestions)
                setUserAnswers(createEmptyAnswers(loadedQuestions.length))
            } catch (error) {
                console.error('Load quiz failed:', error)
                message.error('Failed to load quiz. Please try again later.')
            } finally {
                setLoading(false)
            }
        }
        loadQuiz()
    }, [quizId])

    const currentQuestion = questions[currentIndex]
    const calculateScore = () => calculateQuizScore(questions, userAnswers)

    const requestFeedback = async (score) => {
        if (!questions.length) return

        setFeedbackLoading(true)
        setFeedbackError(null)
        try {
            if (USE_MOCK_FEEDBACK) {
                setFeedbackText(MOCK_FEEDBACK_TEXT)
                return
            }
            const payload = buildQuizFeedbackPayload({ quizName, questions, userAnswers, score })
            const response = await generateQuizFeedback(quizId, payload)
            const text = response?.data?.feedback || response?.data?.message || ''
            setFeedbackText(text || 'AI feedback not available yet.')
        } catch (error) {
            console.error('Generate quiz feedback failed:', error)
            setFeedbackError('Failed to generate AI feedback. Please try again.')
        } finally {
            setFeedbackLoading(false)
        }
    }

    useEffect(() => {
        if (!isFinished) return

        const score = calculateScore()
        setFinalScore(score)

        submitQuiz(quizId, {
            answers: buildQuizAnswerPayload(userAnswers),
            score: score.correct,
            total_questions: score.total,
        }).then(() => {
            message.success('Quiz result submitted.')
        }).catch((error) => {
            console.error('Submit quiz result failed:', error)
        })

        requestFeedback(score)
    }, [isFinished])

    const handleAnswerSelect = (answerIndex) => {
        if (!showResult) {
            setSelectedAnswer(answerIndex)
        }
    }

    const handleSubmitAnswer = () => {
        if (selectedAnswer === null) {
            message.warning('Please select an answer before submitting.')
            return
        }

        const nextAnswers = [...userAnswers]
        nextAnswers[currentIndex] = selectedAnswer
        setUserAnswers(nextAnswers)
        setShowResult(true)
    }

    const handleNext = () => {
        const nextState = nextQuizNavigationState({ currentIndex, questions, userAnswers })
        if (nextState.isFinished) {
            setIsFinished(true)
            return
        }
        setCurrentIndex(nextState.currentIndex)
        setSelectedAnswer(nextState.selectedAnswer)
        setShowResult(nextState.showResult)
    }

    const handlePrevious = () => {
        const previousState = previousQuizNavigationState({ currentIndex, userAnswers })
        setCurrentIndex(previousState.currentIndex)
        setSelectedAnswer(previousState.selectedAnswer)
        setShowResult(previousState.showResult)
    }

    const handleExplainClick = () => {
        if (!currentQuestion) return

        const userAnswerIndex = storedAnswerAt(userAnswers, currentIndex, selectedAnswer)
        if (userAnswerIndex === null || userAnswerIndex === undefined) {
            message.warning('Please select an answer before asking for an explanation.')
            return
        }

        const prompt = buildExplanationPrompt({ question: currentQuestion, userAnswerIndex })
        dispatchChatAutofill(prompt)

        if (navigator.clipboard?.writeText) {
            navigator.clipboard.writeText(prompt).then(() => {
                message.success('Autofilled the chat box and copied the prompt to clipboard.')
            }).catch(() => {
                message.success('Autofilled the chat box.')
            })
        } else {
            message.success('Autofilled the chat box.')
        }
    }

    const handleRetake = () => {
        setCurrentIndex(0)
        setUserAnswers(createEmptyAnswers(questions.length))
        setSelectedAnswer(null)
        setShowResult(false)
        setIsFinished(false)
        setFeedbackText('')
        setFeedbackError(null)
        setFeedbackLoading(false)
        setFinalScore(null)
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
                    <Button type="text" icon={<ArrowLeftOutlined />} onClick={onClose}>
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
                            '100%': '#52c41a',
                        }}
                    />

                    <Space className="mt-8">
                        <Button size="large" onClick={onClose}>
                            Back to List
                        </Button>
                        <Button size="large" type="primary" onClick={handleRetake}>
                            Retake Quiz
                        </Button>
                    </Space>

                    <div className="w-full mt-6">
                        <div className="flex items-center justify-between mt-4 mb-2">
                            <Title level={4} className="m-0">AI Feedback</Title>
                        </div>
                        {feedbackLoading && (
                            <div className="flex items-center gap-2">
                                <Spin size="small" />
                                <Text>Generating personalized feedback...</Text>
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
            </div>
        )
    }

    if (!currentQuestion) {
        return (
            <div className="flex items-center justify-center h-full">
                <Text type="secondary">No questions available.</Text>
            </div>
        )
    }

    const isCorrect = selectedAnswer === currentQuestion.answer_index

    return (
        <div className="flex flex-col h-full">
            <div className="flex items-center justify-between p-4 border-b">
                <div className="flex items-center gap-2">
                    <Button type="text" icon={<ArrowLeftOutlined />} onClick={onClose} />
                    <Title level={5} className="m-0">{quizName || 'Quiz'}</Title>
                </div>
                <Text className="text-gray-500">
                    {currentIndex + 1} / {questions.length}
                </Text>
            </div>

            <Progress
                percent={Math.round(((currentIndex + 1) / questions.length) * 100)}
                showInfo={false}
                strokeColor="#52c41a"
            />

            <div className="flex-1 overflow-y-auto p-6">
                <Card className="mb-4">
                    <Title level={4}>{currentQuestion.question}</Title>
                </Card>

                <Space direction="vertical" className="w-full" size="middle">
                    {currentQuestion.choices.map((choice, index) => {
                        let className = 'w-full text-left p-4 rounded-lg border-2 transition-all'

                        if (showResult) {
                            if (index === currentQuestion.answer_index) {
                                className += ' border-green-500 bg-green-50'
                            } else if (index === selectedAnswer && selectedAnswer !== currentQuestion.answer_index) {
                                className += ' border-red-500 bg-red-50'
                            } else {
                                className += ' border-gray-200'
                            }
                        } else if (index === selectedAnswer) {
                            className += ' border-blue-500 bg-blue-50'
                        } else {
                            className += ' border-gray-300 hover:border-blue-300'
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

                {showResult && (
                    <>
                        <Card className="mt-4" style={{ backgroundColor: isCorrect ? '#f6ffed' : '#fff2e8' }}>
                            <Space direction="vertical" size="small">
                                <Text strong className={isCorrect ? 'text-green-600' : 'text-orange-600'}>
                                    {isCorrect ? 'Correct!' : 'Incorrect'}
                                </Text>
                                <Paragraph className="mb-0">
                                    {currentQuestion.rationale}
                                </Paragraph>
                            </Space>
                        </Card>

                        <Button className="mt-3" onClick={handleExplainClick}>
                            Explain
                        </Button>
                    </>
                )}
            </div>

            <div className="flex justify-between items-center p-4 border-t">
                <Button onClick={handlePrevious} disabled={currentIndex === 0} icon={<ArrowLeftOutlined />}>
                    Previous
                </Button>

                {!showResult ? (
                    <Button type="primary" onClick={handleSubmitAnswer}>
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
