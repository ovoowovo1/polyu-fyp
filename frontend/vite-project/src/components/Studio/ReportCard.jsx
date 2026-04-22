import React, { useState } from 'react'
import { generateQuiz } from '../../api/quiz'
import { message, Modal, InputNumber, Radio } from 'antd'
import { useSelector } from 'react-redux'
import { Card, Typography } from 'antd'

export default function ReportCard() {
    const { Title } = Typography;
    return (
        <>

            <Card
                style={{ backgroundColor: '#f2f2e8' }}
                className="hover:bg-green-200 cursor-pointer hover:brightness-95 "
                styles={{ body: { padding: '0.5rem', backgroundColor: 'transparent' } }}
            //onClick={() => handleGenerateQuiz()}
            //loading={loading}
            >
                <div className="flex justify-between">
                    <span className="material-symbols-outlined" style={{ color: '#796731' }}>files</span>

                    <span
                        className="material-symbols-outlined "
                        style={{ color: '#796731' }}
                        onClick={(e) => {
                            e.stopPropagation();
                            //setOpen(true);
                        }}
                    >edit</span>

                </div>
                <Title level={5} style={{ color: '#796731', marginTop: '1rem' }}>
                    Report
                </Title>
            </Card>



        </>
    )
}
