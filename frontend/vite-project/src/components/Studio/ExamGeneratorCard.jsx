import React, { useState } from 'react';
import { useSelector } from 'react-redux';
import { useTranslation } from 'react-i18next';
import {
    Card,
    Typography,
    Modal,
    Form,
    Input,
    InputNumber,
    Radio,
    Switch,
    Button,
    Progress,
    Alert,
    Space,
    Divider,
    message,
    Tag
} from 'antd';
import {
    DownloadOutlined,
    RobotOutlined,
    ThunderboltOutlined,
    CheckCircleOutlined,
    LoadingOutlined,
    WarningOutlined
} from '@ant-design/icons';
import { generateExam, downloadExamPdf } from '../../api/exam';

const { Title, Text, Paragraph } = Typography;

export default function ExamGeneratorCard({ onExamGenerated }) {
    const { t } = useTranslation();
    const { selectedFileIds } = useSelector((state) => state.documents);
    
    // Modal state
    const [open, setOpen] = useState(false);
    const [loading, setLoading] = useState(false);
    
    // Form state
    const [difficulty, setDifficulty] = useState('medium');
    const [topic, setTopic] = useState('');
    const [examName, setExamName] = useState('');
    const [includeImages, setIncludeImages] = useState(true);
    
    // Question type counts
    const [mcCount, setMcCount] = useState(5);
    const [shortAnswerCount, setShortAnswerCount] = useState(0);
    const [essayCount, setEssayCount] = useState(0);
    
    // Custom prompt
    const [customPrompt, setCustomPrompt] = useState('');
    
    // Result state
    const [result, setResult] = useState(null);
    const [showResult, setShowResult] = useState(false);
    
    // Progress state
    const [progress, setProgress] = useState(0);
    const [progressStatus, setProgressStatus] = useState('');

    const handleOpenModal = () => {
        if (!selectedFileIds || selectedFileIds.length === 0) {
            message.warning(t('exam.generator.selectFilesWarning'));
            return;
        }
        setOpen(true);
        setResult(null);
        setShowResult(false);
        setProgress(0);
    };

    const handleGenerate = async () => {
        if (!selectedFileIds || selectedFileIds.length === 0) {
            message.warning(t('exam.generator.selectFilesWarning'));
            return;
        }

        setLoading(true);
        setProgress(10);
        setProgressStatus(t('exam.generator.retrieving'));

        try {
            // 模擬進度更新
            const progressInterval = setInterval(() => {
                setProgress(prev => {
                    if (prev >= 90) {
                        clearInterval(progressInterval);
                        return prev;
                    }
                    const stages = [
                        { p: 20, s: t('exam.generator.analyzing') },
                        { p: 40, s: t('exam.generator.generating') },
                        { p: 60, s: t('exam.generator.generatingCharts') },
                        { p: 75, s: t('exam.generator.reviewing') },
                        { p: 85, s: t('exam.generator.generatingPdf') },
                    ];
                    const stage = stages.find(s => s.p > prev);
                    if (stage) {
                        setProgressStatus(stage.s);
                        return stage.p;
                    }
                    return prev + 5;
                });
            }, 2000);

            const totalQuestions = mcCount + shortAnswerCount + essayCount;
            const response = await generateExam({
                file_ids: selectedFileIds,
                topic: topic || undefined,
                difficulty,
                num_questions: totalQuestions,
                question_types: {
                    multiple_choice: mcCount,
                    short_answer: shortAnswerCount,
                    essay: essayCount
                },
                exam_name: examName || undefined,
                include_images: includeImages,
                custom_prompt: customPrompt || undefined
            });

            clearInterval(progressInterval);
            setProgress(100);
            setProgressStatus(t('exam.generator.complete'));

            const data = response.data;
            setResult(data);
            setShowResult(true);

            message.success(t('exam.generator.generateSuccess', { count: data.questions?.length || 0 }));

            if (onExamGenerated) {
                onExamGenerated(data);
            }

        } catch (error) {
            console.error('生成考試失敗:', error);
            message.error(error.response?.data?.detail || t('exam.generator.generateFailed'));
            setProgress(0);
            setProgressStatus('');
        } finally {
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
            message.error(t('exam.generator.downloadPdfFailed'));
        }
    };

    const handleClose = () => {
        setOpen(false);
        setResult(null);
        setShowResult(false);
        setProgress(0);
        setProgressStatus('');
    };

    const renderProgressView = () => (
        <div className="text-center py-8">
            <RobotOutlined style={{ fontSize: 48, color: '#1890ff' }} />
            <Title level={4} className="mt-4">{t('exam.generator.working')}</Title>
            <Progress 
                percent={progress} 
                status="active"
                strokeColor={{
                    '0%': '#108ee9',
                    '100%': '#87d068',
                }}
            />
            <Text type="secondary" className="mt-2 block">{progressStatus}</Text>
            
            <div className="mt-6 text-left bg-gray-50 p-4 rounded-lg">
                <Space direction="vertical" size="small">
                    <div className="flex items-center gap-2">
                        {progress >= 20 ? <CheckCircleOutlined style={{ color: '#52c41a' }} /> : <LoadingOutlined />}
                        <Text type={progress >= 20 ? 'success' : 'secondary'}>{t('exam.generator.retriever')}</Text>
                    </div>
                    <div className="flex items-center gap-2">
                        {progress >= 50 ? <CheckCircleOutlined style={{ color: '#52c41a' }} /> : progress >= 20 ? <LoadingOutlined /> : <span className="w-4" />}
                        <Text type={progress >= 50 ? 'success' : 'secondary'}>{t('exam.generator.generator')}</Text>
                    </div>
                    <div className="flex items-center gap-2">
                        {progress >= 70 ? <CheckCircleOutlined style={{ color: '#52c41a' }} /> : progress >= 50 ? <LoadingOutlined /> : <span className="w-4" />}
                        <Text type={progress >= 70 ? 'success' : 'secondary'}>{t('exam.generator.visualizer')}</Text>
                    </div>
                    <div className="flex items-center gap-2">
                        {progress >= 85 ? <CheckCircleOutlined style={{ color: '#52c41a' }} /> : progress >= 70 ? <LoadingOutlined /> : <span className="w-4" />}
                        <Text type={progress >= 85 ? 'success' : 'secondary'}>{t('exam.generator.reviewer')}</Text>
                    </div>
                    <div className="flex items-center gap-2">
                        {progress >= 100 ? <CheckCircleOutlined style={{ color: '#52c41a' }} /> : progress >= 85 ? <LoadingOutlined /> : <span className="w-4" />}
                        <Text type={progress >= 100 ? 'success' : 'secondary'}>{t('exam.generator.pdfGenerator')}</Text>
                    </div>
                </Space>
            </div>
        </div>
    );

    const renderResultView = () => (
        <div className="py-4">
            <Alert
                message={t('exam.generator.successTitle')}
                description={
                    <div>
                        <p>{t('exam.generator.examNameLabel', { name: result?.exam_name || '' })}</p>
                        <p>{t('exam.generator.questionCount', { count: result?.questions?.length || 0 })}</p>
                        <p>{result?.review_score ? t('exam.generator.qualityScore', { score: result.review_score.toFixed(1) }) : t('exam.generator.qualityScoreNA')}</p>
                    </div>
                }
                type="success"
                showIcon
                icon={<CheckCircleOutlined />}
            />

            {result?.warnings?.length > 0 && (
                <Alert
                    message={t('exam.generator.warnings')}
                    description={
                        <ul className="list-disc pl-4">
                            {result.warnings.map((w, i) => (
                                <li key={i}>{w}</li>
                            ))}
                        </ul>
                    }
                    type="warning"
                    showIcon
                    icon={<WarningOutlined />}
                    className="mt-4"
                />
            )}

            <Divider />

            <div className="flex justify-center gap-4">
                {result?.pdf_path && (
                    <Button
                        type="primary"
                        icon={<DownloadOutlined />}
                        size="large"
                        onClick={handleDownloadPdf}
                    >
                        {t('exam.generator.downloadPdf')}
                    </Button>
                )}
                <Button size="large" onClick={handleClose}>
                    {t('exam.generator.close')}
                </Button>
            </div>

            <Divider>{t('exam.generator.preview')}</Divider>

            <div className="max-h-96 overflow-y-auto">
                {result?.questions?.slice(0, 5).map((q, index) => (
                    <Card key={q.question_id} size="small" className="mb-2">
                        <div className="flex justify-between items-start">
                            <Text strong>{t('exam.generator.question', { number: index + 1 })}</Text>
                            <Space>
                                <Tag color={
                                    q.question_type === 'multiple_choice' ? 'blue' :
                                    q.question_type === 'short_answer' ? 'orange' : 'purple'
                                }>
                                    {q.question_type === 'multiple_choice' ? t('exam.generator.questionTypeMultipleChoice') :
                                     q.question_type === 'short_answer' ? t('exam.generator.questionTypeShortAnswer') : t('exam.generator.questionTypeEssay')}
                                </Tag>
                                <Tag color="cyan">{q.bloom_level}</Tag>
                                <Tag color="green">{t('exam.generator.marks', { marks: q.marks })}</Tag>
                            </Space>
                        </div>
                        <Paragraph className="mt-2">{q.question_text}</Paragraph>
                        {q.question_type === 'multiple_choice' && q.choices && (
                            <div className="pl-4">
                                {q.choices.map((choice, i) => (
                                    <div key={i} className={i === q.correct_answer_index ? 'text-green-600 font-medium' : ''}>
                                        {String.fromCharCode(65 + i)}. {choice}
                                        {i === q.correct_answer_index && ' ✓'}
                                    </div>
                                ))}
                            </div>
                        )}
                        {q.question_type !== 'multiple_choice' && q.model_answer && (
                            <div className="pl-4 mt-2 p-2 bg-green-50 rounded">
                                <Text type="secondary" className="text-xs">{t('exam.generator.modelAnswer')}</Text>
                                <Paragraph className="text-sm mb-0 text-green-700">
                                    {q.model_answer.length > 200 
                                        ? q.model_answer.substring(0, 200) + '...' 
                                        : q.model_answer}
                                </Paragraph>
                            </div>
                        )}
                    </Card>
                ))}
                {result?.questions?.length > 5 && (
                    <Text type="secondary" className="block text-center">
                        {t('exam.generator.moreQuestions', { count: result.questions.length - 5 })}
                    </Text>
                )}
            </div>
        </div>
    );

    const renderFormView = () => (
        <Form layout="vertical">
            <Alert
                message={t('exam.generator.multiAgentSystem')}
                description={t('exam.generator.multiAgentDescription')}
                type="info"
                showIcon
                icon={<RobotOutlined />}
                className="mb-4"
            />

            <Form.Item label={t('exam.generator.examName')}>
                <Input
                    placeholder={t('exam.generator.examNamePlaceholder')}
                    value={examName}
                    onChange={e => setExamName(e.target.value)}
                />
            </Form.Item>

            <Form.Item label={t('exam.generator.topic')}>
                <Input
                    placeholder={t('exam.generator.topicPlaceholder')}
                    value={topic}
                    onChange={e => setTopic(e.target.value)}
                />
            </Form.Item>

            <Divider orientation="left" plain>{t('exam.generator.questionTypeConfig')}</Divider>
            
            <div className="grid grid-cols-3 gap-4">
                <Form.Item label={t('exam.generator.multipleChoice')}>
                    <InputNumber
                        min={0}
                        max={30}
                        value={mcCount}
                        onChange={setMcCount}
                        className="w-full"
                        addonAfter={t('exam.generator.questions')}
                    />
                    <Text type="secondary" className="text-xs">{t('exam.generator.marksPerQuestion', { marks: 1 })}</Text>
                </Form.Item>

                <Form.Item label={t('exam.generator.shortAnswer')}>
                    <InputNumber
                        min={0}
                        max={15}
                        value={shortAnswerCount}
                        onChange={setShortAnswerCount}
                        className="w-full"
                        addonAfter={t('exam.generator.questions')}
                    />
                    <Text type="secondary" className="text-xs">{t('exam.generator.marksPerQuestion', { marks: 2 })}</Text>
                </Form.Item>

                <Form.Item label={t('exam.generator.essay')}>
                    <InputNumber
                        min={0}
                        max={10}
                        value={essayCount}
                        onChange={setEssayCount}
                        className="w-full"
                        addonAfter={t('exam.generator.questions')}
                    />
                    <Text type="secondary" className="text-xs">{t('exam.generator.marksPerQuestion', { marks: 5 })}</Text>
                </Form.Item>
            </div>

            <div className="bg-gray-50 p-3 rounded-lg mb-4">
                <Space split={<Divider type="vertical" />}>
                    <Text>{t('exam.generator.totalQuestions', { count: mcCount + shortAnswerCount + essayCount })}</Text>
                    <Text>{t('exam.generator.totalMarks', { marks: mcCount * 1 + shortAnswerCount * 2 + essayCount * 5 })}</Text>
                </Space>
            </div>

            <Form.Item label={t('exam.generator.difficulty')}>
                <Radio.Group
                    value={difficulty}
                    onChange={e => setDifficulty(e.target.value)}
                    optionType="button"
                    buttonStyle="solid"
                >
                    <Radio.Button value="easy">{t('exam.generator.difficultyEasy')}</Radio.Button>
                    <Radio.Button value="medium">{t('exam.generator.difficultyMedium')}</Radio.Button>
                    <Radio.Button value="difficult">{t('exam.generator.difficultyDifficult')}</Radio.Button>
                </Radio.Group>
            </Form.Item>

            <Form.Item label={t('exam.generator.includeImages')}>
                <Switch
                    checked={includeImages}
                    onChange={setIncludeImages}
                    checkedChildren={t('exam.generator.includeImagesYes')}
                    unCheckedChildren={t('exam.generator.includeImagesNo')}
                />
                <Text type="secondary" className="ml-2">
                    {t('exam.generator.includeImagesDescription')}
                </Text>
            </Form.Item>

            <Form.Item label={t('exam.generator.customPrompt')}>
                <Input.TextArea
                    placeholder={t('exam.generator.customPromptPlaceholder')}
                    value={customPrompt}
                    onChange={e => setCustomPrompt(e.target.value)}
                    maxLength={1000}
                    showCount
                    rows={3}
                />
                <Text type="secondary" className="text-xs">
                    {t('exam.generator.customPromptDescription')}
                </Text>
            </Form.Item>

            <Divider />

            <div className="text-center">
                <Text type="secondary">
                    {t('exam.generator.selectedFiles', { count: selectedFileIds?.length || 0 })}
                </Text>
                {(mcCount + shortAnswerCount + essayCount) === 0 && (
                    <Alert
                        message={t('exam.generator.selectQuestionTypeWarning')}
                        type="warning"
                        showIcon
                        className="mt-2"
                    />
                )}
            </div>
        </Form>
    );

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
                title={
                    <Space>
                        <RobotOutlined />
                        <span>{t('exam.generator.title')}</span>
                    </Space>
                }
                open={open}
                onCancel={handleClose}
                width={700}
                footer={
                    loading ? null : showResult ? null : [
                        <Button key="cancel" onClick={handleClose}>
                            {t('exam.generator.cancel')}
                        </Button>,
                        <Button
                            key="generate"
                            type="primary"
                            icon={<ThunderboltOutlined />}
                            onClick={handleGenerate}
                            disabled={!selectedFileIds?.length || (mcCount + shortAnswerCount + essayCount) === 0}
                        >
                            {t('exam.generator.generate')}
                        </Button>
                    ]
                }
            >
                {loading ? renderProgressView() : showResult ? renderResultView() : renderFormView()}
            </Modal>
        </>
    );
}

