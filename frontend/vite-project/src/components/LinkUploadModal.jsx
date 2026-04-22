import React, { useState } from 'react';
import { Modal, Button, Input, message, Progress } from 'antd';
import { uploadLink } from '../api/upload.js';
import useUploadProgress from '../hooks/useUploadProgress.jsx';

const LinkUploadModal = ({ visible, onCancel, onSuccess }) => {
  const [link, setLink] = useState('');
  const [uploading, setUploading] = useState(false);
  const { progress, progressStatus, showProgress, startTracking, stopTracking, abortTracking, genClientId } = useUploadProgress();

  const handleOk = async () => {
    const url = (link || '').trim();
    if (!url) {
      message.warning('請輸入連結');
      return;
    }
    try {
      setUploading(true);
      const cid = startTracking(genClientId());
      await uploadLink(url, cid);
      message.success('連結已提交處理');
      onSuccess && onSuccess();
      onCancel();
    } catch (err) {
      const errorMessage = err.response?.data?.error || err.message || '連結提交失敗';
      message.error(errorMessage);
    } finally {
      setUploading(false);
      stopTracking(1500);
    }
  };

  const handleCancel = () => {
    setLink('');
    abortTracking();
    onCancel();
  };

  return (
    <Modal
      title="新增連結"
      open={visible}
      onCancel={handleCancel}
      onOk={handleOk}
      okText={uploading ? '提交中...' : '提交'}
      okButtonProps={{ disabled: !link.trim(), loading: uploading }}
      destroyOnHidden
    >
      <Input
        placeholder="輸入要抓取的連結，例如 https://example.com/article"
        value={link}
        onChange={(e) => setLink(e.target.value)}
        onPressEnter={handleOk}
      />
      {(uploading || showProgress) && (
        <div style={{ marginTop: 16 }}>
          <Progress percent={progress} status={uploading ? 'active' : progressStatus} />
        </div>
      )}
    </Modal>
  );
};

export default LinkUploadModal;
