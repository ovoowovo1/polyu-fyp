import React, { useEffect, useState } from 'react'
import { message } from 'antd'
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
import {
    QuizCompletedView,
    QuizEmptyView,
    QuizLoadingView,
    QuizNavigation,
    QuizQuestionView,
} from './QuizReaderViews.jsx'

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
        return <QuizLoadingView />
    }

    if (isFinished) {
        const score = calculateScore()
        return (
            <QuizCompletedView
                onClose={onClose}
                score={score}
                feedbackLoading={feedbackLoading}
                feedbackError={feedbackError}
                feedbackText={feedbackText}
                onRetryFeedback={() => requestFeedback(finalScore || calculateScore())}
                onRetake={handleRetake}
            />
        )
    }

    if (!currentQuestion) {
        return <QuizEmptyView />
    }

    const isCorrect = selectedAnswer === currentQuestion.answer_index

    return (
        <div className="flex flex-col h-full">
            <QuizQuestionView
                quizName={quizName}
                currentIndex={currentIndex}
                totalQuestions={questions.length}
                currentQuestion={currentQuestion}
                selectedAnswer={selectedAnswer}
                showResult={showResult}
                isCorrect={isCorrect}
                onAnswerSelect={handleAnswerSelect}
                onClose={onClose}
                onExplainClick={handleExplainClick}
            />

            <QuizNavigation
                currentIndex={currentIndex}
                totalQuestions={questions.length}
                showResult={showResult}
                onPrevious={handlePrevious}
                onSubmitAnswer={handleSubmitAnswer}
                onNext={handleNext}
            />
        </div>
    )
}
