import React, { useState } from 'react'
import { generateQuiz } from '../../api/quiz'
import { message, Modal, InputNumber, Radio } from 'antd'
import { useSelector } from 'react-redux'
import { Card, Typography } from 'antd'




export default function QuizCard({ onQuizGenerated }) {
    const { Title } = Typography;
    const { selectedFileIds } = useSelector((state) => state.documents);
    const [loading, setLoading] = useState(false);

    // Modal
    const [open, setOpen] = useState(false);
    const [confirmLoading, setConfirmLoading] = useState(false);
    const [difficulty, setDifficulty] = useState('medium');
    const [numQuestions, setNumQuestions] = useState(10);


    const handleGenerateQuiz = async (difficulty = 'medium', numQuestions = 10) => {
        // Check if any files are selected
        if (!selectedFileIds || selectedFileIds.length === 0) {
            message.warning('Please select at least one file to generate quiz');
            return;
        }

        //console.log('Generate Quiz Parameters:', { difficulty, numQuestions, selectedFileIds });

        setLoading(true);
        try {
            const response = await generateQuiz(selectedFileIds, {
                difficulty: difficulty,
                numQuestions: numQuestions
            });

            message.success(`Successfully generated ${response.data.questions.length} quiz questions!`);
            //console.log('生成的測驗:', response.data);

            // Notify parent component to refresh list
            if (onQuizGenerated) {
                onQuizGenerated();
            }

        } catch (error) {
            //console.error('生成測驗失敗:', error);
            message.error(error.response?.data?.detail || 'Generate Quiz Failed, Please try again later');
        } finally {
            setLoading(false);
        }
    };



    const handleOk = () => {
        handleGenerateQuiz(difficulty, numQuestions);
        setOpen(false);
    };


    const handleCancel = () => {
        console.log('Clicked cancel button');
        setOpen(false);
    };


    return (
        <>
            <Card
                className="bg-green-100 hover:bg-green-200 cursor-pointer"
                styles={{ body: { padding: '0.5rem', backgroundColor: 'transparent' } }}
                onClick={() => handleGenerateQuiz()}
                loading={loading}
            >
                <div className="flex justify-between">
                    <span className="material-symbols-outlined text-lime-600">quiz</span>

                    <span className="material-symbols-outlined text-lime-600"
                        onClick={(e) => {
                            e.stopPropagation();
                            setOpen(true);
                        }}
                    >edit</span>

                </div>
                <Title level={5} style={{ color: '#65a30d', marginTop: '1rem' }}>
                    Quiz
                </Title>
            </Card>

            <Modal
                title="Custom Quiz"
                open={open}
                onOk={handleOk}
                confirmLoading={confirmLoading}
                onCancel={handleCancel}
                cancelText="Cancel"
                okText="Generate"
            >

                <div className="grid  grid-cols-2  grid-rows-2 gap-1">
                    <div>
                        Number of Questions
                    </div>

                    <div>
                        Difficulty
                    </div>

                    <div>
                        {/* Number of Questions */}
                        <InputNumber
                            defaultValue={10}
                            min={1} max={100}
                            onChange={(value) => setNumQuestions(value)}
                        />

                    </div>

                    <div>
                        {/* Difficulty */}
                        <Radio.Group
                            optionType="button"
                            buttonStyle="solid"
                            defaultValue="medium"
                            value={difficulty}
                            options={[
                                { label: 'Easy', value: 'easy' },
                                { label: 'Medium', value: 'medium' },
                                { label: 'Difficult', value: 'difficult' },
                            ]}
                            onChange={e => setDifficulty(e.target.value)}
                        />

                    </div>


                </div>





            </Modal>

        </>
    )
}
