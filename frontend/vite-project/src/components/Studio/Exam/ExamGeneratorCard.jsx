import React, { useState } from 'react';
import { useSelector } from 'react-redux';
import { useTranslation } from 'react-i18next';
import {
    Button,
    Card,
    message,
    Modal,
    Space,
    Typography,
} from 'antd';
import {
    RobotOutlined,
    ThunderboltOutlined,
} from '@ant-design/icons';
import { generateExam, downloadExamPdf } from '../../../api/exam';
import { buildExamGenerationPayload, getExamProgressStage } from './examGeneratorLogic';
import {
    ExamFormView,
    ExamProgressView,
    ExamResultView,
} from './ExamGeneratorSections';

const { Title } = Typography;

export default function ExamGeneratorCard({ onExamGenerated }) {
    const { t } = useTranslation();
    const { selectedFileIds } = useSelector((state) => state.documents);

    const [open, setOpen] = useState(false);
    const [loading, setLoading] = useState(false);
    const [difficulty, setDifficulty] = useState('medium');
    const [topic, setTopic] = useState('');
    const [examName, setExamName] = useState('');
    const [includeImages, setIncludeImages] = useState(true);
    const [mcCount, setMcCount] = useState(5);
    const [shortAnswerCount, setShortAnswerCount] = useState(0);
    const [essayCount, setEssayCount] = useState(0);
    const [customPrompt, setCustomPrompt] = useState('');
    const [result, setResult] = useState(null);
    const [showResult, setShowResult] = useState(false);
    const [progress, setProgress] = useState(0);
    const [progressStatus, setProgressStatus] = useState('');

    const hasSelectedFiles = Boolean(selectedFileIds?.length);
    const totalQuestions = mcCount + shortAnswerCount + essayCount;

    const resetModalState = () => {
        setResult(null);
        setShowResult(false);
        setProgress(0);
        setProgressStatus('');
    };

    const handleOpenModal = () => {
        if (!hasSelectedFiles) {
            message.warning(t('exam.generator.selectFilesWarning'));
            return;
        }
        resetModalState();
        setOpen(true);
    };

    const handleGenerate = async () => {
        if (!hasSelectedFiles) {
            message.warning(t('exam.generator.selectFilesWarning'));
            return;
        }

        setLoading(true);
        setProgress(10);
        setProgressStatus(t('exam.generator.retrieving'));

        const progressInterval = setInterval(() => {
            setProgress((previous) => {
                if (previous >= 90) {
                    clearInterval(progressInterval);
                    return previous;
                }
                const stage = getExamProgressStage(previous, t);
                if (stage) {
                    setProgressStatus(stage.s);
                    return stage.p;
                }
                return previous + 5;
            });
        }, 2000);

        try {
            const response = await generateExam(buildExamGenerationPayload({
                selectedFileIds,
                topic,
                difficulty,
                mcCount,
                shortAnswerCount,
                essayCount,
                examName,
                includeImages,
                customPrompt,
            }));

            setProgress(100);
            setProgressStatus(t('exam.generator.complete'));

            const data = response.data;
            setResult(data);
            setShowResult(true);
            message.success(t('exam.generator.generateSuccess', { count: data.questions?.length || 0 }));
            onExamGenerated?.(data);
        } catch (error) {
            console.error('Exam generation failed:', error);
            message.error(error.response?.data?.detail || t('exam.generator.generateFailed'));
            setProgress(0);
            setProgressStatus('');
        } finally {
            clearInterval(progressInterval);
            setLoading(false);
        }
    };

    const handleDownloadPdf = async () => {
        if (!result?.exam_id) {
            message.error(t('exam.generator.noPdfAvailable'));
            return;
        }

        try {
            message.loading(t('exam.generator.downloadPdfLoading'), 0);
            await downloadExamPdf(result.exam_id, `${result.exam_name || 'exam'}.pdf`);
            message.destroy();
            message.success(t('exam.generator.downloadPdfSuccess'));
        } catch (error) {
            message.destroy();
            console.error('Exam PDF download failed:', error);
            message.error(t('exam.generator.downloadPdfFailed'));
        }
    };

    const handleClose = () => {
        setOpen(false);
        resetModalState();
    };

    return (
        <>
            <Card
                className="bg-purple-100 hover:bg-purple-200 cursor-pointer"
                styles={{ body: { padding: '0.5rem', backgroundColor: 'transparent' } }}
                onClick={handleOpenModal}
                loading={loading}
            >
                <div className="flex justify-between">
                    <RobotOutlined className="text-xl text-purple-600" />
                    <ThunderboltOutlined className="text-lg text-yellow-500" />
                </div>
                <Title level={5} style={{ color: '#7c3aed', marginTop: '1rem' }}>
                    {t('exam.generator.cardTitle')}
                </Title>
            </Card>

            <Modal
                title={(
                    <Space>
                        <RobotOutlined />
                        <span>{t('exam.generator.title')}</span>
                    </Space>
                )}
                open={open}
                onCancel={handleClose}
                width={700}
                footer={loading || showResult ? null : [
                    <Button key="cancel" onClick={handleClose}>
                        {t('exam.generator.cancel')}
                    </Button>,
                    <Button
                        key="generate"
                        type="primary"
                        icon={<ThunderboltOutlined />}
                        onClick={handleGenerate}
                        disabled={!hasSelectedFiles || totalQuestions === 0}
                    >
                        {t('exam.generator.generate')}
                    </Button>,
                ]}
            >
                {loading ? (
                    <ExamProgressView progress={progress} progressStatus={progressStatus} t={t} />
                ) : showResult ? (
                    <ExamResultView result={result} onDownloadPdf={handleDownloadPdf} onClose={handleClose} t={t} />
                ) : (
                    <ExamFormView
                        customPrompt={customPrompt}
                        difficulty={difficulty}
                        essayCount={essayCount}
                        examName={examName}
                        includeImages={includeImages}
                        mcCount={mcCount}
                        selectedFileIds={selectedFileIds}
                        setCustomPrompt={setCustomPrompt}
                        setDifficulty={setDifficulty}
                        setEssayCount={setEssayCount}
                        setExamName={setExamName}
                        setIncludeImages={setIncludeImages}
                        setMcCount={setMcCount}
                        setShortAnswerCount={setShortAnswerCount}
                        setTopic={setTopic}
                        shortAnswerCount={shortAnswerCount}
                        t={t}
                        topic={topic}
                    />
                )}
            </Modal>
        </>
    );
}
