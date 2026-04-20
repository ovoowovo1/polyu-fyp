# -*- coding: utf-8 -*-
"""
圖表生成腳本 - 視覺化 RAG 檢索策略比較結果

此腳本讀取 evaluation/results 目錄下的評估結果 CSV 文件，
生成對比圖表供 FYP 報告使用。

生成的圖表類型：
1. 柱狀圖 - 各指標的對比
2. 雷達圖 - 綜合比較
3. 差異圖 - 顯示兩種方法的差異

執行方式：
    python evaluation/generate_charts.py

可選參數：
    --input     指定輸入的 CSV 文件（預設：最新的 comparison_*.csv）
    --output    指定輸出目錄（預設：evaluation/charts）
"""

import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional, List
import glob

# 將專案根目錄加入 Python 路徑
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

# 設定中文字體
plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False


# ============================================================================
# 圖表配置
# ============================================================================

COLORS = {
    "vector_only": "#3498db",  # 藍色
    "hybrid": "#e74c3c",       # 紅色
    "fulltext_only": "#2ecc71", # 綠色
}

METRIC_LABELS = {
    "context_precision": "Context\nPrecision",
    "context_recall": "Context\nRecall",
    "faithfulness": "Faithfulness",
    "answer_relevancy": "Answer\nRelevancy",
}

METRIC_LABELS_ZH = {
    "context_precision": "上下文精確度",
    "context_recall": "上下文召回率",
    "faithfulness": "忠實度",
    "answer_relevancy": "答案相關性",
}

METHOD_LABELS = {
    "vector_only": "Vector Only",
    "hybrid": "Hybrid (Vector + Text)",
    "fulltext_only": "Fulltext Only (BM25)",
}


# ============================================================================
# 柱狀圖 - 各指標對比
# ============================================================================

def create_bar_chart(
    df: pd.DataFrame,
    output_path: Path,
    methods: List[str] = ["vector_only", "hybrid"]
):
    """
    建立柱狀圖比較各指標
    
    Args:
        df: 評估結果 DataFrame
        output_path: 輸出目錄
        methods: 要比較的方法列表
    """
    metrics = ["context_precision", "context_recall", "faithfulness", "answer_relevancy"]
    available_metrics = [m for m in metrics if m in df.columns]
    
    if not available_metrics:
        print("警告：沒有可用的評估指標數據")
        return
    
    # 計算各方法的平均值
    data = {}
    for method in methods:
        method_df = df[df["retrieval_method"] == method]
        if not method_df.empty:
            data[method] = [method_df[m].mean() for m in available_metrics]
    
    if not data:
        print("警告：沒有可用的數據")
        return
    
    # 繪圖
    fig, ax = plt.subplots(figsize=(12, 6))
    
    x = np.arange(len(available_metrics))
    width = 0.35
    n_methods = len(data)
    
    for i, (method, values) in enumerate(data.items()):
        offset = width * (i - (n_methods - 1) / 2)
        bars = ax.bar(
            x + offset,
            values,
            width,
            label=METHOD_LABELS.get(method, method),
            color=COLORS.get(method, f"C{i}"),
            edgecolor='white',
            linewidth=1
        )
        
        # 在柱狀圖上顯示數值
        for bar, val in zip(bars, values):
            height = bar.get_height()
            ax.annotate(
                f'{val:.3f}',
                xy=(bar.get_x() + bar.get_width() / 2, height),
                xytext=(0, 3),
                textcoords="offset points",
                ha='center', va='bottom',
                fontsize=10,
                fontweight='bold'
            )
    
    ax.set_xlabel('評估指標', fontsize=12, fontweight='bold')
    ax.set_ylabel('分數', fontsize=12, fontweight='bold')
    ax.set_title('RAG 檢索策略比較 - RAGAS 評估指標', fontsize=14, fontweight='bold', pad=20)
    ax.set_xticks(x)
    ax.set_xticklabels([METRIC_LABELS.get(m, m) for m in available_metrics])
    ax.legend(loc='upper right', fontsize=10)
    ax.set_ylim(0, 1.1)
    ax.grid(axis='y', alpha=0.3)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    
    plt.tight_layout()
    
    # 儲存圖片
    chart_path = output_path / "bar_chart_comparison.png"
    plt.savefig(chart_path, dpi=300, bbox_inches='tight', facecolor='white')
    print(f"✓ 柱狀圖已儲存至: {chart_path}")
    
    plt.close()


# ============================================================================
# 雷達圖 - 綜合比較
# ============================================================================

def create_radar_chart(
    df: pd.DataFrame,
    output_path: Path,
    methods: List[str] = ["vector_only", "hybrid"]
):
    """
    建立雷達圖綜合比較
    
    Args:
        df: 評估結果 DataFrame
        output_path: 輸出目錄
        methods: 要比較的方法列表
    """
    metrics = ["context_precision", "context_recall", "faithfulness", "answer_relevancy"]
    available_metrics = [m for m in metrics if m in df.columns]
    
    if len(available_metrics) < 3:
        print("警告：雷達圖需要至少 3 個指標")
        return
    
    # 計算各方法的平均值
    data = {}
    for method in methods:
        method_df = df[df["retrieval_method"] == method]
        if not method_df.empty:
            data[method] = [method_df[m].mean() for m in available_metrics]
    
    if not data:
        return
    
    # 設定雷達圖
    angles = np.linspace(0, 2 * np.pi, len(available_metrics), endpoint=False).tolist()
    angles += angles[:1]  # 閉合圖形
    
    fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))
    
    for method, values in data.items():
        values_closed = values + values[:1]
        ax.plot(
            angles, values_closed,
            'o-', linewidth=2,
            label=METHOD_LABELS.get(method, method),
            color=COLORS.get(method, None)
        )
        ax.fill(angles, values_closed, alpha=0.25, color=COLORS.get(method, None))
    
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels([METRIC_LABELS_ZH.get(m, m) for m in available_metrics], fontsize=11)
    ax.set_ylim(0, 1)
    ax.set_title('RAG 檢索策略綜合比較', fontsize=14, fontweight='bold', pad=20)
    ax.legend(loc='upper right', bbox_to_anchor=(1.3, 1.1))
    
    plt.tight_layout()
    
    chart_path = output_path / "radar_chart_comparison.png"
    plt.savefig(chart_path, dpi=300, bbox_inches='tight', facecolor='white')
    print(f"✓ 雷達圖已儲存至: {chart_path}")
    
    plt.close()


# ============================================================================
# 差異圖 - 顯示改進幅度
# ============================================================================

def create_difference_chart(
    df: pd.DataFrame,
    output_path: Path,
    baseline: str = "vector_only",
    compare: str = "hybrid"
):
    """
    建立差異圖顯示 hybrid 相對於 vector_only 的改進
    
    Args:
        df: 評估結果 DataFrame
        output_path: 輸出目錄
        baseline: 基準方法
        compare: 比較方法
    """
    metrics = ["context_precision", "context_recall", "faithfulness", "answer_relevancy"]
    available_metrics = [m for m in metrics if m in df.columns]
    
    if not available_metrics:
        return
    
    baseline_df = df[df["retrieval_method"] == baseline]
    compare_df = df[df["retrieval_method"] == compare]
    
    if baseline_df.empty or compare_df.empty:
        print("警告：缺少必要的方法數據")
        return
    
    # 計算差異
    differences = []
    for m in available_metrics:
        diff = compare_df[m].mean() - baseline_df[m].mean()
        differences.append(diff)
    
    # 繪圖
    fig, ax = plt.subplots(figsize=(10, 6))
    
    colors = ['#2ecc71' if d >= 0 else '#e74c3c' for d in differences]
    
    bars = ax.barh(
        range(len(available_metrics)),
        differences,
        color=colors,
        edgecolor='white',
        linewidth=1
    )
    
    ax.set_yticks(range(len(available_metrics)))
    ax.set_yticklabels([METRIC_LABELS_ZH.get(m, m) for m in available_metrics])
    ax.set_xlabel('分數差異 (Hybrid - Vector Only)', fontsize=12)
    ax.set_title(f'Hybrid vs Vector Only 改進幅度', fontsize=14, fontweight='bold', pad=20)
    ax.axvline(x=0, color='black', linewidth=0.5)
    ax.grid(axis='x', alpha=0.3)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    
    # 添加數值標籤
    for bar, diff in zip(bars, differences):
        width = bar.get_width()
        ax.annotate(
            f'{diff:+.4f}',
            xy=(width, bar.get_y() + bar.get_height() / 2),
            xytext=(5 if width >= 0 else -5, 0),
            textcoords="offset points",
            ha='left' if width >= 0 else 'right',
            va='center',
            fontsize=11,
            fontweight='bold'
        )
    
    plt.tight_layout()
    
    chart_path = output_path / "difference_chart.png"
    plt.savefig(chart_path, dpi=300, bbox_inches='tight', facecolor='white')
    print(f"✓ 差異圖已儲存至: {chart_path}")
    
    plt.close()


# ============================================================================
# 箱形圖 - 分數分佈
# ============================================================================

def create_box_plot(
    df: pd.DataFrame,
    output_path: Path,
    methods: List[str] = ["vector_only", "hybrid"]
):
    """
    建立箱形圖顯示分數分佈
    
    Args:
        df: 評估結果 DataFrame
        output_path: 輸出目錄
        methods: 要比較的方法列表
    """
    metrics = ["context_precision", "context_recall", "faithfulness", "answer_relevancy"]
    available_metrics = [m for m in metrics if m in df.columns]
    
    if not available_metrics:
        return
    
    fig, axes = plt.subplots(1, len(available_metrics), figsize=(4 * len(available_metrics), 6))
    
    if len(available_metrics) == 1:
        axes = [axes]
    
    for i, metric in enumerate(available_metrics):
        data = []
        labels = []
        
        for method in methods:
            method_df = df[df["retrieval_method"] == method]
            if not method_df.empty and metric in method_df.columns:
                data.append(method_df[metric].dropna().values)
                labels.append(METHOD_LABELS.get(method, method))
        
        if data:
            bp = axes[i].boxplot(data, labels=labels, patch_artist=True)
            
            for j, (patch, method) in enumerate(zip(bp['boxes'], methods)):
                patch.set_facecolor(COLORS.get(method, f"C{j}"))
                patch.set_alpha(0.7)
            
            axes[i].set_title(METRIC_LABELS_ZH.get(metric, metric), fontsize=12, fontweight='bold')
            axes[i].set_ylim(0, 1.1)
            axes[i].grid(axis='y', alpha=0.3)
            axes[i].tick_params(axis='x', rotation=45)
    
    plt.suptitle('各指標分數分佈比較', fontsize=14, fontweight='bold', y=1.02)
    plt.tight_layout()
    
    chart_path = output_path / "box_plot_comparison.png"
    plt.savefig(chart_path, dpi=300, bbox_inches='tight', facecolor='white')
    print(f"✓ 箱形圖已儲存至: {chart_path}")
    
    plt.close()


# ============================================================================
# 主函數
# ============================================================================

def find_latest_csv(results_dir: Path) -> Optional[Path]:
    """找到最新的評估結果 CSV 文件"""
    csv_files = list(results_dir.glob("comparison_*.csv"))
    if not csv_files:
        return None
    return max(csv_files, key=lambda p: p.stat().st_mtime)


def generate_all_charts(input_file: str, output_dir: str):
    """
    生成所有圖表
    
    Args:
        input_file: 輸入 CSV 文件路徑
        output_dir: 輸出目錄
    """
    print("\n" + "=" * 50)
    print("   RAG 檢索策略比較 - 圖表生成")
    print("=" * 50 + "\n")
    
    input_path = Path(input_file)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    if not input_path.exists():
        print(f"❌ 找不到輸入文件: {input_path}")
        return
    
    print(f"📖 讀取數據: {input_path}")
    df = pd.read_csv(input_path)
    
    if df.empty:
        print("❌ CSV 文件為空")
        return
    
    # 獲取可用的方法
    methods = df["retrieval_method"].unique().tolist() if "retrieval_method" in df.columns else []
    print(f"📊 找到方法: {methods}")
    print(f"📈 樣本數量: {len(df)}")
    print()
    
    # 生成各種圖表
    print("正在生成圖表...\n")
    
    try:
        create_bar_chart(df, output_path, methods)
    except Exception as e:
        print(f"⚠️ 柱狀圖生成失敗: {e}")
    
    try:
        create_radar_chart(df, output_path, methods)
    except Exception as e:
        print(f"⚠️ 雷達圖生成失敗: {e}")
    
    if len(methods) >= 2:
        try:
            create_difference_chart(df, output_path, methods[0], methods[1])
        except Exception as e:
            print(f"⚠️ 差異圖生成失敗: {e}")
    
    try:
        create_box_plot(df, output_path, methods)
    except Exception as e:
        print(f"⚠️ 箱形圖生成失敗: {e}")
    
    print(f"\n✅ 所有圖表已生成至: {output_path}")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="生成 RAG 比較圖表")
    parser.add_argument(
        "--input", "-i",
        type=str,
        default=None,
        help="輸入 CSV 文件路徑（預設：最新的 comparison_*.csv）"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default="evaluation/charts",
        help="輸出目錄"
    )
    
    args = parser.parse_args()
    
    script_dir = Path(__file__).parent
    
    # 找到輸入文件
    if args.input:
        input_path = Path(args.input)
        if not input_path.is_absolute():
            input_path = script_dir / args.input
    else:
        results_dir = script_dir / "results"
        input_path = find_latest_csv(results_dir)
        if not input_path:
            print("❌ 找不到評估結果文件")
            print("請先執行 python evaluation/run_comparison.py 進行評估")
            sys.exit(1)
    
    # 設定輸出目錄
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = script_dir / args.output
    
    generate_all_charts(str(input_path), str(output_path))


if __name__ == "__main__":
    main()
