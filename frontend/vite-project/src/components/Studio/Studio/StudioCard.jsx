import React, { memo, useEffect, useRef, useState } from 'react'
import { Button, Card, Divider, List, message, Tag, Typography } from 'antd'
import { useDispatch, useSelector } from 'react-redux'
import { useTranslation } from 'react-i18next'
import { DeleteOutlined, DownloadOutlined, EditOutlined, EyeOutlined, MenuFoldOutlined, MenuUnfoldOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'

import QuizCard from '../Quiz/QuizCard'
import ExamGeneratorCard from '../Exam/ExamGeneratorCard'
import QuizReader from '../Quiz/QuizReader'
import CollapsedIcon from './CollapsedIcon'
import QuizResultList from '../Quiz/QuizResultList'

import { setQuizReaderOpen, toggleStudioCardCollapse } from '../../../redux/studioSlice'
import { deleteQuiz, getAllQuizzes } from '../../../api/quiz'
import { deleteExam, downloadExamPdf, getExamList } from '../../../api/exam'
import { getCurrentUser } from '../../../api/auth'
import {
    examPdfFilename,
    formatStudioDate,
    isCanceledRequest,
    mergeStudioItems,
} from './studioCardLogic'

const { Title } = Typography

function StudioCard({ widthSize = null }) {
    const { t } = useTranslation()
    const dispatch = useDispatch()
    const navigate = useNavigate()
    const { isStudioCardCollapsed } = useSelector((state) => state.studio)
    const { currentClassId } = useSelector((state) => state.documents)

    const user = getCurrentUser()
    const isTeacher = user?.role === 'teacher'

    const [listLoading, setListLoading] = useState(false)
    const [quizzes, setQuizzes] = useState([])
    const [exams, setExams] = useState([])
    const [selectedQuiz, setSelectedQuiz] = useState(null)
    const [resultModalVisible, setResultModalVisible] = useState(false)
    const [resultQuizId, setResultQuizId] = useState(null)

    const lastRequestedClassRef = useRef(null)
    const controllerRef = useRef(null)

    const loadQuizzesAndExams = async () => {
        if (!currentClassId) {
            setQuizzes([])
            setExams([])
            return
        }

        if (lastRequestedClassRef.current === currentClassId && listLoading) {
            return
        }

        if (controllerRef.current) {
            try {
                controllerRef.current.abort()
            } catch {
                // Ignore abort cleanup errors.
            }
            controllerRef.current = null
        }

        const controller = new AbortController()
        controllerRef.current = controller
        setListLoading(true)
        lastRequestedClassRef.current = currentClassId

        try {
            const [quizRes, examRes] = await Promise.all([
                getAllQuizzes(currentClassId, { signal: controller.signal }),
                getExamList(currentClassId),
            ])
            setQuizzes(quizRes.data?.quizzes || [])
            setExams(examRes.data?.exams || [])
        } catch (error) {
            if (!isCanceledRequest(error)) {
                console.error('Load Studio list failed:', error)
                message.error(t('studio.quizDeleted'))
            }
        } finally {
            setListLoading(false)
        }
    }

    useEffect(() => {
        loadQuizzesAndExams()
    }, [currentClassId])

    const stopItemClick = (event) => {
        if (event?.stopPropagation) event.stopPropagation()
    }

    const handleDeleteQuiz = async (quizId, event) => {
        stopItemClick(event)
        try {
            await deleteQuiz(quizId)
            message.success(t('studio.quizDeleted'))
            loadQuizzesAndExams()
        } catch (error) {
            console.error('Delete quiz failed:', error)
            message.error(t('studio.deleteQuizFailed'))
        }
    }

    const handleDeleteExam = async (examId, event) => {
        stopItemClick(event)
        try {
            await deleteExam(examId)
            message.success(t('exam.studio.examDeleted'))
            loadQuizzesAndExams()
        } catch (error) {
            console.error('Delete exam failed:', error)
            message.error(t('exam.studio.deleteExamFailed'))
        }
    }

    const handleViewResults = (quizId, event) => {
        stopItemClick(event)
        setResultQuizId(quizId)
        setResultModalVisible(true)
    }

    const handleEditQuiz = (quizId, event) => {
        stopItemClick(event)
        navigate(`/quiz/edit/${quizId}`)
    }

    const handleQuizClick = (quiz) => {
        setSelectedQuiz(quiz)
        dispatch(setQuizReaderOpen(true))
    }

    const handleExamClick = (exam) => {
        navigate(isTeacher ? `/exam/view/${exam.id}` : `/exam/take/${exam.id}`)
    }

    const handleEditExam = (classId, event) => {
        stopItemClick(event)
        navigate(`/exam/list/${classId}`)
    }

    const handleDownloadPdfExam = async (examId, event) => {
        stopItemClick(event)
        try {
            message.loading(t('exam.generator.downloadPdfLoading'), 0)
            await downloadExamPdf(examId, examPdfFilename(examId, exams))
            message.destroy()
            message.success(t('exam.generator.downloadPdfSuccess'))
        } catch (error) {
            message.destroy()
            console.error('Exam PDF download failed:', error)
            message.error(t('exam.generator.downloadPdfFailed'))
        }
    }

    const handleCloseQuiz = () => {
        setSelectedQuiz(null)
        dispatch(setQuizReaderOpen(false))
    }

    const renderItemActions = (item, isExam) => {
        if (isExam) {
            return (
                <>
                    {isTeacher && (
                        <Button
                            type="text"
                            size="small"
                            icon={<DownloadOutlined />}
                            title={t('exam.studio.downloadPdf')}
                            onClick={(event) => handleDownloadPdfExam(item.id, event)}
                        />
                    )}
                    <Button
                        type="text"
                        size="small"
                        icon={<EyeOutlined />}
                        title={t('exam.studio.viewSubmissions')}
                        onClick={(event) => {
                            stopItemClick(event)
                            navigate(`/exam/grade/${item.id}`)
                        }}
                    />
                    {isTeacher && (
                        <>
                            <Button
                                type="text"
                                size="small"
                                icon={<EditOutlined />}
                                onClick={(event) => handleEditExam(currentClassId, event)}
                                title={t('common.edit')}
                            />
                            <Button
                                type="text"
                                size="small"
                                danger
                                icon={<DeleteOutlined />}
                                onClick={(event) => handleDeleteExam(item.id, event)}
                            />
                        </>
                    )}
                </>
            )
        }

        return isTeacher ? (
            <>
                <Button
                    type="text"
                    size="small"
                    icon={<EyeOutlined />}
                    title={t('exam.studio.viewResults')}
                    onClick={(event) => handleViewResults(item.id, event)}
                />
                <Button
                    type="text"
                    size="small"
                    icon={<EditOutlined />}
                    onClick={(event) => handleEditQuiz(item.id, event)}
                />
                <Button
                    type="text"
                    size="small"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={(event) => handleDeleteQuiz(item.id, event)}
                />
            </>
        ) : null
    }

    const renderStudioItem = (item) => {
        const isExam = item._type === 'exam'
        return (
            <List.Item
                className="cursor-pointer hover:bg-gray-50 px-3 py-2 rounded-lg mb-2 transition-colors"
                onClick={() => (isExam ? handleExamClick(item) : handleQuizClick(item))}
            >
                <div className="w-full">
                    <div className="flex justify-between items-start mb-1">
                        <div className="flex-1">
                            <div className="font-medium text-gray-800 mb-1">
                                {isExam ? (item.title || t('exam.studio.unnamedExam')) : (item.name || t('exam.studio.unnamedQuiz'))}
                            </div>
                            <div className="flex items-center gap-2">
                                <Tag color={isExam ? 'blue' : 'green'}>
                                    {isExam ? `${item.num_questions || 0} ${t('exam.studio.questions')}` : `${item.num_questions} ${t('studio.questions')}`}
                                </Tag>
                                {isExam && (
                                    <Tag color={item.is_published ? 'green' : 'default'}>
                                        {item.is_published ? t('exam.studio.published') : t('exam.studio.unpublished')}
                                    </Tag>
                                )}
                                <Tag color="default">{isExam ? 'Exam' : 'Quiz'}</Tag>
                            </div>
                        </div>
                        <div className="flex items-center gap-2">
                            {renderItemActions(item, isExam)}
                        </div>
                    </div>
                    <div className="text-xs text-gray-500">
                        {formatStudioDate(item.created_at)}
                    </div>
                    {item.documents?.length > 0 && (
                        <div className="text-xs text-gray-600 mt-1 truncate">
                            {t('studio.source')}: {item.documents.map((document) => document.name).join(', ')}
                        </div>
                    )}
                </div>
            </List.Item>
        )
    }

    return (
        <Card
            className="h-full border-r border-gray-100 flex flex-col"
            style={{ width: widthSize || '100%' }}
            hoverable
            styles={{ body: { height: '100%', padding: isStudioCardCollapsed ? '1.5rem 0.75rem' : '1.5rem', display: 'flex', flexDirection: 'column' } }}
        >
            {isStudioCardCollapsed ? (
                <div className="flex flex-col items-center h-full">
                    <Button
                        onClick={() => dispatch(toggleStudioCardCollapse())}
                        shape="circle"
                        type="text"
                        icon={<MenuFoldOutlined />}
                        title={t('studio.expandStudio')}
                    />
                    <CollapsedIcon />
                    <Divider />
                </div>
            ) : selectedQuiz ? (
                <QuizReader
                    quizId={selectedQuiz.id}
                    quizName={selectedQuiz.name}
                    onClose={handleCloseQuiz}
                />
            ) : (
                <>
                    <div className="flex mb-4">
                        <Title level={4} className="m-0">{t('studio.title')}</Title>
                        <Button
                            className="ml-auto"
                            onClick={() => dispatch(toggleStudioCardCollapse())}
                            shape="circle"
                            type="text"
                            icon={<MenuUnfoldOutlined />}
                            title={t('studio.collapseStudio')}
                        />
                    </div>

                    {isTeacher && (
                        <>
                            <div className="grid grid-cols-2 gap-4">
                                <QuizCard onQuizGenerated={loadQuizzesAndExams} />
                                <ExamGeneratorCard onExamGenerated={loadQuizzesAndExams} />
                            </div>
                            <Divider />
                        </>
                    )}

                    <div className="flex-1 overflow-y-auto space-y-4">
                        <List
                            dataSource={mergeStudioItems(exams, quizzes)}
                            split={false}
                            loading={listLoading}
                            locale={{ emptyText: t('exam.studio.noExamQuizRecords') }}
                            renderItem={renderStudioItem}
                        />
                    </div>
                </>
            )}
            <QuizResultList
                quizId={resultQuizId}
                visible={resultModalVisible}
                onClose={() => setResultModalVisible(false)}
            />
        </Card>
    )
}

export default memo(StudioCard)
