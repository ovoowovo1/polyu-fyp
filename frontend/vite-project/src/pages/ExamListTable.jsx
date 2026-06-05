import React from 'react';
import { Button, Popconfirm, Space, Table, Tag, Typography } from 'antd';
import dayjs from 'dayjs';

import {
    formatExamCreatedAt,
    getExamStatusKey,
    getStudentExamActionKeys,
    getTeacherExamActionKeys,
} from './examListPageLogic';

const { Text } = Typography;

function renderTeacherAction({ actionKey, record, t, onNavigate, onPublish, onDelete }) {
    if (actionKey === 'view') {
        return (
            <Button key="view" size="small" onClick={() => onNavigate(`/exam/view/${record.id}`)}>
                {t('exam.listPage.actions.viewExam')}
            </Button>
        );
    }
    if (actionKey === 'publish' || actionKey === 'unpublish') {
        return (
            <Button
                key="publish"
                size="small"
                type={record.is_published ? 'default' : 'primary'}
                onClick={() => onPublish(record.id, !record.is_published)}
            >
                {record.is_published ? t('exam.listPage.actions.unpublish') : t('exam.listPage.actions.publish')}
            </Button>
        );
    }
    if (actionKey === 'submissions') {
        return (
            <Button key="submissions" size="small" onClick={() => onNavigate(`/exam/grade/${record.id}`)}>
                {t('exam.listPage.actions.viewSubmissions')}
            </Button>
        );
    }
    return (
        <Popconfirm key="delete" title={t('exam.listPage.actions.deleteConfirm')} onConfirm={() => onDelete(record.id)}>
            <Button size="small" danger>
                {t('exam.listPage.actions.delete')}
            </Button>
        </Popconfirm>
    );
}

function renderStudentAction({ actionKey, record, t, onNavigate, onStart }) {
    if (actionKey === 'take') {
        return (
            <Button key="take" size="small" type="primary" onClick={() => onStart(record.id)}>
                {t('exam.listPage.actions.start')}
            </Button>
        );
    }
    if (actionKey === 'notPublished') {
        return (
            <Button key="disabled" size="small" disabled>
                {t('exam.listPage.actions.notPublished')}
            </Button>
        );
    }
    return (
        <Button key="my" size="small" onClick={() => onNavigate(`/exam/grade/${record.id}?mode=mine`)}>
            {t('exam.listPage.actions.myScore')}
        </Button>
    );
}

function buildExamListColumns({ t, isTeacher, onNavigate, onPublish, onDelete, onStart }) {
    return [
        {
            title: t('exam.listPage.table.title'),
            dataIndex: 'title',
            key: 'title',
            render: (text) => <Text strong>{text || t('exam.studio.unnamedExam')}</Text>,
        },
        {
            title: t('exam.listPage.table.numQuestions'),
            dataIndex: 'num_questions',
            key: 'num_questions',
            width: 80,
        },
        {
            title: t('exam.listPage.table.totalMarks'),
            dataIndex: 'total_marks',
            key: 'total_marks',
            width: 80,
        },
        {
            title: t('exam.listPage.table.status'),
            dataIndex: 'is_published',
            key: 'is_published',
            width: 120,
            render: (value) => {
                const statusKey = getExamStatusKey(value);
                return (
                    <Tag color={statusKey === 'published' ? 'green' : 'default'}>
                        {statusKey === 'published' ? t('exam.studio.published') : t('exam.studio.unpublished')}
                    </Tag>
                );
            },
        },
        {
            title: t('exam.listPage.table.createdAt'),
            dataIndex: 'created_at',
            key: 'created_at',
            width: 180,
            render: (value) => formatExamCreatedAt(value, (dateValue) => dayjs(dateValue).format('YYYY/MM/DD HH:mm')),
        },
        {
            title: t('exam.listPage.table.actions'),
            key: 'actions',
            width: 280,
            render: (_, record) => {
                const actions = isTeacher
                    ? getTeacherExamActionKeys(record.is_published).map((actionKey) => renderTeacherAction({
                        actionKey,
                        record,
                        t,
                        onNavigate,
                        onPublish,
                        onDelete,
                    }))
                    : getStudentExamActionKeys(record.is_published).map((actionKey) => renderStudentAction({
                        actionKey,
                        record,
                        t,
                        onNavigate,
                        onStart,
                    }));
                return <Space>{actions}</Space>;
            },
        },
    ];
}

export default function ExamListTable({
    t,
    exams,
    loading,
    isTeacher,
    onNavigate,
    onPublish,
    onDelete,
    onStart,
}) {
    return (
        <Table
            rowKey="id"
            dataSource={exams}
            columns={buildExamListColumns({ t, isTeacher, onNavigate, onPublish, onDelete, onStart })}
            loading={loading}
            pagination={{ pageSize: 10 }}
        />
    );
}
