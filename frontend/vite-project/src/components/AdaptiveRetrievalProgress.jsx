import React, { useMemo } from 'react';
import { Card, Flex, Progress, Tag, Typography } from 'antd';
import {
  CheckCircleOutlined,
  FilterOutlined,
  LoadingOutlined,
  RadarChartOutlined,
  RedoOutlined,
  RobotOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';

import { buildRetrievalProgressModel } from '../utils/retrievalProgressModel.js';

const { Text } = Typography;

const STAGE_ICONS = {
  router: <RadarChartOutlined />,
  retrieval: <SearchOutlined />,
  grader: <FilterOutlined />,
  rewrite: <RedoOutlined />,
  generation: <RobotOutlined />,
};

const renderStatusAdornment = (status) => {
  if (status === 'completed') {
    return <CheckCircleOutlined style={{ color: '#52c41a' }} />;
  }
  if (status === 'running') {
    return <LoadingOutlined style={{ color: '#1677ff' }} />;
  }
  return null;
};

export default function AdaptiveRetrievalProgress({ progressMessages = [] }) {
  const { t } = useTranslation();
  const progress = useMemo(
    () => buildRetrievalProgressModel(progressMessages, t),
    [progressMessages, t],
  );

  return (
    <Card
      size="small"
      className="mb-2 w-full"
      style={{
        backgroundColor: progress.isCompleted ? '#f6ffed' : '#fff',
        border: progress.isCompleted ? '1px solid #b7eb8f' : '1px solid #d9d9d9',
      }}
    >
      <div className="space-y-3">
        <div>
          <div className="flex justify-between items-center mb-1">
            <Text strong style={{ fontSize: '12px' }}>
              {progress.isCompleted ? t('studio.retrievalComplete') : t('studio.retrievalProgress')}
            </Text>
            <Text style={{ fontSize: '11px', color: '#666' }}>
              {progress.percent}%
            </Text>
          </div>
          <Progress
            percent={progress.percent}
            size="small"
            strokeColor={progress.isCompleted ? '#52c41a' : '#1677ff'}
            showInfo={false}
          />
        </div>

        <Flex gap="small" wrap>
          {progress.stages.map((stage) => (
            <Flex
              key={stage.key}
              vertical
              align="center"
              flex="1"
              style={{ minWidth: '84px' }}
            >
              <Flex align="center" gap={4} style={{ fontSize: '16px', marginBottom: '4px' }}>
                <span style={{ color: stage.status === 'completed' ? '#52c41a' : '#1677ff' }}>
                  {STAGE_ICONS[stage.key]}
                </span>
                {renderStatusAdornment(stage.status)}
              </Flex>
              <Text style={{ fontSize: '11px', textAlign: 'center' }}>{stage.name}</Text>

              {stage.status === 'completed' && typeof stage.hits === 'number' ? (
                <Tag>{stage.hits} {t('retrieval.results')}</Tag>
              ) : stage.key === 'rewrite' && stage.count > 0 ? (
                <Tag>{t('retrieval.attempt', { count: stage.count })}</Tag>
              ) : (
                <Tag color={stage.status === 'running' ? 'processing' : 'default'}>
                  {t(`retrieval.${stage.status}`)}
                </Tag>
              )}
            </Flex>
          ))}
        </Flex>

        {progress.latestMessage && (
          <div className="border-t pt-2 mt-2">
            <Text ellipsis={{ expandable: true }} style={{ fontSize: '11px', color: '#888' }} className="truncate">
              {t('studio.latestProgress')}: {progress.latestMessage}
            </Text>
          </div>
        )}
      </div>
    </Card>
  );
}
