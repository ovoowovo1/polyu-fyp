import React, { memo } from "react";
import { useDispatch } from "react-redux";
// Update the import path below to wherever your action lives
import { toggleStudioCardCollapse } from '../../redux/studioSlice'
import { RobotOutlined } from "@ant-design/icons";

const IconPill = memo(function IconPill({ bg, color, icon, label, onClick }) {
    return (
        <button
            type="button"
            aria-label={label}
            title={label}
            onClick={onClick}
            className="mt-2 inline-flex h-9 w-9 items-center justify-center rounded-full p-1 shadow-sm transition active:scale-95 hover:brightness-95 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-black/10"
            style={{ backgroundColor: bg }}
        >
            <span className="material-symbols-outlined text-[20px]" style={{ color }}>
                {icon}
            </span>
        </button>
    );
});


export default function CollapsedIcon() {
    const dispatch = useDispatch();


    const handleToggle = () => dispatch(toggleStudioCardCollapse());


    const ACTIONS = [
       // { bg: "#edeffa", color: "#224484", icon: "graphic_eq", label: "Audio" },
       // { bg: "#E1F1E5", color: "#23633C", icon: "video_library", label: "Videos" },
       // { bg: "#F0E9EF", color: "#8E659A", icon: "flowchart", label: "Flowchart" },
       // { bg: "#F2F2E8", color: "#796731", icon: "files", label: "Files" },
       // { bg: "#f7edeb", color: "#8c2e2a", icon: "cards_star", label: "Featured" },
        { bg: "#ecfccb", color: "#4d7c0f", icon: "quiz", label: "Quiz" }, // lime-100 / lime-600
        { bg: "#f3e8ff", color: "#7e22ce", icon: <RobotOutlined />, label: "AI exam" }, // violet-100 / violet-600
    ];


    return (
        <div className="flex flex-col">
            {ACTIONS.map((a) => (
                <IconPill
                    key={a.icon}
                    bg={a.bg}
                    color={a.color}
                    icon={a.icon}
                    label={a.label}
                    onClick={handleToggle}
                />
            ))}
        </div>
    );
}