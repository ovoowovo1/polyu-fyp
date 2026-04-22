import React, { useState, useEffect } from 'react';
import { Modal, Table, message, Button, Typography, Space, Tooltip } from 'antd';
import { EyeOutlined } from '@ant-design/icons';
import { getQuizResults, getQuizById } from '../../api/quiz';
import SubmissionDetailModal from './SubmissionDetailModal';

const { Title } = Typography;

export default function QuizResultList({ quizId, visible, onClose }) {
    const [loading, setLoading] = useState(false);
    const [results, setResults] = useState([]);
    
    // For details view
    const [quizData, setQuizData] = useState(null);
    const [selectedSubmission, setSelectedSubmission] = useState(null);
    const [detailVisible, setDetailVisible] = useState(false);

    useEffect(() => {
        if (visible && quizId) {
            fetchResults();
            fetchQuizDetails();
        }
    }, [visible, quizId]);

    const fetchQuizDetails = async () => {
        try {
            const res = await getQuizById(quizId);
            setQuizData(res.data.quiz);
        } catch (error) {
            console.error('Fetch quiz details failed:', error);
            // Non-critical, but details won't work well without it
        }
    };

    const fetchResults = async () => {
        setLoading(true);
        try {
            const res = await getQuizResults(quizId);
            setResults(res.data.results || []);
        } catch (error) {
            console.error('Fetch results failed:', error);
            message.error('Failed to load quiz results');
        } finally {
            setLoading(false);
        }
    };

    const handleViewDetails = (record) => {
        if (!quizData) {
            message.warning('Quiz details not loaded yet, please try again.');
            return;
        }
        setSelectedSubmission(record);
        setDetailVisible(true);
    };

    const columns = [
        {
            title: 'Student Name',
            dataIndex: 'student_name',
            key: 'student_name',
        },
        {
            title: 'Email',
            dataIndex: 'student_email',
            key: 'student_email',
        },
        {
            title: 'Score',
            key: 'score',
            render: (_, record) => `${record.score} / ${record.total_questions}`,
            sorter: (a, b) => a.score - b.score,
        },
        {
            title: 'Submitted At',
            dataIndex: 'submitted_at',
            key: 'submitted_at',
            render: (text) => text ? new Date(text).toLocaleString() : '-',
            sorter: (a, b) => new Date(a.submitted_at) - new Date(b.submitted_at),
        },
        {
            title: 'Action',
            key: 'action',
            render: (_, record) => (
                <Tooltip title="View Answer Details">
                    <Button 
                        type="text" 
                        icon={<EyeOutlined />} 
                        onClick={() => handleViewDetails(record)}
                    />
                </Tooltip>
            ),
        }
    ];

    return (
        <>
            <Modal
                title="Quiz Results"
                open={visible}
                onCancel={onClose}
                footer={[
                    <Button key="close" onClick={onClose}>
                        Close
                    </Button>
                ]}
                width={1200}
            >
                <Table 
                    columns={columns} 
                    dataSource={results} 
                    rowKey="submission_id" 
                    loading={loading}
                    pagination={{ pageSize: 10 }}
                />
            </Modal>
            
            <SubmissionDetailModal 
                visible={detailVisible}
                submission={selectedSubmission}
                quiz={quizData}
                onClose={() => setDetailVisible(false)}
            />
        </>
    );
}

