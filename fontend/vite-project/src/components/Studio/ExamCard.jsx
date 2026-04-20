import React, { useState } from 'react';
import { Card, Typography, Modal, Input, message, Button, Space } from 'antd';
import { useNavigate } from 'react-router-dom';

export default function ExamCard({ defaultClassId }) {
  const { Title } = Typography;
  const navigate = useNavigate();

  const [open, setOpen] = useState(false);
  const [classId, setClassId] = useState(defaultClassId || '');

  const goToList = () => {
    const targetClassId = classId || defaultClassId;
    if (!targetClassId) {
      message.warning('請先輸入班級 ID');
      return;
    }
    navigate(`/exam/list/${targetClassId}`);
  };

  return (
    <>
      <Card
        style={{ backgroundColor: '#f7edeb' }}
        className="hover:bg-green-200 cursor-pointer hover:brightness-95 "
        styles={{ body: { padding: '0.5rem', backgroundColor: 'transparent' } }}
        onClick={() => goToList()}
      >
        <div className="flex justify-between">
          <span className="material-symbols-outlined" style={{ color: '#8c2e2a' }}>
            cards_star
          </span>

          <span
            className="material-symbols-outlined "
            style={{ color: '#8c2e2a' }}
            onClick={(e) => {
              e.stopPropagation();
              setOpen(true);
            }}
          >
            edit
          </span>
        </div>
        <Title level={5} style={{ color: '#8c2e2a', marginTop: '1rem' }}>
          Exam
        </Title>
      </Card>

      <Modal
        title="前往考試列表"
        open={open}
        onCancel={() => setOpen(false)}
        footer={null}
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Input
            placeholder="輸入班級 ID"
            value={classId}
            onChange={(e) => setClassId(e.target.value)}
          />
          <Button type="primary" block onClick={goToList}>
            開啟考試列表
          </Button>
        </Space>
      </Modal>
    </>
  );
}
