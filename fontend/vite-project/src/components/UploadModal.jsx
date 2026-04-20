import React, { useState } from 'react';
import { Alert, Button, Modal, Progress, Tag, Typography, Upload, message } from 'antd';
import { InboxOutlined } from '@ant-design/icons';
import { useSelector } from 'react-redux';

import { uploadMultiple } from '../api/upload.js';
import useUploadProgress from '../hooks/useUploadProgress.jsx';

const { Dragger } = Upload;
const { Text } = Typography;

const STATUS_META = {
  success: { alertType: 'success', label: 'Success' },
  partial: { alertType: 'warning', label: 'Partial' },
  failed: { alertType: 'error', label: 'Failed' },
};

const UploadModal = ({ visible, onCancel, onSuccess }) => {
  const [fileList, setFileList] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState(null);
  const {
    progress,
    progressStatus,
    showProgress,
    startTracking,
    stopTracking,
    abortTracking,
    genClientId,
    finishedEvent,
  } = useUploadProgress();

  const currentClassId = useSelector((state) => state.documents.currentClassId);

  const clearState = () => {
    setFileList([]);
    setUploadResult(null);
    abortTracking();
  };

  const keepOnlyFailedFiles = (files, results = []) => {
    return files.filter((_, index) => results[index]?.status !== 'success');
  };

  const summarizeResult = (payload) => {
    const summary = payload?.summary || { total: 0, succeeded: 0, failed: 0 };
    return `${summary.succeeded} succeeded, ${summary.failed} failed.`;
  };

  const handleUpload = async () => {
    if (fileList.length === 0) {
      message.warning('Please select files to upload');
      return;
    }

    const pendingFiles = [...fileList];
    setUploadResult(null);
    setUploading(true);
    const cid = startTracking(genClientId());

    try {
      const response = await uploadMultiple(pendingFiles, cid, currentClassId);
      const payload = response.data;
      setUploadResult(payload);

      if (payload.status === 'success') {
        message.success(`${pendingFiles.length} files uploaded successfully.`);
        setFileList([]);
        onSuccess && onSuccess();
        clearState();
        onCancel();
        return;
      }

      if (payload.status === 'partial') {
        message.warning(`Upload completed with partial success. ${summarizeResult(payload)}`);
        setFileList(keepOnlyFailedFiles(pendingFiles, payload.results));
        onSuccess && onSuccess();
        return;
      }

      message.error(`Upload failed. ${summarizeResult(payload)}`);
      setFileList(keepOnlyFailedFiles(pendingFiles, payload.results));
    } catch (error) {
      console.error('Upload error:', error);
      const payload = error.response?.data;
      if (payload?.results) {
        setUploadResult(payload);
        setFileList(keepOnlyFailedFiles(pendingFiles, payload.results));
        message.error(`Upload failed. ${summarizeResult(payload)}`);
      } else {
        const errorMessage = error.response?.data?.error || error.message || 'Upload failed';
        message.error(`Upload failed: ${errorMessage}`);
      }
    } finally {
      setUploading(false);
      stopTracking(1500);
    }
  };

  const handleCancel = () => {
    clearState();
    onCancel();
  };

  const props = {
    multiple: true,
    onRemove: (file) => {
      setUploadResult(null);
      setFileList((current) => current.filter((item) => item.uid !== file.uid));
    },
    beforeUpload: (file, newFiles) => {
      setUploadResult(null);
      const allFiles = [...fileList, ...newFiles];
      const pdfFiles = allFiles.filter((candidate) => {
        const isPdf = candidate.type === 'application/pdf' || candidate.name?.toLowerCase().endsWith('.pdf');
        if (!isPdf) {
          message.error(`${candidate.name} is not a PDF file and was removed.`);
        }
        return isPdf;
      });

      const uniqueFiles = Array.from(new Map(pdfFiles.map((candidate) => [candidate.uid, candidate])).values());
      setFileList(uniqueFiles);
      return false;
    },
    fileList,
  };

  const progressBarStatus = uploading ? 'active' : progressStatus;
  const resultMeta = STATUS_META[uploadResult?.status] || STATUS_META.failed;

  return (
    <Modal
      title="Upload PDF files"
      open={visible}
      onCancel={handleCancel}
      footer={[
        <Button key="cancel" onClick={handleCancel}>
          Cancel
        </Button>,
        <Button
          key="upload"
          type="primary"
          onClick={handleUpload}
          disabled={fileList.length === 0}
          loading={uploading}
        >
          {uploading ? 'Uploading...' : `Confirm upload ${fileList.length} files`}
        </Button>
      ]}
      width={600}
      destroyOnClose
    >
      <Dragger
        {...props}
        style={{
          border: '2px dashed #d9d9d9',
          borderRadius: '8px',
          padding: '40px 20px',
          background: '#fafafa'
        }}
      >
        <p className="ant-upload-drag-icon">
          <InboxOutlined style={{ color: '#7c3aed', fontSize: '48px' }} />
        </p>
        <p className="ant-upload-text" style={{ fontSize: '18px', color: '#666' }}>
          Click or drag multiple PDF files here
        </p>
        <p className="ant-upload-hint" style={{ color: '#999', marginTop: '8px' }}>
          Supports uploading multiple PDF files. After selecting files, click the confirm button below.
        </p>
      </Dragger>

      {(uploading || showProgress) && (
        <div style={{ marginTop: 16 }}>
          <Progress percent={progress} status={progressBarStatus} />
          {!uploading && finishedEvent?.status === 'partial' && (
            <Text type="secondary">The upload completed with mixed file results.</Text>
          )}
        </div>
      )}

      {uploadResult && (
        <div style={{ marginTop: 16 }}>
          <Alert
            showIcon
            type={resultMeta.alertType}
            message={`${resultMeta.label}: ${summarizeResult(uploadResult)}`}
          />
          <div style={{ marginTop: 12, maxHeight: 220, overflowY: 'auto' }}>
            {uploadResult.results?.map((result, index) => (
              <div
                key={`${result.filename}-${index}`}
                style={{
                  padding: '10px 12px',
                  border: '1px solid #f0f0f0',
                  borderRadius: 8,
                  marginBottom: 8,
                  background: '#fff'
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                  <Tag color={result.status === 'success' ? 'success' : 'error'}>
                    {result.status === 'success' ? 'Success' : 'Failed'}
                  </Tag>
                  <Text strong>{result.filename}</Text>
                </div>
                <Text type="secondary">{result.message}</Text>
                {result.error?.upstream_message && (
                  <div style={{ marginTop: 4 }}>
                    <Text type="secondary">Upstream: {result.error.upstream_message}</Text>
                  </div>
                )}
                {result.error?.code && (
                  <div style={{ marginTop: 4 }}>
                    <Text type="secondary">Code: {result.error.code}</Text>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </Modal>
  );
};

export default UploadModal;
