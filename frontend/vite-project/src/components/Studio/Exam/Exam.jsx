import React, { useState } from 'react'
import {
  Input,
  Button,
  Modal,
  Select,
  Form,
  InputNumber,
  Radio,
  Collapse,
  List,
  Card,
  Space,
  Typography,
  Tag,
  Tooltip,
} from 'antd'

const { Title, Text } = Typography
const { Option } = Select
const { Panel } = Collapse

export default function Exam() {
  const [examTitle, setExamTitle] = useState('New Exam')
  const [durationMin, setDurationMin] = useState(60)
  const [questions, setQuestions] = useState([])

  const [isModalOpen, setIsModalOpen] = useState(false)
  const [editingQuestion, setEditingQuestion] = useState(null)

  // form fields for question editor
  const [qType, setQType] = useState('multiple-choice')
  const [qText, setQText] = useState('')
  const [qMarks, setQMarks] = useState(1)
  const [options, setOptions] = useState(['', ''])
  const [rubric, setRubric] = useState('')

  function openAddModal() {
    setEditingQuestion(null)
    setQType('multiple-choice')
    setQText('')
    setQMarks(1)
    setOptions(['', ''])
    setRubric('')
    setIsModalOpen(true)
  }

  function openEditModal(q) {
    setEditingQuestion(q.id)
    setQType(q.type)
    setQText(q.text)
    setQMarks(q.maxMarks ?? 1)
    setOptions(q.options ?? ['',''])
    setRubric(q.rubric ?? '')
    setIsModalOpen(true)
  }

  function saveQuestion() {
    const q = {
      id: editingQuestion || `${Date.now()}-${Math.floor(Math.random()*1000)}`,
      type: qType,
      text: qText,
      options: qType === 'multiple-choice' ? options.filter(o => o.trim() !== '') : undefined,
      maxMarks: Number(qMarks) || 0,
      rubric: rubric,
    }

    setQuestions(prev => {
      const exists = prev.find(p => p.id === q.id)
      if (exists) {
        return prev.map(p => (p.id === q.id ? q : p))
      }
      return [...prev, q]
    })

    setIsModalOpen(false)
  }

  function removeQuestion(id) {
    setQuestions(prev => prev.filter(p => p.id !== id))
  }

  function addOption() {
    setOptions(prev => [...prev, ''])
  }

  function changeOption(idx, value) {
    setOptions(prev => {
      const copy = [...prev]
      copy[idx] = value
      return copy
    })
  }

  function exportJSON() {
    const payload = {
      title: examTitle,
      durationMin,
      questions,
    }
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${examTitle.replace(/\s+/g,'_') || 'exam'}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="p-4">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>Exam Builder</Title>
          <Text type="secondary">教師可建立考卷、題目與基本評分規則</Text>
        </div>
        <Space>
          <Button key="add" type="primary" onClick={openAddModal}>
            + 新增題目
          </Button>
        </Space>
      </div>

      <Card className="mt-4">
        <Form layout="vertical">
          <Form.Item label="考卷標題">
            <Input value={examTitle} onChange={e => setExamTitle(e.target.value)} />
          </Form.Item>
          <Form.Item label="時限 (分鐘)">
            <InputNumber min={1} value={durationMin} onChange={value => setDurationMin(value)} />
          </Form.Item>
        </Form>

        <div className="mt-6">
          <Title level={5}>題目清單</Title>
          {questions.length === 0 ? (
            <Text type="secondary">目前沒有題目，請按「新增題目」。</Text>
          ) : (
            <List
              dataSource={questions}
              renderItem={item => (
                <List.Item
                  actions={[
                    <Button key="edit" type="link" onClick={() => openEditModal(item)}>編輯</Button>,
                    <Button key="del" type="link" danger onClick={() => removeQuestion(item.id)}>刪除</Button>,
                  ]}
                >
                  <List.Item.Meta
                    title={<div><Text strong>{item.text}</Text> <Tag color="blue" style={{ marginLeft: 8 }}>{item.type}</Tag></div>}
                    description={<div>分數: {item.maxMarks} &nbsp; {item.options ? <span>選項: {item.options.length}</span> : null}</div>}
                  />
                </List.Item>
              )}
            />
          )}
        </div>
      </Card>

      <Modal
        title={editingQuestion ? '編輯題目' : '新增題目'}
        open={isModalOpen}
        onOk={saveQuestion}
        onCancel={() => setIsModalOpen(false)}
        width={800}
      >
        <Form layout="vertical">
          <Form.Item label="題型">
            <Select value={qType} onChange={val => setQType(val)}>
              <Option value="multiple-choice">選擇題 (Multiple Choice)</Option>
              <Option value="fill-in-the-blank">填空題 (Fill in the blank)</Option>
              <Option value="short-answer">簡答題 (Short Answer)</Option>
              <Option value="long-answer">長答題 (Long Answer)</Option>
            </Select>
          </Form.Item>

          <Form.Item label="題幹">
            <Input.TextArea rows={3} value={qText} onChange={e => setQText(e.target.value)} />
          </Form.Item>

          <Form.Item label="最大分數">
            <InputNumber min={0} value={qMarks} onChange={v => setQMarks(v)} />
          </Form.Item>

          {qType === 'multiple-choice' && (
            <>
              <Form.Item label="選項">
                {options.map((opt, idx) => (
                  <Input
                    key={idx}
                    value={opt}
                    onChange={e => changeOption(idx, e.target.value)}
                    placeholder={`選項 ${idx + 1}`}
                    style={{ marginBottom: 8 }}
                  />
                ))}
                <Button type="dashed" onClick={addOption}>新增選項</Button>
              </Form.Item>
            </>
          )}

          <Form.Item label="評分規則 / Rubric (給 LLM 或教師參考)">
            <Input.TextArea rows={4} value={rubric} onChange={e => setRubric(e.target.value)} placeholder="例如：要點 A -> 2 分；要點 B -> 1 分；語意相似可給部分分" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
