# -*- coding: utf-8 -*-
"""
輔助腳本 - 列出資料庫中的所有文檔

執行此腳本以查看可用的文檔 ID，方便填寫 test_queries_template.json
"""

import os
import sys

# 將專案根目錄加入 Python 路徑
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import pg_service
from rich.console import Console
from rich.table import Table


def list_all_documents():
    """列出所有文檔及其基本資訊"""
    console = Console()
    
    console.print("\n[bold cyan]📄 資料庫中的文檔列表[/bold cyan]\n")
    
    try:
        # 獲取所有文檔
        files = pg_service.get_files_list()
        
        if not files:
            console.print("[yellow]⚠️ 資料庫中沒有任何文檔[/yellow]")
            return
        
        # 建立表格
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("序號", style="dim", width=4)
        table.add_column("文檔 ID (UUID)", style="cyan", width=38)
        table.add_column("檔案名稱", style="green", max_width=40)
        table.add_column("Chunks 數", justify="right", style="yellow")
        table.add_column("大小", justify="right")
        
        for idx, doc in enumerate(files, start=1):
            doc_id = doc.get("id") or doc.get("fileId") or "N/A"
            name = doc.get("filename") or doc.get("name") or doc.get("original_name") or "未命名"
            chunks = doc.get("total_chunks") or doc.get("chunk_count") or 0
            size = doc.get("file_size") or doc.get("size") or 0
            
            # 格式化文件大小
            if size >= 1024 * 1024:
                size_str = f"{size / (1024 * 1024):.1f} MB"
            elif size >= 1024:
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size} B"
            
            table.add_row(
                str(idx),
                str(doc_id),
                name[:40] + "..." if len(name) > 40 else name,
                str(chunks),
                size_str
            )
        
        console.print(table)
        console.print(f"\n[bold]共 {len(files)} 個文檔[/bold]\n")
        
        # 輸出可複製的格式
        console.print("[bold cyan]📋 可複製的 file_ids 格式:[/bold cyan]")
        file_ids = [str(doc.get("id") or doc.get("fileId")) for doc in files]
        console.print(f'[dim]{file_ids}[/dim]\n')
        
    except Exception as e:
        console.print(f"[red]❌ 錯誤: {e}[/red]")
        raise


def list_documents_by_class(class_id: str):
    """列出特定班級的文檔"""
    console = Console()
    
    console.print(f"\n[bold cyan]📄 班級 {class_id} 的文檔列表[/bold cyan]\n")
    
    try:
        files = pg_service.get_files_list(class_id=class_id)
        
        if not files:
            console.print(f"[yellow]⚠️ 班級 {class_id} 沒有任何文檔[/yellow]")
            return
        
        for idx, doc in enumerate(files, start=1):
            doc_id = doc.get("id") or doc.get("fileId")
            name = doc.get("filename") or doc.get("name") or "未命名"
            console.print(f"  {idx}. [cyan]{doc_id}[/cyan] - {name}")
        
        console.print(f"\n[bold]共 {len(files)} 個文檔[/bold]\n")
        
    except Exception as e:
        console.print(f"[red]❌ 錯誤: {e}[/red]")
        raise


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="列出資料庫中的文檔")
    parser.add_argument("--class-id", "-c", type=str, help="指定班級 ID 進行篩選")
    
    args = parser.parse_args()
    
    if args.class_id:
        list_documents_by_class(args.class_id)
    else:
        list_all_documents()
