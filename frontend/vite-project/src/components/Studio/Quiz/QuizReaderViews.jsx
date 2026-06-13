import React from 'react'
import { Button, Card, Progress, Space, Spin, Typography } from 'antd'
import { ArrowLeftOutlined, ArrowRightOutlined, CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons'

const { Title, Text, Paragraph } = Typography

export function QuizLoadingView() {
    return (
        <div className="flex items-center justify-center h-full">
            <Spin size="large" />
        </div>
    )
}

export function QuizEmptyView() {
    return (
        <div className="flex items-center justify-center h-full">
            <Text type="secondary">No questions available.</Text>
        </div>
    )
}

export function QuizCompletedView({
    onClose,
    score,
    feedbackLoading,
    feedbackError,
    feedbackText,
    onRetryFeedback,
    onRetake,
}) {
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
                    <Button size="large" type="primary" onClick={onRetake}>
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
                            <Button onClick={onRetryFeedback}>Try again</Button>
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

export function QuizQuestionView({
    quizName,
    currentIndex,
    totalQuestions,
    currentQuestion,
    selectedAnswer,
    showResult,
    isCorrect,
    onAnswerSelect,
    onClose,
    onExplainClick,
}) {
    return (
        <>
            <div className="flex items-center justify-between p-4 border-b">
                <div className="flex items-center gap-2">
                    <Button type="text" icon={<ArrowLeftOutlined />} onClick={onClose} />
                    <Title level={5} className="m-0">{quizName || 'Quiz'}</Title>
                </div>
                <Text className="text-gray-500">
                    {currentIndex + 1} / {totalQuestions}
                </Text>
            </div>

            <Progress
                percent={Math.round(((currentIndex + 1) / totalQuestions) * 100)}
                showInfo={false}
                strokeColor="#52c41a"
            />

            <div className="flex-1 overflow-y-auto p-6">
                <Card className="mb-4">
                    <Title level={4}>{currentQuestion.question}</Title>
                </Card>

                <Space direction="vertical" className="w-full" size="middle">
                    {currentQuestion.choices.map((choice, index) => (
                        <AnswerButton
                            key={index}
                            choice={choice}
                            index={index}
                            correctIndex={currentQuestion.answer_index}
                            selectedAnswer={selectedAnswer}
                            showResult={showResult}
                            onAnswerSelect={onAnswerSelect}
                        />
                    ))}
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

                        <Button className="mt-3" onClick={onExplainClick}>
                            Explain
                        </Button>
                    </>
                )}
            </div>
        </>
    )
}

export function QuizNavigation({
    currentIndex,
    totalQuestions,
    showResult,
    onPrevious,
    onSubmitAnswer,
    onNext,
}) {
    return (
        <div className="flex justify-between items-center p-4 border-t">
            <Button onClick={onPrevious} disabled={currentIndex === 0} icon={<ArrowLeftOutlined />}>
                Previous
            </Button>

            {!showResult ? (
                <Button type="primary" onClick={onSubmitAnswer}>
                    Submit Answer
                </Button>
            ) : (
                <Button
                    type="primary"
                    onClick={onNext}
                    icon={currentIndex === totalQuestions - 1 ? undefined : <ArrowRightOutlined />}
                >
                    {currentIndex === totalQuestions - 1 ? 'Finish Quiz' : 'Next Question'}
                </Button>
            )}
        </div>
    )
}

function AnswerButton({
    choice,
    index,
    correctIndex,
    selectedAnswer,
    showResult,
    onAnswerSelect,
}) {
    let className = 'w-full text-left p-4 rounded-lg border-2 transition-all'

    if (showResult) {
        if (index === correctIndex) {
            className += ' border-green-500 bg-green-50'
        } else if (index === selectedAnswer && selectedAnswer !== correctIndex) {
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
            className={className}
            onClick={() => onAnswerSelect(index)}
            disabled={showResult}
        >
            <div className="flex items-center justify-between">
                <Text>{choice}</Text>
                {showResult && index === correctIndex && (
                    <CheckCircleOutlined className="text-green-600 text-xl" />
                )}
                {showResult && index === selectedAnswer && selectedAnswer !== correctIndex && (
                    <CloseCircleOutlined className="text-red-600 text-xl" />
                )}
            </div>
        </button>
    )
}
