import matplotlib.pyplot as plt
import numpy as np

# 設定學術風格 (使用 serif 字體看起來更像論文)
plt.rcParams['font.family'] = 'serif'
plt.rcParams['font.size'] = 12

def plot_ragas_results(data, title, filename):
    # 提取數據
    metrics = list(data.keys())
    methods = ['Vector Only', 'Hybrid', 'Full-text Only']
    
    # 準備每個方法的數值
    vector_scores = [data[m][0] for m in metrics]
    hybrid_scores = [data[m][1] for m in metrics]
    fulltext_scores = [data[m][2] for m in metrics]

    # 設定長條圖的位置
    x = np.arange(len(metrics))  # 標籤位置
    width = 0.25  # 長條寬度

    fig, ax = plt.subplots(figsize=(10, 6))
    
    # 繪製長條 (使用專業配色：藍、橘、綠)
    rects1 = ax.bar(x - width, vector_scores, width, label='Vector Only', color='#4472C4', edgecolor='black', linewidth=0.5)
    rects2 = ax.bar(x, hybrid_scores, width, label='Hybrid Search', color='#ED7D31', edgecolor='black', linewidth=0.5)
    rects3 = ax.bar(x + width, fulltext_scores, width, label='Full-text Only', color='#A5A5A5', edgecolor='black', linewidth=0.5)

    # 加入標籤和標題
    ax.set_ylabel('RAGAS Score (0-1)')
    ax.set_title(title, fontweight='bold', pad=20)
    ax.set_xticks(x)
    ax.set_xticklabels([m.replace('_', ' ').title() for m in metrics])
    ax.set_ylim(0, 1.1)  # 設定 Y 軸範圍稍微高一點以容納數值標籤
    ax.legend(loc='lower right') # 圖例位置

    # 在長條上方顯示具體數值
    def autolabel(rects):
        for rect in rects:
            height = rect.get_height()
            ax.annotate(f'{height:.2f}',
                        xy=(rect.get_x() + rect.get_width() / 2, height),
                        xytext=(0, 3),  # 垂直偏移
                        textcoords="offset points",
                        ha='center', va='bottom', fontsize=10)

    autolabel(rects1)
    autolabel(rects2)
    autolabel(rects3)

    # 加入格線方便閱讀
    ax.yaxis.grid(True, linestyle='--', alpha=0.7)
    
    # 調整佈局並存檔
    plt.tight_layout()
    plt.savefig(filename, dpi=300) # 存成高解析度 300dpi
    plt.show()
    print(f"Chart saved as {filename}")

# ==========================================
# 數據輸入 (來自你的截圖 image_646f80.png & image_646f99.png)
# 格式: 'Metric': [Vector, Hybrid, Fulltext]
# ==========================================

# 1. Cross-Lingual Data (Chinese Queries on English Docs)
data_cross_lingual = {
    'context_precision': [0.5829, 0.5011, 0.1357],
    'context_recall':    [0.6567, 0.5967, 0.2400],
    'faithfulness':      [0.8619, 0.8577, 0.8514],
    'answer_relevancy':  [0.6192, 0.5987, 0.2619]
}

# 2. Monolingual Data (English Queries on English Docs)
data_monolingual = {
    'context_precision': [0.4520, 0.5020, 0.5207],
    'context_recall':    [0.6133, 0.6167, 0.5733],
    'faithfulness':      [0.8656, 0.8298, 0.8736],
    'answer_relevancy':  [0.5429, 0.6099, 0.5761]
}


# 執行繪圖
plot_ragas_results(
    data_cross_lingual, 
    'Figure 5.1: Evaluation Results for Cross-Lingual Retrieval (Chinese Queries)', 
    'Figure_5_1_Cross_Lingual_50.png'
)

plot_ragas_results(
    data_monolingual, 
    'Figure 5.2: Evaluation Results for Monolingual Retrieval (English Queries)', 
    'Figure_5_2_Monolingual_50.png'
)