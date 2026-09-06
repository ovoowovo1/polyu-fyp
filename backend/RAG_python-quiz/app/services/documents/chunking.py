"""PDF/Markdown splitting that keeps small text and structural line boundaries."""
import re

from langchain_text_splitters import RecursiveCharacterTextSplitter


class DocumentSplitter:
    def __init__(self, chunk_size=1500, chunk_overlap=400):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.prose = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", "。", "！", "？", "；", ". ", "! ", "? ", "; ", "，", ", ", " ", ""])

    def split_lines(self, lines, prefix="", suffix=""):
        parts, current = [], []
        for line in lines:
            if current and len(prefix + "\n".join(current + [line]) + suffix) > self.chunk_size:
                parts.append(prefix + "\n".join(current) + suffix)
                overlap, size = [], 0
                for previous in reversed(current):
                    if size + len(previous) + 1 > self.chunk_overlap:
                        break
                    overlap.insert(0, previous)
                    size += len(previous) + 1
                current = overlap
                while current and len(prefix + "\n".join(current + [line]) + suffix) > self.chunk_size:
                    current.pop(0)
            current.append(line)
        if current:
            parts.append(prefix + "\n".join(current) + suffix)
        return parts

    def split_text(self, text):
        # Fenced code and consecutive pipe-table rows are kept as complete blocks.
        pattern = r"(^```[^\n]*\n[\s\S]*?^```[^\n]*$|^(?:[^\n]*\|[^\n]*(?:\n|$)){2,})"
        chunks = []
        for part in re.split(pattern, text, flags=re.MULTILINE):
            if not part or not part.strip():
                continue
            part = part.strip("\r\n")
            if part.startswith("```"):
                lines = part.splitlines()
                chunks.extend(self.split_lines(lines[1:-1], lines[0] + "\n", "\n```"))
            elif len(part.splitlines()) >= 2 and re.match(r"^[\s|:\-]+$", part.splitlines()[1]):
                lines = part.splitlines()
                chunks.extend(self.split_lines(lines[2:], "\n".join(lines[:2]) + "\n"))
            else:
                chunks.extend(self.prose.split_text(part))
        return chunks
