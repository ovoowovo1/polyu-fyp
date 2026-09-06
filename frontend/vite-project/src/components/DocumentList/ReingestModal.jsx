import React, { useState } from 'react';
import { Alert, Modal, Progress, Upload, Button } from 'antd';
import { useDispatch } from 'react-redux';
import { useTranslation } from 'react-i18next';
import { reingestPdf } from '../../api/upload.js';
import useUploadProgress from '../../hooks/useUploadProgress.jsx';
import { refreshReingestedDocument } from '../../redux/documentSlice.js';

export default function ReingestModal({ document, onClose }) {
    const { t } = useTranslation();
    const dispatch = useDispatch();
    const [file, setFile] = useState(null);
    const [running, setRunning] = useState(false);
    const [result, setResult] = useState(null);
    const [error, setError] = useState('');
    const { progress, startTracking, abortTracking } = useUploadProgress();
    const submit = async () => {
        setRunning(true);
        setError('');
        const clientId = startTracking();
        try {
            const response = await reingestPdf(document.id, file, clientId);
            setResult(response.data);
            await dispatch(refreshReingestedDocument(document.id));
        } catch (failure) {
            const detail = failure.response?.data?.detail;
            setError(typeof detail === 'string' ? detail : detail?.error || failure.message);
        } finally {
            abortTracking();
            setRunning(false);
        }
    };
    return <Modal open title={t('documents.reingest')} onCancel={onClose} closable={!running}
        maskClosable={!running} cancelButtonProps={{ disabled: running }}
        okText={result ? t('common.close') : t('documents.reingest')}
        okButtonProps={{ disabled: !file && !result }} confirmLoading={running}
        onOk={result ? onClose : submit}>
        <p>{document.filename}</p>
        <p>{t('documents.reingestHint')}</p>
        <Upload accept=".pdf,application/pdf" maxCount={1} disabled={running || !!result}
            beforeUpload={(selected) => { setFile(selected); return false; }} onRemove={() => setFile(null)}>
            <Button>{t('documents.chooseOriginalPdf')}</Button>
        </Upload>
        {running && <Progress percent={progress} status="active" />}
        {error && <Alert type="error" message={error} />}
        {result && <Alert type="success" message={t('documents.reingestComplete', { count: result.chunksCount })} />}
    </Modal>;
}
