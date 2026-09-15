from mcp.server.fastmcp import FastMCP
from backend.retrieval import search_corpus, chunk_context
from backend.store import Store

mcp = FastMCP("exampilot-knowledge-mcp")
store = Store(readonly=True)


@mcp.tool()
def search(project_id: str, corpus_version: int, queries: list[dict] | None = None, query: str | None = None, top_k: int = 5) -> dict:
    """批量检索课程知识点，返回真实原文候选及来源摘要。queries 和 query 二选一。"""
    if (queries is None) == (query is None):
        raise ValueError("query 与 queries 必须且只能提供一个")
    return search_corpus(store, project_id, corpus_version, queries if queries is not None else [{"query": query}], top_k)


@mcp.tool()
def get_chunk_context(project_id: str, corpus_version: int, ids: list[str] | None = None, id: str | None = None) -> dict:
    """批量读取原文及 Source Metadata。仅返回指定项目已发布资料中的内容。ids 和 id 二选一。"""
    if (ids is None) == (id is None):
        raise ValueError("id 与 ids 必须且只能提供一个")
    return chunk_context(store, project_id, corpus_version, ids if ids is not None else [id])


if __name__ == "__main__":
    mcp.run(transport="stdio")

