"""BibTeX 导入接口。

重点覆盖三件事：幂等性、部分失败的报告、以及文件上传这条路。
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import DataError, IntegrityError, SQLAlchemyError

SIMPLE_BIB = """
@article{paxman2023,
  title = {Automatic mapping of {Greenland}'s subglacial valleys},
  author = {Paxman, Guy J. G. and Zhang, Alice},
  journal = {Journal of Glaciology},
  year = {2023},
  doi = {https://doi.org/10.1017/JOG.2023.1},
  keywords = {glaciology, radar}
}

@inproceedings{chartrand2026,
  title = {A giant subglacial valley network},
  author = {Chartrand, Robert},
  booktitle = {Proceedings of the Cryosphere Conference},
  year = {2026}
}
"""


def import_bibtex(client: TestClient, headers: dict[str, str], bibtex: str) -> dict[str, Any]:
    response = client.post("/papers/import", json={"bibtex": bibtex}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


class TestTextImport:
    def test_imports_all_entries(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        stats = import_bibtex(client, auth_headers, SIMPLE_BIB)

        assert stats["total"] == 2
        assert stats["created"] == 2
        assert stats["skipped"] == 0
        assert stats["failed"] == 0
        assert stats["issues"] == []

    def test_normalizes_doi_and_author_name(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        import_bibtex(client, auth_headers, SIMPLE_BIB)

        body = client.get("/papers", params={"q": "Automatic mapping"}).json()
        paper = body["items"][0]
        assert paper["doi"] == "10.1017/jog.2023.1"
        # 标题里的 {Greenland} 保护花括号应该被剥掉
        assert paper["title"] == "Automatic mapping of Greenland's subglacial valleys"
        # "Paxman, Guy J. G." 应该被转成「名 姓」，并按原顺序保留
        assert [a["name"] for a in paper["authors"]] == ["Guy J. G. Paxman", "Alice Zhang"]

    def test_keywords_become_tags(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        import_bibtex(client, auth_headers, SIMPLE_BIB)

        body = client.get("/papers", params={"q": "Automatic mapping"}).json()
        assert sorted(t["name"] for t in body["items"][0]["tags"]) == ["glaciology", "radar"]

    def test_journal_and_booktitle_both_map_to_venue(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        import_bibtex(client, auth_headers, SIMPLE_BIB)

        by_title = {item["title"]: item for item in client.get("/papers").json()["items"]}
        assert by_title["A giant subglacial valley network"]["venue"] == (
            "Proceedings of the Cryosphere Conference"
        )

    def test_reimport_is_idempotent(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        """幂等性是导入功能的核心要求：同一份文件导两次不能变成两份数据。"""
        first = import_bibtex(client, auth_headers, SIMPLE_BIB)
        second = import_bibtex(client, auth_headers, SIMPLE_BIB)

        assert first["created"] == 2
        assert second["created"] == 0
        assert second["skipped"] == 2

        # 库里确实还是一共 2 篇，不是 4 篇
        assert client.get("/papers").json()["total"] == 2

    def test_duplicate_within_one_file_is_skipped(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """同一份文件里重复的条目也要去重 —— 只查库不查文件的话会插两次。"""
        bib = """
        @article{a, title = {Same Title}, year = {2020}, doi = {10.1/x}}
        @article{b, title = {Same Title}, year = {2020}, doi = {10.1/x}}
        """
        stats = import_bibtex(client, auth_headers, bib)
        assert stats["created"] == 1
        assert stats["skipped"] == 1

    def test_entry_without_doi_dedupes_by_title_and_year(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """没有 DOI 的条目用 (标题, 年份) 当后备指纹。"""
        bib = "@article{a, title = {No Doi Here}, year = {2019}}"
        assert import_bibtex(client, auth_headers, bib)["created"] == 1
        assert import_bibtex(client, auth_headers, bib)["skipped"] == 1


class TestPartialFailure:
    def test_one_bad_record_does_not_block_the_others(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """这是导入功能最重要的行为：499 条好数据不该被 1 条 typo 拖下水。"""
        bib = """
        @article{good, title = {Good One}, year = {2020}}
        @article{future, title = {From The Future}, year = {2099}}
        @article{alsoGood, title = {Another Good One}, year = {2021}}
        """
        stats = import_bibtex(client, auth_headers, bib)

        assert stats["total"] == 3
        assert stats["created"] == 2
        assert stats["failed"] == 1
        # 不变式：每条解析出来的记录必然落到三个桶之一
        assert stats["total"] == stats["created"] + stats["skipped"] + stats["failed"]

    def test_validation_failure_reports_index_and_key(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        bib = """
        @article{good, title = {Good One}, year = {2020}}
        @article{fromFuture, title = {From The Future}, year = {2099}}
        """
        stats = import_bibtex(client, auth_headers, bib)

        assert len(stats["issues"]) == 1
        issue = stats["issues"][0]
        assert issue["index"] == 2
        assert issue["key"] == "fromFuture"
        assert "year 不能晚于" in issue["reason"]

    def test_parse_error_is_reported_without_entry_index(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """解析级错误没有条目序号可给，index 和 key 都是 null。"""
        bib = """
        @article{broken,
          title {missing the equals sign},
          year = {2020}
        }
        """
        stats = import_bibtex(client, auth_headers, bib)

        assert stats["total"] == 0
        assert len(stats["issues"]) == 1
        assert stats["issues"][0]["index"] is None
        assert "缺少 =" in stats["issues"][0]["reason"]

    def test_empty_body_is_rejected(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        response = client.post("/papers/import", json={"bibtex": ""}, headers=auth_headers)
        assert response.status_code == 422


class TestFileUpload:
    def test_upload_bib_file(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        response = client.post(
            "/papers/import/upload",
            files={"file": ("sample.bib", SIMPLE_BIB.encode("utf-8"), "text/plain")},
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.json()["created"] == 2

    def test_upload_handles_utf8_bom(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """有些编辑器保存的 utf-8 会带 BOM，解码时不能把 BOM 留在正文里。"""
        raw = "\ufeff@article{k, title = {BOM Test}, year = {2020}}".encode()
        response = client.post(
            "/papers/import/upload",
            files={"file": ("bom.bib", raw, "text/plain")},
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.json()["created"] == 1

    def test_upload_and_text_import_share_dedup(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """两个入口必须走同一套去重逻辑，否则换个入口就能导进重复数据。"""
        import_bibtex(client, auth_headers, SIMPLE_BIB)

        response = client.post(
            "/papers/import/upload",
            files={"file": ("sample.bib", SIMPLE_BIB.encode("utf-8"), "text/plain")},
            headers=auth_headers,
        )
        assert response.json()["skipped"] == 2

    def test_upload_falls_back_to_latin1_for_non_utf8_files(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """老的 .bib 文件可能是 latin-1 编码，不能因此让整个请求 500。"""
        # 0xE9 单独出现是非法的 UTF-8 序列，会触发解码兜底分支
        raw = "@article{k, title = {Caf\xe9 study}, year = {2020}}".encode("latin-1")

        response = client.post(
            "/papers/import/upload",
            files={"file": ("latin1.bib", raw, "text/plain")},
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.json()["created"] == 1


class TestWriteFailureIsolation:
    @pytest.mark.parametrize(
        ("error", "expected_text"),
        [
            # IntegrityError 是 SQLAlchemyError 的子类，会被专门的分支先捕获
            (IntegrityError("INSERT INTO papers ...", {}, Exception("dup")), "写入冲突"),
            # 其他数据库错误走兜底的 SQLAlchemyError 分支
            (DataError("INSERT INTO papers ...", {}, Exception("value too long")), "写入失败"),
        ],
    )
    def test_failed_write_does_not_block_later_entries(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
        error: SQLAlchemyError,
        expected_text: str,
    ) -> None:
        """一条写入失败后必须 rollback 清理 session，否则后面每条都会连着失败。

        这个分支很难自然触发（去重逻辑很严），所以用 monkeypatch 强制注入一次失败。
        它是「部分成功」这个承诺的兜底：失败之后剩下的记录还得能进库。
        """
        from paper_manage import crud

        original = crud.create_paper
        calls = {"count": 0}

        def flaky(db: Any, payload: Any) -> Any:
            calls["count"] += 1
            if calls["count"] == 1:
                raise error
            return original(db, payload)

        # 打在 paper_manage.crud 这个**包**上：导入服务里写的是 `crud.create_paper`，
        # 包里的这个名字在 import 时就绑定好了，改 crud.paper 模块是没用的。
        monkeypatch.setattr(crud, "create_paper", flaky)

        bib = """
        @article{first, title = {Will Fail}, year = {2020}}
        @article{second, title = {Should Succeed}, year = {2021}}
        """
        stats = import_bibtex(client, auth_headers, bib)

        assert stats["failed"] == 1
        assert stats["created"] == 1
        assert expected_text in stats["issues"][0]["reason"]
        assert stats["issues"][0]["key"] == "first"
