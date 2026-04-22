import React, { memo, useState, useEffect, useRef } from 'react'
import { Card, Typography, Button, message, Divider, List, Tag } from 'antd'
import { useSelector, useDispatch } from 'react-redux'
import { useTranslation } from 'react-i18next'
import { MenuFoldOutlined, MenuUnfoldOutlined, DeleteOutlined, EditOutlined, EyeOutlined, DownloadOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'

import AudioCard from './AudioCard'
import VideoCard from './VideoCard'
import MindMap from './MindMap'
import ReportCard from './ReportCard'
import FlashCard from './FlashCard'
import QuizCard from './QuizCard'
import ExamGeneratorCard from './ExamGeneratorCard'
import QuizReader from './QuizReader'
import CollapsedIcon from './CollapsedIcon'
import QuizResultList from './QuizResultList'

import { toggleStudioCardCollapse, setQuizReaderOpen } from '../../redux/studioSlice'
import { deleteQuiz, getAllQuizzes } from '../../api/quiz'
import { getExamList, deleteExam, downloadExamPdf } from '../../api/exam'
import { getCurrentUser } from '../../api/auth'


function StudioCard({ widthSize = null }) {
    const { t, i18n } = useTranslation();
    const dispatch = useDispatch();
    const { Title } = Typography;
    const { isStudioCardCollapsed, isQuizReaderOpen } = useSelector((state) => state.studio);
    const { currentClassId } = useSelector((state) => state.documents);

    const user = getCurrentUser();
    const isTeacher = user?.role === 'teacher';

    const [listLoading, setListLoading] = useState(false);
    const [quizzes, setQuizzes] = useState([]);
    const [exams, setExams] = useState([]);
    const [selectedQuiz, setSelectedQuiz] = useState(null);
    const [resultModalVisible, setResultModalVisible] = useState(false);
    const [resultQuizId, setResultQuizId] = useState(null);

    // refs to manage aborting and prevent duplicate sequential calls while loading
    const lastRequestedClassRef = useRef(null);
    const controllerRef = useRef(null);

    // 加載測驗與考試列表
    const loadQuizzesAndExams = async () => {
        if (!currentClassId) {
            setQuizzes([]);
            setExams([]);
            return;
        }

        // Avoid duplicate requests for the same class if already requested
        if (lastRequestedClassRef.current === currentClassId && listLoading) {
            return;
        }

        // Cancel previous pending request (if any)
        if (controllerRef.current) {
            try { controllerRef.current.abort(); } catch (e) { /* ignore */ }
            controllerRef.current = null;
        }

        const controller = new AbortController();
        controllerRef.current = controller;

        setListLoading(true);
        lastRequestedClassRef.current = currentClassId;
        try {
            const [quizRes, examRes] = await Promise.all([
                getAllQuizzes(currentClassId, { signal: controller.signal }),
                getExamList(currentClassId),
            ]);
            setQuizzes(quizRes.data?.quizzes || []);
            setExams(examRes.data?.exams || []);
        } catch (error) {
            // ignore abort errors
            if (error.name === 'CanceledError' || error.message === 'canceled') {
                // aborted
            } else {
                console.error('獲取列表失敗:', error);
                message.error(t('studio.quizDeleted'));
            }
        } finally {
            setListLoading(false);
        }
    };

    useEffect(() => {
        loadQuizzesAndExams();
    }, [currentClassId]);



    const handleDeleteQuiz = async (quizId, e) => {
        e.stopPropagation();
        try {
            await deleteQuiz(quizId);
            message.success(t('studio.quizDeleted'));
            loadQuizzesAndExams();
        } catch (error) {
            console.error('刪除測驗失敗:', error);
            message.error(t('studio.deleteQuizFailed'));
        }
    };

    const handleDeleteExam = async (examId, e) => {
        e.stopPropagation();
        try {
            await deleteExam(examId);
            message.success(t('exam.studio.examDeleted'));
            loadQuizzesAndExams();
        } catch (error) {
            console.error('刪除考試失敗:', error);
            message.error(t('exam.studio.deleteExamFailed'));
        }
    };

    const handleViewResults = (quizId, e) => {
        e.stopPropagation();
        setResultQuizId(quizId);
        setResultModalVisible(true);
    };

    const navigate = useNavigate();

    const handleEditQuiz = (quizId, e) => {
        // prevent the List.Item onClick from firing
        if (e && e.stopPropagation) e.stopPropagation();
        // navigate to edit page
        navigate(`/quiz/edit/${quizId}`)
    }

    const handleQuizClick = (quiz) => {
        setSelectedQuiz(quiz);
        dispatch(setQuizReaderOpen(true));
    };

    const handleExamClick = (exam) => {
        // 導向考試查看頁面 或 作答頁面
        if (isTeacher) {
            navigate(`/exam/view/${exam.id}`);
        } else {
            navigate(`/exam/take/${exam.id}`);
        }
    };

    const handleViewExam = (examId, e) => {
        e.stopPropagation();
        navigate(`/exam/view/${examId}`);
    };

    const handleEditExam = (classId, e) => {
        e.stopPropagation();
        navigate(`/exam/list/${classId}`);
    };

    const handleDownloadPdfExam = async (examId, e) => {
        if (e) e.stopPropagation();
        try {
            const exam = exams.find(e => e.id === examId);
            const filename = exam?.title ? `${exam.title}.pdf` : `exam_${examId}.pdf`;
            message.loading(t('exam.generator.downloadPdfLoading'), 0);
            await downloadExamPdf(examId, filename);
            message.destroy();
            message.success(t('exam.generator.downloadPdfSuccess'));
        } catch (error) {
            message.destroy();
            console.error('下載 PDF 失敗:', error);
            message.error(t('exam.generator.downloadPdfFailed'));
        }
    };

    const handleCloseQuiz = () => {
        setSelectedQuiz(null);
        dispatch(setQuizReaderOpen(false));
    };

    const formatDate = (timestamp) => {
        if (!timestamp) return '';
        // Handle both ISO string format and numeric timestamp
        const date = typeof timestamp === 'string' 
            ? new Date(timestamp) 
            : new Date(parseInt(timestamp));
        
        // Check if date is valid
        if (isNaN(date.getTime())) return '';
        
        // Format as DD/MM/YYYY HH:MM
        const day = String(date.getDate()).padStart(2, '0');
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const year = date.getFullYear();
        const hours = String(date.getHours()).padStart(2, '0');
        const minutes = String(date.getMinutes()).padStart(2, '0');
        
        return `${day}/${month}/${year} ${hours}:${minutes}`;
    };

    return (

        <Card
            className="h-full border-r border-gray-100 flex flex-col"
            style={{ width: widthSize || '100%' }}
            hoverable
            styles={{ body: { height: '100%', padding: isStudioCardCollapsed ? '1.5rem 0.75rem' : '1.5rem', display: 'flex', flexDirection: 'column' } }}
        >
            {
                isStudioCardCollapsed ? (
                    // 折疊狀態：只顯示展開按鈕
                    <>
                        <div className="flex flex-col items-center h-full">
                            <Button
                                onClick={() => dispatch(toggleStudioCardCollapse())}
                                shape='circle'
                                type="text"
                                icon={< MenuFoldOutlined />}
                                title={t('studio.expandStudio')}
                            />

                            <CollapsedIcon />
                            <Divider />

                        </div>
                    </>
                ) : selectedQuiz ? (
                    // 顯示測驗閱讀器
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
                                shape='circle'
                                type="text"
                                icon={<MenuUnfoldOutlined />}
                                title={t('studio.collapseStudio')}
                            />
                        </div>


                        {isTeacher && (
                            <>
                                <div className="grid grid-cols-2 gap-4">
                                    {/* <AudioCard /> */}
                                    {/* <VideoCard />*/}
                                    {/*<MindMap />*/}
                                    {/* <ReportCard />*/}
                                    {/* <FlashCard />*/}
                                    <QuizCard onQuizGenerated={loadQuizzesAndExams} />
                                    <ExamGeneratorCard onExamGenerated={loadQuizzesAndExams} />
                                </div>


                                <Divider />
                            </>
                        )}

                        <div className="flex-1 overflow-y-auto space-y-4">
                            <List
                                dataSource={[
                                    ...(exams || []).map(e => ({ ...e, _type: 'exam' })),
                                    ...(quizzes || []).map(q => ({ ...q, _type: 'quiz' })),
                                ].sort((a, b) => {
                                    // 按創建時間排序（最新的在前）
                                    const getTimestamp = (item) => {
                                        if (!item.created_at) return 0;
                                        if (typeof item.created_at === 'string') {
                                            return new Date(item.created_at).getTime();
                                        }
                                        return typeof item.created_at === 'number' 
                                            ? item.created_at 
                                            : parseInt(item.created_at) || 0;
                                    };
                                    return getTimestamp(b) - getTimestamp(a);
                                })}
                                split={false}
                                loading={listLoading}
                                locale={{ emptyText: t('exam.studio.noExamQuizRecords') }}
                                renderItem={(item) => {
                                    const isExam = item._type === 'exam';
                                    return (
                                        <List.Item
                                            className="cursor-pointer hover:bg-gray-50 px-3 py-2 rounded-lg mb-2 transition-colors"
                                            onClick={() => {
                                                if (isExam) {
                                                    handleExamClick(item);
                                                } else {
                                                    handleQuizClick(item);
                                                }
                                            }}
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
                                                        {isExam ? (
                                                            <>
                                                                {isTeacher && (
                                                                    <>

                                                                        <Button
                                                                            type="text"
                                                                            size="small"
                                                                            icon={<DownloadOutlined />}
                                                                            title={t('exam.studio.downloadPdf')}
                                                                            onClick={(e) => handleDownloadPdfExam(item.id, e)}
                                                                        />
                                                                    </>

                                                                )}
                                                                <Button
                                                                    type="text"
                                                                    size="small"
                                                                    icon={<EyeOutlined />}
                                                                    title={t('exam.studio.viewSubmissions')}
                                                                    onClick={(e) => {
                                                                        e.stopPropagation();
                                                                        navigate(`/exam/grade/${item.id}`);
                                                                    }}
                                                                />
                                                                {isTeacher && (
                                                                    <>
                                                                        <Button
                                                                            type="text"
                                                                            size="small"
                                                                            icon={<EditOutlined />}
                                                                            onClick={(e) => handleEditExam(currentClassId, e)}
                                                                            title={t('common.edit')}
                                                                        />


                                                                        <Button
                                                                            type="text"
                                                                            size="small"
                                                                            danger
                                                                            icon={<DeleteOutlined />}
                                                                            onClick={(e) => handleDeleteExam(item.id, e)}
                                                                        />
                                                                    </>
                                                                )}
                                                            </>
                                                        ) : (
                                                            isTeacher && (
                                                                <>
                                                                    <Button
                                                                        type="text"
                                                                        size="small"
                                                                        icon={<EyeOutlined />}
                                                                        title={t('exam.studio.viewResults')}
                                                                        onClick={(e) => handleViewResults(item.id, e)}
                                                                    />

                                                                    <Button
                                                                        type="text"
                                                                        size="small"
                                                                        icon={<EditOutlined />}
                                                                        onClick={(e) => handleEditQuiz(item.id, e)}
                                                                    />
                                                                    <Button
                                                                        type="text"
                                                                        size="small"
                                                                        danger
                                                                        icon={<DeleteOutlined />}
                                                                        onClick={(e) => handleDeleteQuiz(item.id, e)}
                                                                    />
                                                                </>
                                                            )
                                                        )}
                                                    </div>
                                                </div>
                                                <div className="text-xs text-gray-500">
                                                    {formatDate(item.created_at)}
                                                </div>
                                                {item.documents && item.documents.length > 0 && (
                                                    <div className="text-xs text-gray-600 mt-1 truncate">
                                                        {t('studio.source')}: {item.documents.map(d => d.name).join(', ')}
                                                    </div>
                                                )}
                                            </div>
                                        </List.Item>
                                    );
                                }}
                            />
                        </div>

                    </>
                )
            }
            <QuizResultList
                quizId={resultQuizId}
                visible={resultModalVisible}
                onClose={() => setResultModalVisible(false)}
            />
        </Card>

    )
}

export default memo(StudioCard)
