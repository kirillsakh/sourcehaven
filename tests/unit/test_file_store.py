from pathlib import Path

import pytest

from sourcehaven.storage.files import LocalFileStore


@pytest.mark.parametrize(
    "key",
    [
        "../x.pdf",
        "/abs.pdf",
        "a\\b.pdf",
        "a/../../b.pdf",
        "",
        "a/b\0.pdf",
        "a/..b.pdf",
        ".",
        "./",
        "a/./b",
        "a//b",
        "a/./..",
        "a/",
    ],
)
def test_file_store_rejects_unsafe_keys(tmp_path: Path, key: str) -> None:
    with pytest.raises(ValueError):
        LocalFileStore(tmp_path).resolve(key)


def test_resolve_stays_under_the_root(tmp_path: Path) -> None:
    assert LocalFileStore(tmp_path).resolve("o/d/v.pdf") == tmp_path / "o" / "d" / "v.pdf"


async def test_put_moves_the_file_and_open_reads_it(tmp_path: Path) -> None:
    store: LocalFileStore = LocalFileStore(tmp_path / "store")
    source: Path = tmp_path / "incoming.bin"
    source.write_bytes(b"%PDF-1.7 hello")
    await store.put("o/d/v.pdf", source)
    assert not source.exists()
    with store.open("o/d/v.pdf") as stream:
        assert stream.read() == b"%PDF-1.7 hello"


async def test_put_replaces_an_existing_key(tmp_path: Path) -> None:
    store: LocalFileStore = LocalFileStore(tmp_path / "store")
    for content in (b"one", b"two"):
        source: Path = tmp_path / "incoming.bin"
        source.write_bytes(content)
        await store.put("o/d/v.pdf", source)
    with store.open("o/d/v.pdf") as stream:
        assert stream.read() == b"two"


async def test_delete_prefix_removes_only_that_subtree(tmp_path: Path) -> None:
    store: LocalFileStore = LocalFileStore(tmp_path / "store")
    for key in ("o/d1/v.pdf", "o/d2/v.pdf"):
        source: Path = tmp_path / "incoming.bin"
        source.write_bytes(b"x")
        await store.put(key, source)
    await store.delete_prefix("o/d1/")
    assert not store.resolve("o/d1").exists()
    assert store.resolve("o/d2/v.pdf").exists()


async def test_delete_prefix_tolerates_a_missing_prefix(tmp_path: Path) -> None:
    await LocalFileStore(tmp_path).delete_prefix("o/missing/")


@pytest.mark.parametrize("prefix", ["", "/", "../x", "a\\b", ".", "./", "a/./..", "a//b"])
async def test_delete_prefix_rejects_unsafe_prefixes(tmp_path: Path, prefix: str) -> None:
    with pytest.raises(ValueError):
        await LocalFileStore(tmp_path).delete_prefix(prefix)


async def test_delete_prefix_dot_never_wipes_the_root(tmp_path: Path) -> None:
    store: LocalFileStore = LocalFileStore(tmp_path)
    (tmp_path / "o").mkdir()
    for prefix in (".", "./"):
        with pytest.raises(ValueError):
            await store.delete_prefix(prefix)
    assert (tmp_path / "o").is_dir()
