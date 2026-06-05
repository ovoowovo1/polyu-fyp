import React from 'react';
import {
    Alert,
    Button,
    Card,
    Divider,
    Form,
    Input,
    InputNumber,
    Progress,
    Radio,
    Space,
    Switch,
    Tag,
    Typography,
} from 'antd';
import {
    CheckCircleOutlined,
    DownloadOutlined,
    LoadingOutlined,
    RobotOutlined,
    WarningOutlined,
} from '@ant-design/icons';
import {
    examGenerationTotals,
    examQuestionTypeColor,
    examQuestionTypeLabel,
    examResultQuestionPreview,
} from './examGeneratorLogic';

const { Title, Text, Paragraph } = Typography;

const progressSteps = [
    { threshold: 20, labelKey: 'exam.generator.retriever' },
    { threshold: 50, labelKey: 'exam.generator.generator' },
    { threshold: 70, labelKey: 'exam.generator.visualizer' },
    { threshold: 85, labelKey: 'exam.generator.reviewer' },
    { threshold: 100, labelKey: 'exam.generator.pdfGenerator' },
];

function ProgressStepIcon({ progress, threshold, previousThreshold }) {
    if (progress >= threshold) {
        return <CheckCircleOutlined style={{ color: '#52c41a' }} />;
    }
    if (progress >= previousThreshold) {
        return <LoadingOutlined />;
    }
    return <span className="w-4" />;
}

export function ExamProgressView({ progress, progressStatus, t }) {
    return (
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
                    {progressSteps.map((step, index) => {
                        const previousThreshold = index === 0 ? 0 : progressSteps[index - 1].threshold;
                        return (
                            <div key={step.labelKey} className="flex items-center gap-2">
                                <ProgressStepIcon
                                    progress={progress}
                                    threshold={step.threshold}
                                    previousThreshold={previousThreshold}
                                />
                                <Text type={progress >= step.threshold ? 'success' : 'secondary'}>
                                    {t(step.labelKey)}
                                </Text>
                            </div>
                        );
                    })}
                </Space>
            </div>
        </div>
    );
}

export function ExamResultView({ result, onDownloadPdf, onClose, t }) {
    const preview = examResultQuestionPreview(result?.questions || []);

    return (
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
                            {result.warnings.map((warning, index) => (
                                <li key={index}>{warning}</li>
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
                        onClick={onDownloadPdf}
                    >
                        {t('exam.generator.downloadPdf')}
                    </Button>
                )}
                <Button size="large" onClick={onClose}>
                    {t('exam.generator.close')}
                </Button>
            </div>

            <Divider>{t('exam.generator.preview')}</Divider>

            <div className="max-h-96 overflow-y-auto">
                {preview.questions.map((question, index) => (
                    <Card key={question.question_id || index} size="small" className="mb-2">
                        <div className="flex justify-between items-start">
                            <Text strong>{t('exam.generator.question', { number: index + 1 })}</Text>
                            <Space>
                                <Tag color={examQuestionTypeColor(question.question_type)}>
                                    {examQuestionTypeLabel(question.question_type, t)}
                                </Tag>
                                <Tag color="cyan">{question.bloom_level}</Tag>
                                <Tag color="green">{t('exam.generator.marks', { marks: question.marks })}</Tag>
                            </Space>
                        </div>
                        <Paragraph className="mt-2">{question.question_text}</Paragraph>
                        {question.question_type === 'multiple_choice' && question.choices && (
                            <div className="pl-4">
                                {question.choices.map((choice, choiceIndex) => (
                                    <div
                                        key={choiceIndex}
                                        className={choiceIndex === question.correct_answer_index ? 'text-green-600 font-medium' : ''}
                                    >
                                        {String.fromCharCode(65 + choiceIndex)}. {choice}
                                        {choiceIndex === question.correct_answer_index && ' (correct)'}
                                    </div>
                                ))}
                            </div>
                        )}
                        {question.question_type !== 'multiple_choice' && question.model_answer && (
                            <div className="pl-4 mt-2 p-2 bg-green-50 rounded">
                                <Text type="secondary" className="text-xs">{t('exam.generator.modelAnswer')}</Text>
                                <Paragraph className="text-sm mb-0 text-green-700">
                                    {question.model_answer.length > 200
                                        ? `${question.model_answer.substring(0, 200)}...`
                                        : question.model_answer}
                                </Paragraph>
                            </div>
                        )}
                    </Card>
                ))}
                {preview.remainingCount > 0 && (
                    <Text type="secondary" className="block text-center">
                        {t('exam.generator.moreQuestions', { count: preview.remainingCount })}
                    </Text>
                )}
            </div>
        </div>
    );
}

export function ExamFormView({
    customPrompt,
    difficulty,
    essayCount,
    examName,
    includeImages,
    mcCount,
    selectedFileIds,
    setCustomPrompt,
    setDifficulty,
    setEssayCount,
    setExamName,
    setIncludeImages,
    setMcCount,
    setShortAnswerCount,
    setTopic,
    shortAnswerCount,
    t,
    topic,
}) {
    const totals = examGenerationTotals({ mcCount, shortAnswerCount, essayCount });

    return (
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
                    onChange={(event) => setExamName(event.target.value)}
                />
            </Form.Item>

            <Form.Item label={t('exam.generator.topic')}>
                <Input
                    placeholder={t('exam.generator.topicPlaceholder')}
                    value={topic}
                    onChange={(event) => setTopic(event.target.value)}
                />
            </Form.Item>

            <Divider orientation="left" plain>{t('exam.generator.questionTypeConfig')}</Divider>

            <div className="grid grid-cols-3 gap-4">
                <Form.Item label={t('exam.generator.multipleChoice')}>
                    <InputNumber min={0} max={30} value={mcCount} onChange={setMcCount} className="w-full" addonAfter={t('exam.generator.questions')} />
                    <Text type="secondary" className="text-xs">{t('exam.generator.marksPerQuestion', { marks: 1 })}</Text>
                </Form.Item>

                <Form.Item label={t('exam.generator.shortAnswer')}>
                    <InputNumber min={0} max={15} value={shortAnswerCount} onChange={setShortAnswerCount} className="w-full" addonAfter={t('exam.generator.questions')} />
                    <Text type="secondary" className="text-xs">{t('exam.generator.marksPerQuestion', { marks: 2 })}</Text>
                </Form.Item>

                <Form.Item label={t('exam.generator.essay')}>
                    <InputNumber min={0} max={10} value={essayCount} onChange={setEssayCount} className="w-full" addonAfter={t('exam.generator.questions')} />
                    <Text type="secondary" className="text-xs">{t('exam.generator.marksPerQuestion', { marks: 5 })}</Text>
                </Form.Item>
            </div>

            <div className="bg-gray-50 p-3 rounded-lg mb-4">
                <Space split={<Divider type="vertical" />}>
                    <Text>{t('exam.generator.totalQuestions', { count: totals.questions })}</Text>
                    <Text>{t('exam.generator.totalMarks', { marks: totals.marks })}</Text>
                </Space>
            </div>

            <Form.Item label={t('exam.generator.difficulty')}>
                <Radio.Group value={difficulty} onChange={(event) => setDifficulty(event.target.value)} optionType="button" buttonStyle="solid">
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
                    onChange={(event) => setCustomPrompt(event.target.value)}
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
                {totals.questions === 0 && (
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
}
