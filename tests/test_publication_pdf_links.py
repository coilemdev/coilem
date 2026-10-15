"""Published PDFs must not link to files on the machine that built them."""

from __future__ import annotations

import pytest

from tools.verify_snapshot import pdf_hygiene_failures, pdf_link_is_local

pypdf = pytest.importorskip("pypdf")
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NumberObject, TextStringObject  # noqa: E402

# Joined at run time: spelled out, these sample user folders would fail the
# snapshot gate's own text check on this file.
WINDOWS_HOME = "/".join(("C:", "Users", "someone"))
MAC_HOME = "/".join(("", "Users", "someone"))
LINUX_HOME = "/".join(("", "home", "someone"))


def action(kind, **entries):
    fields = {NameObject("/S"): NameObject(kind)}
    for key, value in entries.items():
        fields[NameObject(f"/{key}")] = TextStringObject(value) if isinstance(value, str) else value
    return DictionaryObject(fields)


def link(target):
    return DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Link"),
            NameObject("/Rect"): ArrayObject([NumberObject(v) for v in (10, 10, 60, 20)]),
            NameObject("/A"): target,
        }
    )


def pdf_with_links(tmp_path, *actions, writer=None):
    writer = writer or pypdf.PdfWriter()
    writer.add_blank_page(200, 200)
    for target in actions:
        writer.add_annotation(0, link(target))
    path = tmp_path / "report.pdf"
    writer.write(path)
    return path


@pytest.mark.parametrize(
    "uri",
    [
        f"file:///{WINDOWS_HOME}/benchmark-output/report/fixtures/a.json",
        "file:///private/tmp/scratch/report/fixtures/a.json",
        f"{LINUX_HOME}/report/fixtures/a.json",
        "C:/bench/report/fixtures/a.json",
        "C:\\bench\\report\\fixtures\\a.json",
        "\\\\server\\share\\a.json",
        "~/report/fixtures/a.json",
        "javascript:app.alert(1)",
        f"https://example.com/open?path={MAC_HOME}/a.json",
    ],
)
def test_local_link_targets_are_rejected(uri):
    assert pdf_link_is_local(uri)


@pytest.mark.parametrize(
    "uri",
    [
        "https://github.com/coilemdev/coilem/blob/main/benchmarks/main-20261012-af10e6d/fixtures/a.json",
        "http://example.com/a.json",
        "mailto:maintainers@example.org",
        "fixtures/a.json",
        "../fixtures/a.json",
    ],
)
def test_web_and_report_relative_link_targets_are_allowed(uri):
    assert not pdf_link_is_local(uri)


def test_pdf_with_web_relative_and_internal_links_passes(tmp_path):
    path = pdf_with_links(
        tmp_path,
        action("/URI", URI="https://github.com/coilemdev/coilem"),
        action("/URI", URI="fixtures/spm_4p12s_simple__baseline__native.json"),
        action("/GoTo", D=ArrayObject([NumberObject(0), NameObject("/Fit")])),
    )
    assert pdf_hygiene_failures("report.pdf", path) == []


@pytest.mark.parametrize(
    "target",
    [
        action("/URI", URI=f"file:///{WINDOWS_HOME}/report/fixtures/a.json"),
        action("/Launch", F="C:/bench/rerun.bat"),
        action("/GoToR", F=f"{LINUX_HOME}/other.pdf", D=ArrayObject([NumberObject(0), NameObject("/Fit")])),
        action("/URI", URI="https://github.com/coilemdev/coilem", Next=action("/URI", URI=f"file://{LINUX_HOME}/a.json")),
    ],
    ids=["file-uri", "launch", "remote-goto", "chained-next"],
)
def test_pdf_with_a_local_file_link_fails_without_echoing_the_path(tmp_path, target):
    failures = pdf_hygiene_failures("report.pdf", pdf_with_links(tmp_path, target))
    assert failures == ["local file link in PDF: report.pdf (1 links, first on page 1)"]
    assert "someone" not in failures[0] and "bench" not in failures[0]


def test_a_looping_action_chain_ends(tmp_path):
    writer = pypdf.PdfWriter()
    loop = action("/URI", URI="https://github.com/coilemdev/coilem")
    reference = writer._add_object(loop)  # pypdf has no public call for an indirect object
    loop[NameObject("/Next")] = reference
    assert pdf_hygiene_failures("report.pdf", pdf_with_links(tmp_path, reference, writer=writer)) == []


def test_unreadable_pdf_is_reported(tmp_path):
    path = tmp_path / "report.pdf"
    path.write_bytes(b"%PDF-1.4\nnot a document\n%%EOF\n")
    assert pdf_hygiene_failures("report.pdf", path) == ["invalid publication PDF: report.pdf"]
