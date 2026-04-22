import React from 'react';
import { Modal, Button, Typography, Tag, Space, Card, Divider } from 'antd';
import { CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons';

const { Title, Text, Paragraph } = Typography;

export default function SubmissionDetailModal({ submission, quiz, visible, onClose }) {
    if (!submission || !quiz) return null;

    const questions = quiz.questions || [];
    const studentAnswers = submission.answers || [];
    
    // Create a map for faster lookup: question_index -> answer_index
    const answerMap = {};
    studentAnswers.forEach(ans => {
        // Ensure we handle both string and number types if JSON serialization changed them
        if (ans && ans.question_index !== undefined) {
            answerMap[ans.question_index] = ans.answer_index;
        }
    });

    return (
        <Modal
            title={
                <div className="flex justify-between items-center pr-8">
                    <span>Quiz Details: {submission.student_name}</span>
                    <Space>
                        <Tag color={submission.score === submission.total_questions ? 'green' : 'blue'}>
                            Score: {submission.score} / {submission.total_questions}
                        </Tag>
                        {studentAnswers.length === 0 && <Tag color="warning">No Answer Data</Tag>}
                    </Space>
                </div>
            }
            open={visible}
            onCancel={onClose}
            footer={[
                <Button key="close" onClick={onClose}>
                    Close
                </Button>
            ]}
            width={1200}
            styles={{ body: { maxHeight: '70vh', overflowY: 'auto', paddingRight: '10px' } }}
        >
            <div className="space-y-6">
                {questions.map((q, qIndex) => {
                    const studentChoice = answerMap[qIndex];
                    const correctChoice = q.answer_index;
                    // Use loose equality to handle string/number mismatch
                    const isCorrect = studentChoice == correctChoice; 
                    const isAnswered = studentChoice !== undefined && studentChoice !== null;

                    return (
                        <Card 
                            key={qIndex} 
                            size="small"
                            className={`border-l-4 ${isCorrect ? 'border-l-green-500' : 'border-l-red-500'}`}
                        >
                            <div className="flex gap-2 mb-2">
                                <Text strong className="text-lg text-gray-500">Q{qIndex + 1}.</Text>
                                <Text strong className="text-lg">{q.question}</Text>
                                {!isAnswered && <Tag color="warning">Not Answered</Tag>}
                            </div>

                            <Space direction="vertical" className="w-full pl-8">
                                {q.choices.map((choice, cIndex) => {
                                    // Loose equality for index matching
                                    const isSelected = studentChoice == cIndex;
                                    const isTargetAnswer = correctChoice == cIndex;
                                    
                                    let itemStyle = "p-3 rounded-lg border transition-all flex justify-between items-center ";
                                    
                                    if (isTargetAnswer) {
                                        // Correct answer always green bg
                                        itemStyle += "bg-green-50 border-green-500";
                                    } else if (isSelected) {
                                        // Wrong selection red bg (since if it was right, it would be caught above or we handle mixed)
                                        // But wait, if isTargetAnswer is true, we want green. 
                                        // If isSelected is true AND NOT isTargetAnswer, we want red.
                                        itemStyle += "bg-red-50 border-red-500";
                                    } else {
                                        // Normal
                                        itemStyle += "bg-white border-gray-200";
                                    }

                                    return (
                                        <div key={cIndex} className={itemStyle}>
                                            <div className="flex items-center gap-3">
                                                <div className={`w-6 h-6 rounded-full flex items-center justify-center border ${
                                                    isTargetAnswer ? 'bg-green-500 text-white border-green-500' :
                                                    (isSelected ? 'bg-red-500 text-white border-red-500' : 'text-gray-500 border-gray-300')
                                                }`}>
                                                    {String.fromCharCode(65 + cIndex)}
                                                </div>
                                                <Text>{choice}</Text>
                                            </div>
                                            
                                            <Space>
                                                {isTargetAnswer && <Tag color="success" icon={<CheckCircleOutlined />}>Correct Answer</Tag>}
                                                {isSelected && <Tag color={isTargetAnswer ? "success" : "error"} icon={isTargetAnswer ? <CheckCircleOutlined /> : <CloseCircleOutlined />}>Student Choice</Tag>}
                                            </Space>
                                        </div>
                                    );
                                })}
                            </Space>

                            {q.rationale && (
                                <div className="mt-4 ml-8 bg-gray-50 p-3 rounded text-gray-600 text-sm">
                                    <Text strong>Rationale:</Text> {q.rationale}
                                </div>
                            )}
                        </Card>
                    );
                })}
            </div>
        </Modal>
    );
}

