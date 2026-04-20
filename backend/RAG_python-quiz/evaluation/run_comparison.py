# -*- coding: utf-8 -*-
"""
RAGAS 評估比較腳本 - 比較 Vector Only vs Hybrid (Vector + Text) 檢索

此腳本執行以下步驟：
1. 讀取 test_queries_template.json 中的測試問題
2. 對每個問題分別使用兩種檢索策略獲取上下文
3. 使用 LLM 生成答案
4. 使用 RAGAS 計算評估指標
5. 將結果儲存為 CSV 和 JSON 格式

執行方式：
    python evaluation/run_comparison.py

可選參數：
    --input     指定輸入的測試問題文件（預設：test_queries_template.json）
    --output    指定輸出目錄（預設：evaluation/results）
    --k         每種檢索返回的結果數量（預設：10）
"""

import os
import sys
import json
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path

# 將專案根目錄加入 Python 路徑
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.table import Table

# 本地模組
from evaluation.retrieval_compare import (
    vector_only_search,
    hybrid_search_rrf,
    fulltext_only_search,
    format_contexts
)
from evaluation.ragas_config import get_ragas_llm, get_ragas_embeddings

# RAGAS 相關
from ragas import evaluate
from ragas.metrics import (
    context_precision,
    context_recall,
    faithfulness,
    answer_relevancy,
)
from ragas import EvaluationDataset, SingleTurnSample

# LLM 用於生成答案
from openai import OpenAI
from app.utils.dev_credentials import MissingCredentialError, get_eval_llm_credentials

console = Console()


# ============================================================================
# 答案生成
# ============================================================================

async def generate_answer(question: str, contexts: List[str]) -> str:
    """
    使用 LLM 根據上下文生成答案
    
    Args:
        question: 問題
        contexts: 上下文列表
    
    Returns:
        生成的答案
    """
    context_text = "\n\n---\n\n".join(contexts)
    
    prompt = f"""根據以下上下文回答問題。如果上下文中沒有相關資訊，請說明無法回答。

上下文：
{context_text}

問題：{question}

請用中文回答："""

    try:
        credentials = get_eval_llm_credentials()
        client = OpenAI(api_key=credentials.api_key, base_url=credentials.base_url)
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=credentials.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            timeout=60,
        )
        answer = response.choices[0].message.content.strip()
        # 確保答案不為空
        if not answer:
            return "無法根據提供的上下文生成答案。"
        return answer
    except MissingCredentialError:
        raise
    except Exception as e:
        console.print(f"[red]生成答案時發生錯誤: {e}[/red]")
        return f"生成失敗，錯誤: {str(e)}"


# ============================================================================
# 單次評估運行
# ============================================================================

async def run_single_evaluation(
    question: str,
    ground_truth: str,
    file_ids: List[str],
    retrieval_method: str,
    k: int = 10
) -> Dict[str, Any]:
    """
    對單個問題執行評估
    
    Args:
        question: 測試問題
        ground_truth: 預期答案
        file_ids: 限定的文檔 ID
        retrieval_method: 檢索方法 ("vector_only" 或 "hybrid")
        k: 檢索結果數量
    
    Returns:
        評估結果字典
    """
    # 根據方法選擇檢索策略
    if retrieval_method == "vector_only":
        results = await vector_only_search(question, file_ids, k)
    elif retrieval_method == "hybrid":
        results = await hybrid_search_rrf(question, file_ids, k)
    elif retrieval_method == "fulltext_only":
        results = await fulltext_only_search(question, file_ids, k)
    else:
        raise ValueError(f"未知的檢索方法: {retrieval_method}")
    
    # 格式化上下文
    contexts = format_contexts(results)
    
    if not contexts:
        contexts = ["[無檢索結果]"]
    
    # 生成答案
    answer = await generate_answer(question, contexts)
    
    return {
        "question": question,
        "ground_truth": ground_truth,
        "contexts": contexts,
        "answer": answer,
        "retrieval_method": retrieval_method,
        "num_results": len(results),
    }


# ============================================================================
# RAGAS 評估
# ============================================================================

def run_ragas_evaluation(
    samples: List[Dict[str, Any]], 
    skip_answer_relevancy: bool = False,
    verbose: bool = True,
    batch_size: int = 10
) -> pd.DataFrame:
    """
    使用 RAGAS 評估樣本（序列批次處理）
    
    Args:
        samples: 評估樣本列表
        skip_answer_relevancy: 是否跳過 answer_relevancy 指標（避免 embedding 錯誤）
        verbose: 是否顯示詳細日誌
        batch_size: 每個批次的樣本數，序列處理（保留 timeout 原設定）
    
    Returns:
        包含評估結果的 DataFrame
    """
    console.print("\n[bold cyan]🔍 開始 RAGAS 評估（批次、序列處理）...[/bold cyan]\n")
    
    # 詳細日誌：顯示樣本資訊
    if verbose:
        console.print(f"[dim]📋 評估樣本數量: {len(samples)}[/dim]")
        for i, sample in enumerate(samples):
            console.print(f"[dim]  [{i+1}] 問題: {sample['question'][:50]}...[/dim]")
            console.print(f"[dim]      答案長度: {len(sample['answer'])} 字元[/dim]")
            console.print(f"[dim]      上下文數量: {len(sample['contexts'])}[/dim]")
    
    # 轉換為 RAGAS 格式
    ragas_samples = []
    for i, sample in enumerate(samples):
        # 驗證資料完整性
        if not sample["question"]:
            console.print(f"[red]❌ 樣本 {i+1} 缺少問題[/red]")
            raise ValueError(f"樣本 {i+1} 缺少問題")
        if not sample["answer"]:
            console.print(f"[yellow]⚠️ 樣本 {i+1} 缺少答案，使用默認值[/yellow]")
            sample["answer"] = "[答案生成失敗或為空]"
        if not sample["contexts"]:
            console.print(f"[yellow]⚠️ 樣本 {i+1} 沒有上下文，將使用空列表[/yellow]")
        
        ragas_samples.append(
            SingleTurnSample(
                user_input=sample["question"],
                response=sample["answer"],
                reference=sample["ground_truth"],
                retrieved_contexts=sample["contexts"] if sample["contexts"] else ["[無上下文]"],
            )
        )
    
    # 獲取配置的 LLM 和 Embeddings
    llm = None
    embeddings = None
    
    try:
        console.print("[dim]🔧 配置 LLM...[/dim]")
        llm = get_ragas_llm()
        console.print("[green]✓ LLM 配置成功[/green]")
    except Exception as e:
        console.print(f"[red]❌ LLM 配置失敗: {e}[/red]")
        raise RuntimeError(f"LLM 配置失敗: {e}")
    
    try:
        console.print("[dim]🔧 配置 Embeddings...[/dim]")
        embeddings = get_ragas_embeddings()
        console.print("[green]✓ Embeddings 配置成功[/green]")
        
        # 測試 embedding 連接
        if verbose:
            console.print("[dim]🧪 測試 Embedding API 連接...[/dim]")
            test_result = embeddings.embed_query("test")
            console.print(f"[green]✓ Embedding 測試成功，向量維度: {len(test_result)}[/green]")
    except Exception as e:
        console.print(f"[yellow]⚠️ Embeddings 配置失敗: {e}[/yellow]")
        console.print("[yellow]   將跳過 answer_relevancy 指標[/yellow]")
        embeddings = None
        skip_answer_relevancy = True
    
    # 定義評估指標
    if skip_answer_relevancy:
        console.print("[yellow]⚠️ 跳過 answer_relevancy 指標（需要 Embeddings）[/yellow]")
        metrics = [
            context_precision,
            context_recall,
            faithfulness,
        ]
    else:
        metrics = [
            context_precision,
            context_recall,
            faithfulness,
            answer_relevancy,
        ]
    
    console.print(f"[dim]📊 使用指標: {[m.name for m in metrics]}[/dim]")
    
    # 序列批次處理：將 ragas_samples 切成多個小批次，逐批 evaluate
    try:
        console.print("[dim]🚀 開始執行評估（序列批次處理；超時仍由 LLM/Embeddings 設定控制）...[/dim]\n")
        dfs = []
        total = len(ragas_samples)
        if total == 0:
            console.print("[yellow]⚠️ 沒有可用的 RAGAS 樣本，跳過評估[/yellow]")
            return pd.DataFrame()
        
        for start in range(0, total, batch_size):
            end = min(start + batch_size, total)
            console.print(f"[dim]➡️ 處理第 {start+1}-{end} / {total}（每批 {batch_size}）[/dim]")
            batch_samples = ragas_samples[start:end]
            batch_dataset = EvaluationDataset(samples=batch_samples)
            
            if llm and embeddings:
                result = evaluate(
                    dataset=batch_dataset,
                    metrics=metrics,
                    llm=llm,
                    embeddings=embeddings,
                    raise_exceptions=False,
                )
            elif llm:
                result = evaluate(
                    dataset=batch_dataset,
                    metrics=metrics,
                    llm=llm,
                    raise_exceptions=False,
                )
            else:
                result = evaluate(
                    dataset=batch_dataset,
                    metrics=metrics,
                    raise_exceptions=False,
                )
            
            dfs.append(result.to_pandas())
        
        combined = pd.concat(dfs, ignore_index=True)
        console.print("\n[green]✓ RAGAS 評估完成（序列批次處理）[/green]")
        return combined
    except Exception as e:
        console.print(f"\n[red]❌ RAGAS 評估失敗: {e}[/red]")
        console.print(f"[red]   錯誤類型: {type(e).__name__}[/red]")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        raise RuntimeError(f"RAGAS 評估失敗: {e}")


# ============================================================================
# 主執行邏輯
# ============================================================================

async def run_comparison(
    input_file: str,
    output_dir: str,
    k: int = 10,
    methods: List[str] = ["vector_only", "hybrid"],
    skip_answer_relevancy: bool = False,
    verbose: bool = False,
    resume: bool = True,
    batch_size: int = 10,
) -> Dict[str, pd.DataFrame]:
    """
    執行完整的比較評估
    
    Args:
        input_file: 測試問題 JSON 文件路徑
        output_dir: 輸出目錄
        k: 檢索結果數量
        methods: 要比較的檢索方法列表
        skip_answer_relevancy: 是否跳過 answer_relevancy 指標
        verbose: 是否顯示詳細日誌
        resume: 是否從中斷處恢復
        batch_size: RAGAS 評估時每批次的樣本數（序列處理）
    
    Returns:
        各方法的評估結果 DataFrame 字典
    """
    console.print("\n[bold magenta]═══════════════════════════════════════════[/bold magenta]")
    console.print("[bold magenta]   RAG 檢索策略比較評估 (RAGAS)   [/bold magenta]")
    console.print("[bold magenta]═══════════════════════════════════════════[/bold magenta]\n")
    
    # 讀取測試問題
    console.print(f"[cyan]📖 讀取測試問題: {input_file}[/cyan]")
    
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    test_cases = data.get("test_cases", [])
    
    # 過濾掉模板佔位符
    valid_cases = [
        case for case in test_cases
        if case.get("question") and not case["question"].startswith("（")
    ]
    
    if not valid_cases:
        console.print("[yellow]⚠️ 沒有有效的測試問題！請先填寫 test_queries_template.json[/yellow]")
        return {}
    
    console.print(f"[green]✓ 找到 {len(valid_cases)} 個有效測試問題[/green]\n")
    
    # 檢查是否有中間結果可以恢復
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    temp_file = output_path / "temp_results.json"
    all_results = {method: [] for method in methods}
    
    if resume and temp_file.exists():
        console.print(f"[yellow]📂 發現中間結果文件，嘗試恢復...[/yellow]")
        try:
            with open(temp_file, 'r', encoding='utf-8') as f:
                temp_data = json.load(f)
                
            # 檢查配置是否匹配
            if (temp_data.get("k") == k and 
                set(temp_data.get("methods", [])) == set(methods)):
                all_results = temp_data.get("results", {})
                console.print(f"[green]✓ 成功恢復中間結果[/green]")
                console.print(f"[green]  已完成: {', '.join([f'{m}({len(r)})' for m, r in all_results.items()])}[/green]\n")
            else:
                console.print(f"[yellow]⚠️ 配置不匹配，將重新開始[/yellow]\n")
                all_results = {method: [] for method in methods}
        except Exception as e:
            console.print(f"[yellow]⚠️ 恢復失敗: {e}，將重新開始[/yellow]\n")
            all_results = {method: [] for method in methods}
    
    # 執行評估（只處理未完成的部分）
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console
    ) as progress:
        
        for method in methods:
            completed = len(all_results.get(method, []))
            remaining = len(valid_cases) - completed
            
            if remaining == 0:
                console.print(f"[green]✓ {method} 已完成，跳過[/green]")
                continue
            
            task = progress.add_task(
                f"[cyan]{method} 檢索評估...",
                total=remaining
            )
            
            # 只處理未完成的問題
            for case in valid_cases[completed:]:
                try:
                    result = await run_single_evaluation(
                        question=case["question"],
                        ground_truth=case["ground_truth"],
                        file_ids=case.get("file_ids", []),
                        retrieval_method=method,
                        k=k
                    )
                    all_results[method].append(result)
                    
                    # 每 5 個問題保存一次
                    if len(all_results[method]) % 5 == 0:
                        with open(temp_file, 'w', encoding='utf-8') as f:
                            json.dump({
                                "k": k,
                                "methods": methods,
                                "results": all_results
                            }, f, ensure_ascii=False, indent=2)
                    
                    progress.advance(task)
                except Exception as e:
                    console.print(f"[red]❌ 問題評估失敗: {e}[/red]")
                    # 保存當前進度
                    with open(temp_file, 'w', encoding='utf-8') as f:
                        json.dump({
                            "k": k,
                            "methods": methods,
                            "results": all_results
                        }, f, ensure_ascii=False, indent=2)
                    raise
    
    # 最終保存
    with open(temp_file, 'w', encoding='utf-8') as f:
        json.dump({
            "k": k,
            "methods": methods,
            "results": all_results
        }, f, ensure_ascii=False, indent=2)
    
    console.print(f"\n[green]✓ 檢索階段完成，中間結果已保存[/green]\n")
    
    # RAGAS 評估
    ragas_results = {}
    
    for method, samples in all_results.items():
        console.print(f"\n[bold]📊 評估 {method} 方法...[/bold]")
        df = run_ragas_evaluation(
            samples, 
            skip_answer_relevancy=skip_answer_relevancy,
            verbose=verbose,
            batch_size=batch_size,
        )
        df["retrieval_method"] = method
        ragas_results[method] = df
    
    # 合併結果
    combined_df = pd.concat(ragas_results.values(), ignore_index=True)
    
    # 儲存結果
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # CSV
    csv_path = output_path / f"comparison_{timestamp}.csv"
    combined_df.to_csv(csv_path, index=False, encoding='utf-8-sig')
    console.print(f"\n[green]✓ 結果已儲存至: {csv_path}[/green]")
    
    # JSON（詳細結果）
    json_path = output_path / f"comparison_{timestamp}.json"
    detailed_results = {
        "timestamp": timestamp,
        "config": {"k": k, "methods": methods},
        "results": {
            method: [
                {
                    "question": s["question"],
                    "ground_truth": s["ground_truth"],
                    "answer": s["answer"],
                    "num_contexts": len(s["contexts"]),
                }
                for s in samples
            ]
            for method, samples in all_results.items()
        },
        "metrics": combined_df.to_dict(orient="records")
    }
    
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(detailed_results, f, ensure_ascii=False, indent=2)
    console.print(f"[green]✓ 詳細結果已儲存至: {json_path}[/green]")
    
    # 刪除臨時文件
    if temp_file.exists():
        temp_file.unlink()
        console.print(f"[dim]🗑️ 已清理臨時文件[/dim]")
    
    # 顯示摘要
    display_summary(combined_df, methods)
    
    return ragas_results


def display_summary(df: pd.DataFrame, methods: List[str]):
    """顯示評估結果摘要"""
    console.print("\n[bold magenta]═══════════════════════════════════════════[/bold magenta]")
    console.print("[bold magenta]           評估結果摘要           [/bold magenta]")
    console.print("[bold magenta]═══════════════════════════════════════════[/bold magenta]\n")
    
    # 計算各指標的平均值
    metrics = ["context_precision", "context_recall", "faithfulness", "answer_relevancy"]
    
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("指標", style="white")
    
    for method in methods:
        table.add_column(method, justify="center")
    
    table.add_column("差異", justify="center", style="yellow")
    
    for metric in metrics:
        if metric not in df.columns:
            continue
        
        row = [metric]
        values = []
        
        for method in methods:
            method_df = df[df["retrieval_method"] == method]
            if not method_df.empty and metric in method_df.columns:
                avg = method_df[metric].mean()
                values.append(avg)
                row.append(f"{avg:.4f}")
            else:
                values.append(None)
                row.append("N/A")
        
        # 計算差異
        if len(values) >= 2 and all(v is not None for v in values[:2]):
            diff = values[1] - values[0]  # hybrid - vector_only
            diff_str = f"{diff:+.4f}"
            if diff > 0:
                diff_str = f"[green]{diff_str}[/green]"
            elif diff < 0:
                diff_str = f"[red]{diff_str}[/red]"
            row.append(diff_str)
        else:
            row.append("N/A")
        
        table.add_row(*row)
    
    console.print(table)
    console.print("\n[dim]差異 = hybrid - vector_only（正值表示 hybrid 更好）[/dim]\n")


# ============================================================================
# CLI 入口
# ============================================================================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="RAG 檢索策略比較評估 (RAGAS)"
    )
    parser.add_argument(
        "--input", "-i",
        type=str,
        default="evaluation/test_queries_template.json",
        help="測試問題 JSON 文件路徑"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default="evaluation/results",
        help="輸出目錄"
    )
    parser.add_argument(
        "--k",
        type=int,
        default=10,
        help="每種檢索返回的結果數量"
    )
    parser.add_argument(
        "--methods",
        type=str,
        nargs="+",
        default=["vector_only", "hybrid"],
        choices=["vector_only", "hybrid", "fulltext_only"],
        help="要比較的檢索方法"
    )
    parser.add_argument(
        "--skip-answer-relevancy",
        action="store_true",
        default=False,
        help="跳過 answer_relevancy 指標（避免 Embedding API 錯誤）"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="顯示詳細日誌"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="RAGAS 評估時的批次大小（每批序列處理）"
    )
    
    args = parser.parse_args()
    
    # 轉換為絕對路徑（相對於專案根目錄，不是 evaluation 目錄）
    project_root = Path(__file__).parent.parent
    script_dir = Path(__file__).parent
    
    # 輸入路徑處理
    if Path(args.input).is_absolute():
        input_path = Path(args.input)
    elif args.input.startswith("evaluation/"):
        input_path = project_root / args.input
    else:
        input_path = script_dir / args.input
    
    # 輸出路徑處理
    if Path(args.output).is_absolute():
        output_path = Path(args.output)
    elif args.output.startswith("evaluation/"):
        output_path = project_root / args.output
    else:
        output_path = script_dir / args.output
    
    # 如果輸入文件在當前目錄下
    if not input_path.exists():
        input_path = script_dir / Path(args.input).name
    
    if not input_path.exists():
        console.print(f"[red]❌ 找不到輸入文件: {input_path}[/red]")
        console.print("[yellow]請確認 test_queries_template.json 存在並已填入測試問題[/yellow]")
        sys.exit(1)
    
    # 執行比較
    asyncio.run(run_comparison(
        input_file=str(input_path),
        output_dir=str(output_path),
        k=args.k,
        methods=args.methods,
        skip_answer_relevancy=args.skip_answer_relevancy,
        verbose=args.verbose,
        batch_size=args.batch_size,
    ))


if __name__ == "__main__":
    main()
