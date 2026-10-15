"""Unit tests for DepExit's deterministic analysis (fixture repo uses invented package names)."""
from pathlib import Path

from app import manifests, risk, usage
from app.compare import _test_id

REPO = Path(__file__).parent / "fixtures" / "minirepo"


def test_manifests_parse_with_lines_and_notes():
    ms = manifests.discover(REPO)
    assert ms.install_files == ["requirements.txt"]
    old = [d for d in ms.decls if d.name == "oldlib"]
    assert {(d.file, d.line) for d in old} == {("requirements.txt", 1), ("pyproject.toml", 5)}
    assert any("fancylib" in n for n in ms.notes)  # commented-out requirement is reported, not used


def test_manifest_drift_detected():
    ok, why = manifests.specs_compatible(["==1.0.0", ">=2"])
    assert not ok and "1.0.0" in why
    assert manifests.specs_compatible(["==2.1", ">=2"])[0]


def test_usage_finds_private_api_monkeypatch_and_subclass(monkeypatch):
    scan = {"dependencies": [{"name": "oldlib", "import_names": ["oldlib"]},
                             {"name": "transitivelib", "import_names": ["transitivelib"]}]}
    import asyncio
    from app import gemma

    async def offline(*a, **k):  # unit tests never call the network
        raise gemma.GemmaUnavailable("offline test")
    monkeypatch.setattr(gemma, "generate", offline)
    out = asyncio.run(usage.run(REPO, scan, "3.12", gemma.CallLog(None)))
    kinds = {l["kind"] for l in out["usage"]["oldlib"]["locations"]}
    assert {"import", "from_import", "private_api", "monkeypatch", "subclass", "call"} <= kinds
    codes = {i["code"] for i in out["extra_indicators"]["oldlib"]}
    assert {"PRIVATE_API_USE", "MONKEYPATCH"} <= codes
    assert out["usage"]["transitivelib"]["files"] == ["minipkg/core.py"]


def test_risk_scoring_levels():
    s, lvl = risk.score([{"code": "KNOWN_VULNERABILITY", "count": 2}, {"code": "PY312_INCOMPATIBLE", "severity": "critical"}])
    assert (s, lvl) == (70, "critical")
    assert risk.score([{"code": "UNPINNED"}]) == (5, "low")
    assert risk.score([]) == (0, "none")


def test_junit_ids():
    assert _test_id("tests.test_mod", "test_x") == "tests/test_mod.py::test_x"
    assert _test_id("tests.test_mod.TestA", "test_y") == "tests/test_mod.py::TestA::test_y"
    assert _test_id("", "tests.test_mod") == "tests/test_mod.py"


def test_apply_edits_exact_once():
    from app.materialize import apply_edits
    src = "import oldlib\n\ndef f():\n    return oldlib.load()\n"
    new, err = apply_edits(src, [("import oldlib", "import newlib"), ("oldlib.load()", "newlib.load()")])
    assert err is None and "oldlib" not in new
    assert apply_edits(src, [("missing", "x")])[1] == "edit 1 search text not found in the file"
    assert "ambiguous" in apply_edits("a\na\n", [("a", "b")])[1]


def test_key_pool_escalates_repeated_429_to_daily(monkeypatch):
    from app import gemma
    pool = gemma.KeyPool()
    monkeypatch.setattr(gemma.KeyPool, "configured", staticmethod(lambda: ["k-aaaa", "k-bbbb"]))
    pool.rate_limited("k-aaaa", "Resource has been exhausted")
    assert pool.soonest_available() == 0  # the other key is still free
    pool.rate_limited("k-bbbb", "Resource has been exhausted")
    assert 0 < pool.soonest_available() <= 60  # both briefly limited: wait, not exhausted
    assert not pool.status()["exhausted"]
    for _ in range(gemma.DAILY_STRIKES):
        pool.rate_limited("k-aaaa", "x")
        pool.rate_limited("k-bbbb", "x")
    assert pool.soonest_available() is None and pool.status()["exhausted"]
    pool.succeeded("k-aaaa")
    assert pool._state["k-aaaa"].strikes == 0


def test_blast_radius_follows_imports_to_tests():
    from app import blast
    usage_out = {"oldlib": {"locations": [{"file": "minipkg/core.py", "line": 3, "kind": "import", "code": "import oldlib"},
                                          {"file": "minipkg/core.py", "line": 3, "kind": "call", "code": "import oldlib"}]}}
    br = blast.compute(REPO, usage_out)["oldlib"]
    assert br["direct"] == [{"file": "minipkg/core.py",
                             "lines": [{"line": 3, "kinds": ["import", "call"], "code": "import oldlib"}]}]
    assert [x["file"] for x in br["indirect"]] == ["minipkg/app.py"]
    assert br["tests"] == [{"file": "tests/test_app.py", "via": ["tests/test_app.py", "minipkg/app.py", "minipkg/core.py"]}]
    assert br["stats"]["test_files"] == 1 and br["stats"]["total_test_files"] == 2


def test_namespace_package_folder_is_local(tmp_path):
    """A src/ folder of .py files without __init__.py is project code, not an undeclared dependency."""
    from app import pysrc
    (tmp_path / "src" / "classes").mkdir(parents=True)
    (tmp_path / "src" / "classes" / "YouTube.py").write_text("x = 1\n")
    (tmp_path / "src" / "assets").mkdir()
    (tmp_path / "src" / "assets" / "banner.txt").write_text("hi\n")
    names = pysrc.local_packages(tmp_path)
    assert "classes" in names and "assets" not in names


def test_npm_package_names_imports_and_graph():
    from app import npm
    repo = Path(__file__).parent / "fixtures" / "minijs"
    assert npm.package_of("left-padder/sub") == "left-padder"
    assert npm.package_of("@scope/lazy-pkg/x") == "@scope/lazy-pkg"
    assert npm.package_of("./lib/helper") is None and npm.package_of("node:fs") is None and npm.package_of("fs") is None
    used = npm.imports(repo)
    assert {"left-padder", "@scope/lazy-pkg", "undeclared-lib", "css-framework"} <= set(used)
    assert "fs" not in used
    assert used["@scope/lazy-pkg"][0]["kind"] == "call" and used["css-framework"][0]["file"] == "src/styles.css"
    decls, installed, _ = npm.manifests(repo)
    assert installed["left-padder"] == "1.2.5" and "inner" not in installed  # nested packages are not top-level
    assert {(d["name"], d["group"]) for d in decls} == {("left-padder", "main"), ("unused-thing", "main"), ("build-tool", "dev")}
    graph = npm.import_graph(repo)
    assert graph["src/main.js"] == {"src/lib/helper.js"}
    assert graph["src/__tests__/helper.test.js"] == {"src/lib/helper.js"}
    br = npm.blast.compute(repo, {"undeclared-lib": {"locations": used["undeclared-lib"]}},
                           graph=graph, is_test=npm.is_test_file)["undeclared-lib"]
    assert [x["file"] for x in br["indirect"]] == ["src/main.js"]
    assert [x["file"] for x in br["tests"]] == ["src/__tests__/helper.test.js"]
