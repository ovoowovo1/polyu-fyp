import React, { useState } from 'react'
import { generateQuiz } from '../../api/quiz'
import { message, Modal, InputNumber, Radio } from 'antd'
import { useSelector } from 'react-redux'
import { Card, Typography } from 'antd'

export default function VideoCard() {
    const { Title } = Typography;
    return (
        <>

            <Card
                style={{ backgroundColor: '#E1F1E5' }}
                className="hover:bg-green-200 cursor-pointer hover:brightness-95 "
                styles={{ body: { padding: '0.5rem', backgroundColor: 'transparent' } }}
            //onClick={() => handleGenerateQuiz()}
            //loading={loading}
            >
                <div className="flex justify-between">
                    <span className="material-symbols-outlined" style={{ color: '#23633C' }}>video_library</span>

                    <span
                        className="material-symbols-outlined "
                        style={{ color: '#23633C' }}
                        onClick={(e) => {
                            e.stopPropagation();
                            //setOpen(true);
                        }}
                    >edit</span>

                </div>
                <Title level={5} style={{ color: '#23633C', marginTop: '1rem' }}>
                    Video
                </Title>
            </Card>



        </>
    )
}
