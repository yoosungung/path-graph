from path_graph.chunkers.chunk import chunk_from_markdown
from path_graph.ids import document_id, sha256_text
from path_graph.steps.agent_invoke import extract_wikilinks
from constants import PROJECT_ID


def test_chunk_markdown_splits():
    text = "para one\n\npara two\n\npara three"
    h = "abc123deadbeef"
    chunks = chunk_from_markdown(text, "t1", h, PROJECT_ID, max_chars=20)
    assert len(chunks) >= 2
    assert all(c.tenant == "t1" for c in chunks)
    assert chunks[0].document_id == document_id("t1", PROJECT_ID, h)


def test_oversized_single_paragraph_splits():
    text = "a" * 2500
    h = "deadbeef"
    chunks = chunk_from_markdown(text, "t1", h, PROJECT_ID, max_chars=1000)
    assert len(chunks) == 3
    assert all(len(c.text) <= 1000 for c in chunks)


def test_table_like_markdown_splits_without_double_newline():
    lines = [f"| row {i} | data |" for i in range(80)]
    text = "title\n" + "\n".join(lines)
    h = "cafebabe"
    chunks = chunk_from_markdown(text, "t1", h, PROJECT_ID, max_chars=1000)
    assert len(chunks) >= 2
    assert all(len(c.text) <= 1000 for c in chunks)


def test_wikilink_extract():
    text = "See [[Page A]] and [[Page B]] and [[Page A]]"
    links = extract_wikilinks(text)
    assert links == ["Page A", "Page B"]
