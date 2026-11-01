"""
Framework: tests for tools/render_framework_graph.py, on mutated copies of the data and on the shipped graph.
Package: tests/test_render_framework_graph

The checks are the ones the generator was first written with, in the repository it came from; the exit codes, the
`--root` option, the neutral wording and the table-safety rule are the template's.
"""

from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import render_framework_graph as rfg  # noqa: E402

DATA_FILE = ROOT / "Docs/knowledge/ai-first-framework.graph.json"
# Built from pieces, so that this file (which ships to every made repository) does not itself name a project.
PROJECT_NAMES = ("hog" + "shade", "large" + "worlds", "sprite" + "jammer", "marm" + "oset", "job_orch" + "estrator")
PROJECT_PATTERN = re.compile(r"\b(" + "|".join(PROJECT_NAMES + ("ma" + "ya", "ba" + "ts", "wg" + "pu")) + r")\b")


@pytest.fixture(scope="module")
def data() -> dict:
    return rfg.load()


def _mutated(data: dict, mutate) -> list[str]:
    copied = copy.deepcopy(data)
    mutate(copied)
    return rfg.problems(copied)


def _edge(d: dict, *, to: str | None = None, source: str | None = None, relation: str | None = None) -> dict:
    """An edge between real nodes of ``d``, with any of its three parts replaced."""
    ids = [n["id"] for n in d["nodes"]]
    return {"from": source or ids[0], "to": to or ids[1], "relation": relation or sorted(d["relations"])[0]}


def _graph_in(root: Path, text: str | None = None) -> Path:
    knowledge = root / "Docs" / "knowledge"
    knowledge.mkdir(parents=True)
    (knowledge / "ai-first-framework.graph.json").write_text(
        text or DATA_FILE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return knowledge


# ---- the shipped graph
def test_the_shipped_graph_is_well_formed(data: dict) -> None:
    assert rfg.problems(data) == []


def test_the_shipped_page_is_current() -> None:
    found, diff = rfg.check()
    assert found == [] and diff == "", diff[:2000]


def test_the_graph_and_its_page_name_no_project(data: dict) -> None:
    """The graph is project-agnostic: a repository's name belongs in `seen` as a letter, never in the text."""
    text = " ".join(f"{n['id']} {n['label']} {n['summary']}" for n in data["nodes"])
    for where in (text, rfg.render(data), DATA_FILE.read_text(encoding="utf-8")):
        assert PROJECT_PATTERN.search(where.lower()) is None, PROJECT_PATTERN.search(where.lower())


def test_the_name_pattern_finds_a_name_and_not_a_word_that_contains_one() -> None:
    assert PROJECT_PATTERN.search("seen in " + PROJECT_NAMES[0] + ".")
    assert PROJECT_PATTERN.search("combats and hogwash") is None


def test_the_page_links_to_nothing_that_may_not_exist(data: dict) -> None:
    """The page ships to every made repository, so it may not link to a file only the template has."""
    links = re.findall(r"\]\(([^)]+)\)", rfg.render(data))
    assert [link for link in links if not link.startswith(("http://", "https://", "#"))] == []


# ---- malformed data is reported
def test_a_declared_relation_that_is_never_used_is_found(data: dict) -> None:
    relation = sorted(data["relations"])[0]

    def drop(d: dict) -> None:
        d["edges"] = [e for e in d["edges"] if e["relation"] != relation]

    assert f"relation '{relation}' is declared and never used" in _mutated(data, drop)


def test_a_duplicate_id_is_found(data: dict) -> None:
    found = _mutated(data, lambda d: d["nodes"].append(dict(d["nodes"][0])))
    assert any("duplicate node id" in f for f in found)


def test_an_edge_to_nowhere_is_found(data: dict) -> None:
    found = _mutated(data, lambda d: d["edges"].append(_edge(d, to="nowhere")))
    assert any("not a node" in f for f in found)


def test_an_unknown_relation_is_found(data: dict) -> None:
    found = _mutated(data, lambda d: d["edges"].append(_edge(d, relation="loves")))
    assert any("unknown relation" in f for f in found)


def test_an_orphan_node_is_found(data: dict) -> None:
    first = data["nodes"][0]
    orphan = {
        "id": "lonely",
        "kind": first["kind"],
        "layer": first["layer"],
        "label": "Lonely",
        "seen": "H",
        "summary": "x",
    }
    assert _mutated(data, lambda d: d["nodes"].append(orphan)) == ["node lonely has no edge"]


def test_a_bad_seen_string_is_found(data: dict) -> None:
    assert any("seen" in f for f in _mutated(data, lambda d: d["nodes"][0].update(seen="HX")))
    assert any("distinct" in f for f in _mutated(data, lambda d: d["nodes"][0].update(seen="HH")))


def test_a_self_edge_and_a_duplicate_edge_are_found(data: dict) -> None:
    found = _mutated(data, lambda d: d["edges"].append(_edge(d, to=d["nodes"][0]["id"], source=d["nodes"][0]["id"])))
    assert any("points at itself" in f for f in found)
    assert any("duplicate edge" in f for f in _mutated(data, lambda d: d["edges"].append(dict(d["edges"][0]))))


def test_an_unknown_kind_or_layer_is_found(data: dict) -> None:
    assert any("unknown kind" in f for f in _mutated(data, lambda d: d["nodes"][0].update(kind="gizmo")))
    assert any("unknown layer" in f for f in _mutated(data, lambda d: d["nodes"][0].update(layer="attic")))


def test_a_layer_with_no_node_is_found(data: dict) -> None:
    assert any("has no node" in f for f in _mutated(data, lambda d: d["layers"].update(attic="nothing in it")))


@pytest.mark.parametrize("bad", ["Entry File", "snake_case", "-lead", "trail-", "double--hyphen"])
def test_a_non_kebab_id_is_found(data: dict, bad: str) -> None:
    assert any("kebab-case" in f for f in _mutated(data, lambda d: d["nodes"][0].update(id=bad)))


@pytest.mark.parametrize("word", ["end", "graph", "subgraph", "class", "style", "click", "default", "call", "href"])
def test_a_mermaid_keyword_is_a_fine_node_id_and_a_fine_layer_because_every_identifier_is_prefixed(
    data: dict, word: str
) -> None:
    renamed = copy.deepcopy(data)
    old_id = renamed["nodes"][0]["id"]
    renamed["nodes"][0]["id"] = word
    for e in renamed["edges"]:
        e["from"] = word if e["from"] == old_id else e["from"]
        e["to"] = word if e["to"] == old_id else e["to"]
    old_layer = next(iter(renamed["layers"]))
    renamed["layers"] = {(word if k == old_layer else k): v for k, v in renamed["layers"].items()}
    for n in renamed["nodes"]:
        n["layer"] = word if n["layer"] == old_layer else n["layer"]
    assert rfg.problems(renamed) == []
    page = rfg.render(renamed)
    assert f"  {rfg._lid(word)}[" in page  # the layer, in the overview
    assert re.search(rf"^\s+{rfg._mid(word)}[\[\(\{{]", page, flags=re.MULTILINE)  # the node, in its diagram
    assert not re.search(rf"^\s+{word}[\[\(\{{]", page, flags=re.MULTILINE)  # never a bare keyword as a node id


@pytest.mark.parametrize("key", ["label", "summary"])
@pytest.mark.parametrize("bad", ["a | b", "two\nlines", "carriage\rreturn"])
def test_text_that_would_break_the_pages_table_is_found(data: dict, key: str, bad: str) -> None:
    found = _mutated(data, lambda d: d["nodes"][0].update(**{key: bad}))
    assert any(f"{key} holds a pipe or a line break" in f for f in found), (key, bad)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["nodes"].__setitem__(0, "a string"),
        lambda d: d["nodes"].__setitem__(0, None),
        lambda d: d["edges"].__setitem__(0, ["a", "b"]),
        lambda d: d["nodes"][0].update(seen=7),
        lambda d: d["nodes"][0].update(id=["x"]),
        lambda d: d["nodes"][0].update(kind=["artifact"]),
        lambda d: d["nodes"][0].update(label=3),
        lambda d: d["edges"][0].update(relation={"x": 1}),
        lambda d: d["edges"][0].update(**{"from": ["board"]}),
        lambda d: d.update(layers=None),
        lambda d: d.update(relations=None),
        lambda d: d.update(nodes=None),
        lambda d: d.update(edges=5),
        lambda d: d.update(kinds={"gizmo": "a kind the renderer cannot draw"}),
        lambda d: d["relations"].update(loves="a relation with no arrow"),
        lambda d: d["layers"].update(**{"my layer": "a layer with a space"}),
        lambda d: d.update(version="one"),
        lambda d: d.update(title=7),
        lambda d: d.update(note=["x"]),
    ],
)
def test_malformed_data_is_reported_never_a_traceback(data: dict, mutate) -> None:
    found = _mutated(data, mutate)
    assert found and all(isinstance(f, str) for f in found)


def test_data_that_is_not_an_object_is_reported() -> None:
    assert rfg.problems([]) == ["the data is not a JSON object"]
    assert rfg.problems("x") == ["the data is not a JSON object"]


# ---- the page
def test_the_page_draws_every_node_and_is_mermaid_safe(data: dict) -> None:
    page = rfg.render(data)
    for n in data["nodes"]:
        assert f"`{n['id']}`" in page  # the table row
        assert f"{rfg._mid(n['id'])}[" in page or f"{rfg._mid(n['id'])}{{" in page or f"{rfg._mid(n['id'])}(" in page
    assert page.count("```mermaid") == len(data["layers"]) + 1  # the overview and one per layer
    assert page.count("```") % 2 == 0
    assert not rfg.diagram_problems(page)


def test_ids_are_prefixed_and_cannot_collide(data: dict) -> None:
    assert len({rfg._mid(n["id"]) for n in data["nodes"]}) == len(data["nodes"])
    assert all(rfg._mid(n["id"]).startswith("n_") for n in data["nodes"])
    assert all(rfg._lid(layer).startswith("l_") for layer in data["layers"])


@pytest.mark.parametrize(
    ("raw", "escaped"),
    [
        ('say "hi"', '"say #quot;hi#quot;"'),
        ("a <b> & c", '"a #lt;b#gt; #amp; c"'),
        ("issue #12", '"issue #35;12"'),
        ("plain", '"plain"'),
    ],
)
def test_label_text_is_written_as_entity_codes(raw: str, escaped: str) -> None:
    assert rfg._label(raw) == escaped


def test_a_label_with_markup_in_it_cannot_inject_a_node_or_a_second_statement(data: dict) -> None:
    hostile = copy.deepcopy(data)
    hostile["nodes"][0]["label"] = 'x"] --> n_evil[<b>'
    page = rfg.render(hostile)
    blocks = re.findall(r"^```mermaid\n(.*?)^```$", page, flags=re.DOTALL | re.MULTILINE)
    assert len(blocks) == len(data["layers"]) + 1
    inside = "\n".join(blocks)
    assert '"x#quot;] --#gt; n_evil[#lt;b#gt;"' in inside
    assert "n_evil" not in inside.replace('"x#quot;] --#gt; n_evil[#lt;b#gt;"', "")
    assert "<b>" not in inside


def test_a_stale_page_is_a_diff(tmp_path: Path) -> None:
    knowledge = _graph_in(tmp_path)
    found, diff = rfg.check(tmp_path)  # no page yet
    assert found == [] and diff != ""
    rfg.write(tmp_path)
    assert rfg.check(tmp_path) == ([], "")
    page = knowledge / "ai-first-framework-graph.md"
    page.write_text(page.read_text(encoding="utf-8") + "drift\n", encoding="utf-8")
    assert rfg.check(tmp_path)[1] != ""


def test_a_crlf_page_is_current(tmp_path: Path) -> None:
    """A Windows working copy checks out CRLF; `--check` must call it current, and a real drift still stale."""
    knowledge = _graph_in(tmp_path)
    rfg.write(tmp_path)
    page = knowledge / "ai-first-framework-graph.md"
    lf, crlf = bytes([10]), bytes([13, 10])
    page.write_bytes(page.read_bytes().replace(lf, crlf))
    assert crlf in page.read_bytes()
    assert rfg.check(tmp_path) == ([], "")
    page.write_bytes(page.read_bytes() + b"drift" + crlf)
    assert rfg.check(tmp_path)[1] != ""


def test_writing_a_malformed_graph_is_refused_and_leaves_no_page(tmp_path: Path) -> None:
    knowledge = _graph_in(tmp_path, '{"layers": {}, "kinds": {}, "relations": {}, "nodes": [], "edges": 5}')
    with pytest.raises(rfg.GraphError):
        rfg.write(tmp_path)
    assert not (knowledge / "ai-first-framework-graph.md").exists()


# ---- the command line
def test_main_exit_codes(tmp_path: Path, capsys) -> None:
    assert rfg.main(["--check"]) == 0  # the shipped graph and page
    assert "well formed and its page is current" in capsys.readouterr().out
    knowledge = _graph_in(tmp_path)
    assert rfg.main(["--check", "--root", str(tmp_path)]) == 1  # no page yet: stale
    out = capsys.readouterr().out
    assert "[graph] the page is stale" in out
    assert rfg.main(["--write", "--root", str(tmp_path)]) == 0
    assert rfg.main(["--check", "--root", str(tmp_path)]) == 0
    capsys.readouterr()
    (knowledge / "ai-first-framework-graph.md").write_bytes(bytes([0xFF, 0xFE]) + b" not utf-8")
    assert rfg.main(["--check", "--root", str(tmp_path)]) == 2  # an unreadable page is reported, not a traceback
    assert "cannot run" in capsys.readouterr().err


def test_main_reports_findings_with_exit_1_and_an_unusable_input_with_exit_2(tmp_path: Path, capsys) -> None:
    assert rfg.main(["--check", "--root", str(tmp_path)]) == 2  # no data file at all
    assert "cannot read" in capsys.readouterr().err
    broken = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    broken["edges"].append(_edge(broken, source="board", to="nowhere"))
    _graph_in(tmp_path / "bad", json.dumps(broken))
    assert rfg.main(["--check", "--root", str(tmp_path / "bad")]) == 1  # a malformed graph is a finding
    assert "[graph] edge board -> nowhere" in capsys.readouterr().out
    assert rfg.main(["--write", "--root", str(tmp_path / "bad")]) == 1  # the same findings, the same code, no page
    assert "[graph] edge board -> nowhere" in capsys.readouterr().out
    assert not (tmp_path / "bad" / "Docs/knowledge/ai-first-framework-graph.md").exists()
    assert rfg.main(["--check", "--root", str(tmp_path / "nowhere")]) == 2
    assert "is not a directory" in capsys.readouterr().err


def test_main_needs_exactly_one_mode(capsys) -> None:
    with pytest.raises(SystemExit) as caught:
        rfg.main([])
    assert caught.value.code == 2
    with pytest.raises(SystemExit):
        rfg.main(["--check", "--write"])


def test_a_verbose_run_leaves_a_record(tmp_path: Path, caplog) -> None:
    _graph_in(tmp_path)
    with caplog.at_level("INFO", logger="tools.render_framework_graph"):
        assert rfg.main(["--write", "-v", "--root", str(tmp_path)]) == 0
    counts = f"{len(rfg.load()['nodes'])} nodes, {len(rfg.load()['edges'])} edges"
    assert f"wrote ai-first-framework-graph.md: {counts}" in caplog.text


# ---- on a repository made from the payload
@pytest.mark.skipif(
    (ROOT / "project.json").exists(),
    reason="runs only against the template's payload, not in a repository made from it",
)
def test_a_repository_made_from_the_payload_passes_its_own_graph_check(tmp_path: Path, capsys) -> None:
    import init as ini

    answers = tmp_path / "answers.json"
    answers.write_text(
        json.dumps(
            {
                "name": "Example Project",
                "slug": "example-project",
                "owner": {"name": "Ada Example", "email": "ada@example.org"},
                "default_branch": "main",
                "signoff": True,
                "hygiene": [],
            }
        ),
        encoding="utf-8",
    )
    target = tmp_path / "proj"
    argv = ["new", "--answers", str(answers), "--target", str(target), "--no-sync", "--no-checks"]
    assert ini.main(argv, source=ROOT, today="2026-10-13") == 0
    capsys.readouterr()
    assert rfg.main(["--check", "--root", str(target)]) == 0
    page = target / "Docs/knowledge/ai-first-framework-graph.md"
    assert page.read_text(encoding="utf-8") == (ROOT / "Docs/knowledge/ai-first-framework-graph.md").read_text(
        encoding="utf-8"
    )
    page.write_text(page.read_text(encoding="utf-8") + "drift\n", encoding="utf-8")
    assert rfg.main(["--check", "--root", str(target)]) == 1


# ---- the declared vocabulary must be drawable
def test_a_kind_with_no_shape_and_a_relation_with_no_arrow_are_named(data: dict) -> None:
    found = _mutated(data, lambda d: d["kinds"].update(gizmo="a kind the renderer cannot draw"))
    assert "kind 'gizmo' has no shape in the renderer" in found
    found = _mutated(data, lambda d: d["relations"].update(loves="a relation with no arrow"))
    assert "relation 'loves' has no arrow in the renderer" in found


@pytest.mark.parametrize("layer", ["my layer", "Upper", "9lives", "with-hyphen", "under_score"])
def test_a_layer_name_the_diagrams_cannot_use_as_an_id_is_named(data: dict, layer: str) -> None:
    found = _mutated(data, lambda d: d["layers"].update({layer: "a layer"}))
    assert f"layer '{layer}' is not a plain lower-case word the diagrams can use as an id" in found


# ---- the command line, as a process
def test_the_stale_diff_is_printed_and_a_write_is_announced(tmp_path: Path, capsys) -> None:
    knowledge = _graph_in(tmp_path)
    assert rfg.main(["--write", "--root", str(tmp_path)]) == 0
    assert "graph: wrote ai-first-framework-graph.md" in capsys.readouterr().out
    page = knowledge / "ai-first-framework-graph.md"
    page.write_text(
        page.read_text(encoding="utf-8").replace("# The AI-first framework graph", "# Drifted"), encoding="utf-8"
    )
    assert rfg.main(["--check", "--root", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert (
        "--- committed" in out
        and "+++ rendered" in out
        and "-# Drifted" in out
        and "+# The AI-first framework graph" in out
    )


def test_a_data_file_that_is_not_an_object_is_unusable(tmp_path: Path, capsys) -> None:
    _graph_in(tmp_path, "[1, 2, 3]")
    assert rfg.main(["--check", "--root", str(tmp_path)]) == 2
    assert "is not a JSON object" in capsys.readouterr().err
    _graph_in(tmp_path / "bad", "{not json")
    assert rfg.main(["--check", "--root", str(tmp_path / "bad")]) == 2


def test_verbose_is_the_only_thing_that_makes_the_tool_log_to_stderr(tmp_path: Path) -> None:
    _graph_in(tmp_path)
    base = [sys.executable, rfg.__file__, "--write", "--root", str(tmp_path)]
    quiet = subprocess.run(base, capture_output=True, text=True, check=False)
    loud = subprocess.run([*base, "-v"], capture_output=True, text=True, check=False)
    assert quiet.returncode == loud.returncode == 0
    assert quiet.stderr == "" and "wrote ai-first-framework-graph.md" in loud.stderr


# ---- robustness of the files it reads and writes
def test_a_duplicate_key_in_the_data_is_refused_not_silently_resolved(tmp_path: Path, capsys) -> None:
    _graph_in(tmp_path, '{"version": 1, "version": 2}')
    assert rfg.main(["--check", "--root", str(tmp_path)]) == 2
    assert "appears twice" in capsys.readouterr().err


def test_a_byte_order_mark_on_the_data_is_tolerated(tmp_path: Path) -> None:
    knowledge = _graph_in(tmp_path)
    data_file = knowledge / "ai-first-framework.graph.json"
    data_file.write_bytes(b"\xef\xbb\xbf" + data_file.read_bytes())
    assert rfg.main(["--write", "--root", str(tmp_path)]) == 0


def test_a_layer_diagram_too_big_for_github_is_a_finding_not_a_page(tmp_path: Path, capsys, monkeypatch) -> None:
    _graph_in(tmp_path)
    monkeypatch.setattr(rfg, "MAX_DIAGRAM_EDGES", 3)
    assert rfg.main(["--check", "--root", str(tmp_path)]) == 1
    assert "GitHub draws at most" in capsys.readouterr().out
    assert rfg.main(["--write", "--root", str(tmp_path)]) == 1  # the same finding and code as --check, no page
    assert "GitHub draws at most" in capsys.readouterr().out
    assert not (tmp_path / "Docs/knowledge/ai-first-framework-graph.md").exists()


def test_the_library_write_also_refuses_a_diagram_too_big_to_draw(tmp_path: Path, monkeypatch) -> None:
    _graph_in(tmp_path)
    monkeypatch.setattr(rfg, "MAX_DIAGRAM_EDGES", 3)
    with pytest.raises(rfg.GraphError, match="cannot be drawn"):
        rfg.write(tmp_path)


def test_the_legend_names_every_relation_under_the_arrow_it_is_drawn_with() -> None:
    """The legend is made from the arrow table, so it cannot describe a relation with the wrong arrow."""
    for arrow, word in (("==>", "thick"), ("-->", "plain"), ("-.->", "dotted")):
        sentence = rfg._READING.split(f"a {word} arrow")[1].split(")")[0]
        drawn = [r for r, a in rfg._ARROWS.items() if a == arrow]
        assert drawn and all(f"`{r}`" in sentence for r in drawn), (word, drawn)
        others = [r for r, a in rfg._ARROWS.items() if a != arrow]
        assert not any(f"`{r}`" in sentence for r in others), (word, others)


def test_a_planted_link_at_the_old_temporary_name_is_never_written_through(tmp_path: Path) -> None:
    knowledge = _graph_in(tmp_path)
    victim = tmp_path / "victim.txt"
    victim.write_text("untouched", encoding="utf-8")
    try:
        (knowledge / "ai-first-framework-graph.md.tmp").symlink_to(victim)
    except OSError:
        pytest.skip("this account may not create symbolic links")
    assert rfg.main(["--write", "--root", str(tmp_path)]) == 0
    assert victim.read_text(encoding="utf-8") == "untouched"
    assert (knowledge / "ai-first-framework-graph.md").read_text(encoding="utf-8") == rfg.render(
        rfg.load(knowledge / "ai-first-framework.graph.json")
    )


def test_the_size_limit_counts_characters_as_well_as_edges(data: dict, monkeypatch) -> None:
    monkeypatch.setattr(rfg, "MAX_DIAGRAM_CHARS", 100)
    assert rfg.diagram_problems(rfg.render(data))
    monkeypatch.setattr(rfg, "MAX_DIAGRAM_CHARS", 10**7)
    assert rfg.diagram_problems(rfg.render(data)) == []


def test_two_nodes_with_one_label_in_a_layer_are_found(data: dict) -> None:
    def clash(d: dict) -> None:
        first = d["nodes"][0]
        second = next(n for n in d["nodes"][1:] if n["layer"] == first["layer"])
        second["label"] = first["label"]

    assert any("is also labelled" in f for f in _mutated(data, clash))


@pytest.mark.parametrize("key", ["layers", "kinds", "relations"])
def test_text_with_a_line_break_in_the_vocabulary_is_found(data: dict, key: str) -> None:
    name = sorted(data[key])[0]
    found = _mutated(data, lambda d: d[key].update({name: "two\nlines"}))
    assert any(f"{key} '{name}'" in f for f in found)


def test_a_failed_write_leaves_the_old_page_and_no_temporary(tmp_path: Path, monkeypatch, capsys) -> None:
    knowledge = _graph_in(tmp_path)
    assert rfg.main(["--write", "--root", str(tmp_path)]) == 0
    page = knowledge / "ai-first-framework-graph.md"
    before = page.read_bytes()

    def refuse(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(rfg.os, "replace", refuse)
    assert rfg.main(["--write", "--root", str(tmp_path)]) == 2
    assert "cannot write" in capsys.readouterr().err
    assert page.read_bytes() == before
    assert sorted(path.name for path in knowledge.iterdir()) == [
        "ai-first-framework-graph.md",
        "ai-first-framework.graph.json",
    ]


def test_non_ascii_text_in_a_report_does_not_crash_a_narrow_stdout(tmp_path: Path) -> None:
    broken = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    broken["edges"].append(_edge(broken, to="caf" + chr(0xE9)))  # the finding names the id, which is not ASCII
    _graph_in(tmp_path, json.dumps(broken))
    env = {**os.environ, "PYTHONIOENCODING": "ascii"}  # a strict ASCII stream, as a bare CI console can be
    ran = subprocess.run(
        [sys.executable, rfg.__file__, "--check", "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert ran.returncode == 1 and "Traceback" not in ran.stderr
    assert "caf" + chr(92) + "xe9" in ran.stdout  # written as an escape: not lost, not a crash


def test_a_recursion_bomb_in_the_data_is_unusable_not_a_crash(tmp_path: Path, capsys) -> None:
    _graph_in(tmp_path, "[" * 100_000)
    assert rfg.main(["--check", "--root", str(tmp_path)]) == 2
    assert "cannot read" in capsys.readouterr().err


@pytest.mark.skipif(os.name == "nt", reason="Windows has no group and other permission bits to lose")
def test_the_written_page_is_readable_by_everyone_not_private_to_the_temporary_file(tmp_path: Path) -> None:
    _graph_in(tmp_path)
    assert rfg.main(["--write", "--root", str(tmp_path)]) == 0
    mode = (tmp_path / "Docs/knowledge/ai-first-framework-graph.md").stat().st_mode
    assert mode & 0o044 == 0o044
