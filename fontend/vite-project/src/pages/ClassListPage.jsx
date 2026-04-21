import React, { useState, useEffect, useRef } from 'react'
import { Card, Typography, Button, Modal, Form, Input, message, Tag, Empty, Skeleton, Row, Col, Avatar, Space, Tooltip } from 'antd';
import { TeamOutlined, CalendarOutlined, ArrowRightOutlined } from '@ant-design/icons';
import { listMyClasses, listMyEnrolledClasses, createClass } from '../api/classes';
import { useNavigate } from 'react-router-dom';
import { getCurrentUser } from '../api/auth';
import DocumentsTopBar from '../components/DocumentsTopBar';
import { useTranslation } from 'react-i18next';
// ProfileMenu is provided by DocumentsTopBar

export default function ClassListPage() {
	const { t } = useTranslation();
	const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
	const [form] = Form.useForm();
	const [classes, setClasses] = useState([]);
	const [loading, setLoading] = useState(false);
	const hasFetchedRef = useRef(false);
	const navigate = useNavigate();
	const user = getCurrentUser();
	const isTeacher = user?.role === 'teacher';

	// handleLogout is provided in DocumentsTopBar
	const [search, setSearch] = useState('');

	const openCreateModal = () => setIsCreateModalOpen(true);
	const closeCreateModal = () => {
		setIsCreateModalOpen(false);
		form.resetFields();
	};
	const fetchClasses = async () => {
		try {
			setLoading(true);
			const res = isTeacher ? await listMyClasses() : await listMyEnrolledClasses();
			setClasses(res.classes || []);
		} catch (err) {
			message.error(err.message || t('classes.loadClassesFailed'));
		} finally {
			setLoading(false);
		}
	};

	useEffect(() => {
		if (hasFetchedRef.current) return;
		hasFetchedRef.current = true;
		fetchClasses();
	}, []);

	const filteredClasses = (classes || []).filter(c => {
		const q = (search || '').toLowerCase();
		return c.name?.toLowerCase().includes(q);
	});

	const handleCreate = async (values) => {
		try {
			await createClass(values.className);
			message.success(t('classes.classCreated'));
			closeCreateModal();
			fetchClasses();
		} catch (err) {
			message.error(err.message || t('classes.createClassFailed'));
		}
	};
	return (
		<>
			<div className={"min-h-screen bg-gray-100 flex flex-col"}>
				<DocumentsTopBar title={t('classes.title')} showClassesList={false} />

				<Card className='m-4'>
					<div className="p-4">

						<div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
							<div>
								<div className='text-sm text-gray-500 mt-1'>{t('classes.manageClasses')}</div>
							</div>

							<div className="flex items-center gap-2">
								<Input.Search
									allowClear
									placeholder={t('classes.searchPlaceholder')}
									className="w-60"
									value={search}
									onChange={(e) => setSearch(e.target.value)}
									onSearch={(v) => setSearch(v)}
								/>
								{isTeacher && (<Button type="primary" onClick={openCreateModal}>{t('classes.createClass')}</Button>)}
							</div>
						</div>

						<div className="mt-6">
							{loading && (
								<Row gutter={[16, 16]}>
									{Array.from({ length: 8 }).map((_, i) => (
										<Col key={`s-${i}`} xs={24} sm={12} md={8} lg={6} xl={4}>
											<Card className='w-full'>
												<Skeleton active paragraph={{ rows: 2 }} />
											</Card>
										</Col>
									))}
								</Row>
							)}

							{!loading && filteredClasses.length === 0 && (
								<div className='col-span-full flex justify-center py-10'>
									<Empty description={<span>{t('classes.noClasses')}</span>}>
										{isTeacher ? (
											<Button type="primary" onClick={openCreateModal}>{t('classes.createFirstClass')}</Button>
										) : (
											<div className='text-sm text-gray-500'>{t('classes.pleaseAskTeacher')}</div>
										)}
									</Empty>
								</div>
							)}

							{!loading && filteredClasses.length > 0 && (
								<Row gutter={[16, 16]}>
									{filteredClasses.map((c, i) => (
										<Col key={c.id} xs={24} sm={12} md={8} lg={6} xl={4}>
											<Card
												hoverable
												key={c.id}
												onClick={() => navigate(`/documents/${c.id}`)}
											>
												<div className='flex items-start gap-3'>
													<Avatar size={48} style={{ backgroundColor: '#3b82f6' }} icon={<TeamOutlined />} />
													<div className='flex-1 min-w-0'>
														<Space direction="vertical" size={2} style={{ width: '100%' }}>
															<div className='flex items-center justify-between'>
																{/* allow title to truncate on small screens */}
																<Typography.Title level={5} className='!mb-0 !text-gray-800 truncate'>{c.name}</Typography.Title>
																<Tooltip title={t('classes.openClass')}>
																	<ArrowRightOutlined className='text-gray-400' />
																</Tooltip>
															</div>
															{/* prevent long IDs from wrapping and breaking layout */}
															<div className='text-sm text-gray-500 truncate'>{t('common.id')}: {c.id}</div>
														</Space>
													</div>
												</div>

												<div className='flex items-center justify-between mt-4'>
													<Tag color="blue"><TeamOutlined /> {` ${c.student_count ?? 0} ${t('classes.students')}`}</Tag>
													<div className='text-gray-500 text-sm flex items-center gap-1'>
														<CalendarOutlined />
														{c.created_at ? new Date(c.created_at).toLocaleDateString() : ''}
													</div>
												</div>
											</Card>
										</Col>
									))}
								</Row>
							)}
						</div>

						<Modal
							title={t('classes.createClass')}
							open={isCreateModalOpen}
							onOk={() => form.submit()}
							onCancel={closeCreateModal}
							okText={t('common.create')}
							centered
							destroyOnHidden
						>
							<Form layout="vertical" form={form} onFinish={handleCreate}>
								<Form.Item
									name="className"
									label={t('classes.className')}
									rules={[{ required: true, message: t('classes.classNameRequired') }]}
								>
									<Input placeholder={t('classes.classNamePlaceholder')} autoFocus />
								</Form.Item>
							</Form>
						</Modal>

					</div>
				</Card>
			</div>
		</>
	)
}
