from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from agentlab.models import Chunk


def split_markdown(text: str, doc_id: str, title: str) -> tuple[Chunk, ...]:
    header_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#", "h1"), ("##", "h2")]
    )
    header_docs = header_splitter.split_text(text)

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50,
        separators=["\n\n", "\n", "。", "！", "？", " ", ""],
    )

    chunks: list[Chunk] = []
    for piece in text_splitter.split_documents(header_docs):
        content = piece.page_content.strip()
        if not content:
            continue
        heading = str(piece.metadata.get("h2") or piece.metadata.get("h1") or "")
        chunks.append(
            Chunk(
                doc_id=doc_id,
                chunk_index=len(chunks),
                title=title,
                heading=heading,
                content=content,
            )
        )
    return tuple(chunks)
