from path_graph.chunkers.chunk import chunk_from_markdown
from path_graph.ids import document_id, sha256_text
from path_graph.steps.agent_invoke import extract_wikilinks


def test_chunk_markdown_splits():
    text = "para one\n\npara two\n\npara three"
    h = "abc123deadbeef"
    chunks = chunk_from_markdown(text, "t1", h, max_chars=20)
    assert len(chunks) >= 2
    assert all(c.tenant == "t1" for c in chunks)
    assert chunks[0].document_id == document_id("t1", h)


def test_wikilink_extract():
    text = "See [[Page A]] and [[Page B]] and [[Page A]]"
    links = extract_wikilinks(text)
    assert links == ["Page A", "Page B"]
