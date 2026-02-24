from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders.pdf import PyPDFLoader
from langchain_community.document_loaders.word_document import Docx2txtLoader
from src.utils.text_sanitizer import sanitize_text
from openpyxl import load_workbook
import csv


def read_csv(file_path: str) -> tuple[list[str], int]:
    """
    读取CSV文件并返回切分后的文本块列表和块数。
    这里的实现非常简单，直接将每行作为一个文本块。根据需要可以进行更复杂的处理。
    """
    chunks = []
    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            line = " ".join(row)  # 将每行的所有列合并成一个字符串
            chunks.append(sanitize_text(line))

    print(f"总共切分成 {len(chunks)} 个文本块")
    return chunks, len(chunks)


def read_qa_excel(file_path: str) -> list[dict[str, str]]:
    """
    读取“问题/答案”两列的Excel（.xlsx/.xlsm，默认首个sheet）。
    返回: [{"question": "...", "answer": "..."}, ...]
    """
    wb = load_workbook(file_path, read_only=True, data_only=True)
    try:
        ws = wb.active
        row_iter = ws.iter_rows(values_only=True)
        header = next(row_iter, None)
        if header is None:
            raise ValueError("Excel is empty or missing header row.")

        fields = [str(col).strip() if col is not None else "" for col in header]
        if "问题" not in fields or "答案" not in fields:
            raise ValueError("Excel must contain columns: 问题, 答案")

        question_idx = fields.index("问题")
        answer_idx = fields.index("答案")

        records: list[dict[str, str]] = []
        for row in row_iter:
            question_value = row[question_idx] if question_idx < len(row) else None
            answer_value = row[answer_idx] if answer_idx < len(row) else None

            question = sanitize_text(str(question_value).strip()) if question_value is not None else ""
            answer = sanitize_text(str(answer_value).strip()) if answer_value is not None else ""
            if not question or not answer:
                continue
            records.append({"question": question, "answer": answer})

        return records
    finally:
        wb.close()


def read_excel(file_path: str) -> tuple[list[str], int]:
    """
    读取“问题/答案”两列Excel，并将每行转为一个文本块。
    """
    records = read_qa_excel(file_path)
    chunks = [
        sanitize_text(f"问题：{record['question']}\n答案：{record['answer']}")
        for record in records
    ]
    print(f"总共切分成 {len(chunks)} 个文本块")
    return chunks, len(chunks)


def read_pdf(file_path: str) -> tuple[list[str], int]:
    """
    读取PDF文件并返回切分后的文本块列表和块数。
    """
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=512, chunk_overlap=200, length_function=len)
    loader = PyPDFLoader(file_path)

    texts = [doc.page_content for doc in loader.lazy_load()]
    texts = "".join(texts)
    texts = sanitize_text(texts)
    
    chunks = text_splitter.split_text(texts)
    chunks = [sanitize_text(chunk) for chunk in chunks]

    print(f"总共切分成 {len(chunks)} 个文本块")
    return chunks, len(chunks)


def read_docx(file_path: str) -> tuple[list[str], int]:
    """
    读取Word文档并返回切分后的文本块列表和块数。
    """
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=512, chunk_overlap=200, length_function=len)
    loader = Docx2txtLoader(file_path)

    texts = [doc.page_content for doc in loader.lazy_load()]
    texts = "".join(texts)
    texts = sanitize_text(texts)
    
    chunks = text_splitter.split_text(texts)
    chunks = [sanitize_text(chunk) for chunk in chunks]

    print(f"总共切分成 {len(chunks)} 个文本块")
    return chunks, len(chunks)


if __name__ == "__main__":
    pass
    chunks, count = read_pdf("~/Downloads/20250916太原理工大学2025版学生手册（封面＋正文）.pdf")
    print(f"返回了 {count} 个文本块")
    # import json
    # print(json.dumps(texts, ensure_ascii=False, indent=2))
