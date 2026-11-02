"""The Power BI report (PBIR): Microsoft's JSON schemas, field bindings against the compiled model, and layout.

Schemas are resolved from the vendored copies in powerbi/schemas, so these tests never touch the network.
"""

import json
import re
from itertools import combinations
from pathlib import Path

import pytest
from jsonschema import validators
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

ROOT = Path(__file__).resolve().parents[1]
POWERBI = ROOT / "powerbi"
REPORT = POWERBI / "FleetDelivery.Report"
DEFINITION = REPORT / "definition"
PBIP = POWERBI / "FleetDelivery.pbip"
SCHEMAS = POWERBI / "schemas"
BIM = ROOT / "build" / "model.bim"
SCHEMA_BASE = "https://developer.microsoft.com/json-schemas/"

pytestmark = pytest.mark.model

PAGES = [
    ("delivery_performance", "Delivery Performance"),
    ("fleet_cost", "Fleet Cost"),
    ("customer_profitability", "Customer Profitability"),
    ("data_health", "Data Health"),
]
MARGIN = 16  # page edge margin and the minimum gap between visuals
NAME_RULE = re.compile(r"^[\w-]{1,50}$")  # Microsoft's PBIR object naming rule; names are capped at 50 characters


def C(entity, prop):
    return ("Column", entity, prop)


def M(entity, prop):
    return ("Measure", entity, prop)


# What each page must show: (visualType, {role: [fields in order]}).
EXPECTED_VISUALS = {
    "delivery_performance": [
        ("slicer", {"Values": [C("Branch", "Branch")]}),
        ("slicer", {"Values": [C("Date", "Year Month")]}),
        ("cardVisual", {"Data": [M("Delivery Stop", "Stops")]}),
        ("cardVisual", {"Data": [M("Delivery Stop", "On-Time %")]}),
        ("cardVisual", {"Data": [M("Delivery Stop", "In-Full %")]}),
        ("cardVisual", {"Data": [M("Delivery Stop", "OTIF %")]}),
        ("lineChart", {"Category": [C("Date", "Month Start")],
                       "Y": [M("Delivery Stop", "On-Time %"), M("Delivery Stop", "OTIF %")]}),
        ("clusteredBarChart", {"Category": [C("Branch", "Branch")], "Y": [M("Delivery Stop", "On-Time %")]}),
        ("tableEx", {"Values": [C("Route", "Route"), C("Route", "Route Branch"), M("Delivery Stop", "Stops"),
                                M("Delivery Stop", "On-Time %"), M("Delivery Stop", "Avg Minutes Late"),
                                M("Delivery Stop", "Short Cases")]}),
    ],
    "fleet_cost": [
        ("slicer", {"Values": [C("Branch", "Branch")]}),
        ("cardVisual", {"Data": [M("Route Trip", "Fleet Cost")]}),
        ("cardVisual", {"Data": [M("Route Trip", "Cost per Case")]}),
        ("cardVisual", {"Data": [M("Route Trip", "Cost per Mile")]}),
        ("cardVisual", {"Data": [M("Fuel", "MPG")]}),
        ("columnChart", {"Category": [C("Date", "Month Start")],
                         "Y": [M("Route Trip", "Labor Cost"), M("Fuel", "Fuel Cost")]}),
        ("tableEx", {"Values": [C("Truck", "Truck"), C("Truck", "Home Branch"), M("Route Trip", "Route Days"),
                                M("Route Trip", "Driven Miles"), M("Fuel", "MPG"), M("Route Trip", "Fleet Cost"),
                                M("Route Trip", "Cost per Mile")]}),
    ],
    "customer_profitability": [
        ("slicer", {"Values": [C("Branch", "Branch")]}),
        ("slicer", {"Values": [C("Product Category", "Category")]}),
        ("cardVisual", {"Data": [M("Invoice Line", "Revenue")]}),
        ("cardVisual", {"Data": [M("Invoice Line", "Gross Margin %")]}),
        ("cardVisual", {"Data": [M("Invoice Line", "Credits")]}),
        ("cardVisual", {"Data": [M("Invoice Line", "Revenue per Stop")]}),
        ("clusteredBarChart", {"Category": [C("Customer", "Segment")], "Y": [M("Invoice Line", "Gross Margin %")]}),
        ("tableEx", {"Values": [C("Customer", "Customer"), C("Customer", "Customer Branch"), C("Customer", "Segment"),
                                M("Invoice Line", "Revenue"), M("Invoice Line", "Gross Margin %"),
                                M("Delivery Stop", "Stops"), M("Invoice Line", "Revenue per Stop"),
                                M("Invoice Line", "Credit %")]}),
    ],
    "data_health": [
        ("cardVisual", {"Data": [M("Delivery Stop", "Geofence Coverage %")]}),
        ("cardVisual", {"Data": [M("Delivery Stop", "Backfilled Entry %")]}),
        ("cardVisual", {"Data": [M("Delivery Stop", "TMS On-Time Overstatement")]}),
        ("cardVisual", {"Data": [M("Pipeline Run", "Last Successful Load UTC")]}),
        ("lineChart", {"Category": [C("Date", "Month Start")],
                       "Y": [M("Delivery Stop", "On-Time %"), M("Delivery Stop", "On-Time % (TMS Time)")]}),
        ("pivotTable", {"Rows": [C("Data Quality", "Rule")], "Columns": [C("Branch", "Branch")],
                        "Values": [M("Data Quality", "Rule Breaches")]}),
        ("tableEx", {"Values": [C("Pipeline Run", "Run Id"), C("Pipeline Run", "Status"),
                                C("Pipeline Run", "Refresh Status"), C("Pipeline Run", "Finished UTC"),
                                C("Pipeline Run", "Source Clock UTC")]}),
    ],
}


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def schema_files() -> list[Path]:
    """Every PBIR document in the report folder plus the .pbip. Theme and image files under StaticResources have
    no PBIR schema and are checked by test_resources_are_registered; local .pbi state is ignored."""
    files = [
        p for p in REPORT.rglob("*")
        if p.is_file() and p.suffix in {".json", ".pbir"} and ".pbi" not in p.parts
        and not p.is_relative_to(REPORT / "StaticResources")
    ]
    return sorted(files) + [PBIP]


def visual_files() -> list[Path]:
    return sorted(DEFINITION.glob("pages/*/visuals/*/visual.json"))


def rel(path: Path) -> str:
    return path.relative_to(POWERBI).as_posix()


# ---- (a) JSON schemas ----


def schema_url(path: Path) -> str:
    return SCHEMA_BASE + path.relative_to(SCHEMAS).as_posix()


@pytest.fixture(scope="module")
def registry() -> Registry:
    resources = []
    for path in SCHEMAS.rglob("*.json"):
        contents = read(path)
        resource = Resource.from_contents(contents, default_specification=DRAFT7)
        resources.append((schema_url(path), resource))
        # The embedded schemas declare an $id spelled schema.embedded.json while the files and $refs use
        # schema-embedded.json; register both so either spelling resolves locally.
        if contents.get("$id") and contents["$id"] != schema_url(path):
            resources.append((contents["$id"], resource))
    return Registry().with_resources(resources)


def schema_errors(doc, registry) -> list[str]:
    url = doc.get("$schema", "")
    assert url.startswith(SCHEMA_BASE), "no Microsoft $schema URL"
    local = SCHEMAS / url.removeprefix(SCHEMA_BASE)
    assert local.exists(), f"{url} is not vendored under powerbi/schemas"
    schema = read(local)
    validator = validators.validator_for(schema)(schema, registry=registry)
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path))
    return [f"{list(e.absolute_path)}: {e.message[:300]}" for e in errors]


@pytest.mark.parametrize("path", schema_files(), ids=rel)
def test_file_matches_its_schema(path, registry):
    errors = schema_errors(read(path), registry)
    assert not errors, "\n".join(errors[:10])


def test_schema_validation_rejects_bad_documents(registry):
    """Guards against a validator that accepts everything. The bad field reference sits behind two cross-file
    $refs (visualConfiguration, then semanticQuery), so this also proves those resolve to the vendored copies."""
    doc = read(visual_files()[0])
    doc["position"]["x"] = "left"
    role = next(iter(doc["visual"]["query"]["queryState"].values()))
    role["projections"][0]["field"] = {"Colum": {"Property": "Branch"}}
    errors = schema_errors(doc, registry)
    assert any("'position', 'x'" in e for e in errors)
    assert any("queryState" in e for e in errors)
    page = read(DEFINITION / "pages" / PAGES[0][0] / "page.json")
    page["displayOption"] = "Stretch"
    assert schema_errors(page, registry)


def test_vendored_schemas_are_exactly_the_ones_in_use():
    def refs(node, found):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "$ref" and isinstance(value, str) and not value.startswith("#"):
                    found.add(value.split("#")[0])
                else:
                    refs(value, found)
        elif isinstance(node, list):
            for item in node:
                refs(item, found)

    pending = {read(p)["$schema"].removeprefix(SCHEMA_BASE) for p in schema_files()}
    needed = set()
    while pending:
        current = pending.pop()
        if current in needed:
            continue
        needed.add(current)
        path = SCHEMAS / current
        assert path.exists(), f"missing vendored schema {current}"
        found = set()
        refs(read(path), found)
        for ref in found:
            assert not ref.startswith("http"), f"{current} has an absolute $ref {ref}"
            pending.add((path.parent / ref).resolve().relative_to(SCHEMAS.resolve()).as_posix())
    vendored = {p.relative_to(SCHEMAS).as_posix() for p in SCHEMAS.rglob("*.json")}
    assert vendored == needed


def test_resources_are_registered():
    report = read(DEFINITION / "report.json")
    registered = {}
    for package in report.get("resourcePackages", []):
        for item in package["items"]:
            path = REPORT / "StaticResources" / package["type"] / item["path"]
            assert path.exists(), f"{item['name']} is registered but {rel(path)} is missing"
            registered[item["name"]] = (item["type"], path)
    on_disk = {p for p in (REPORT / "StaticResources").rglob("*") if p.is_file()}
    assert on_disk == {path for _, path in registered.values()}, "every StaticResources file needs a resourcePackages entry"

    themes = report["themeCollection"]
    assert themes, "a report needs a base or custom theme"
    for slot, theme in themes.items():
        assert theme["name"] in registered, f"{slot} {theme['name']} is not in resourcePackages"
        kind, path = registered[theme["name"]]
        assert kind == {"baseTheme": "BaseTheme", "customTheme": "CustomTheme"}[slot]
        assert path.is_relative_to(REPORT / "StaticResources" / theme["type"])
        body = read(path)
        assert body["name"] and body["dataColors"]
        assert all(re.fullmatch(r"#[0-9A-Fa-f]{6}", c) for c in body["dataColors"])


def test_project_paths_resolve():
    pbip = read(PBIP)
    assert [a["report"]["path"] for a in pbip["artifacts"]] == ["FleetDelivery.Report"]
    assert (POWERBI / pbip["artifacts"][0]["report"]["path"] / "definition.pbir").exists()
    pbir = read(REPORT / "definition.pbir")
    model_dir = (REPORT / pbir["datasetReference"]["byPath"]["path"]).resolve()
    assert (model_dir / "definition.pbism").exists()
    assert pbir["version"] == "4.0"
    assert read(DEFINITION / "version.json")["version"] == "2.0.0"


# ---- (b) field references against the compiled model ----


@pytest.fixture(scope="module")
def model():
    if not BIM.exists():
        pytest.skip("build/model.bim missing; run tools/TmdlCheck first")
    tables = {}
    for t in read(BIM)["model"]["tables"]:
        tables[t["name"]] = {
            "hidden": bool(t.get("isHidden")),
            "Column": {c["name"]: bool(c.get("isHidden")) for c in t.get("columns", [])},
            "Measure": {m["name"]: bool(m.get("isHidden")) for m in t.get("measures", [])},
        }
    return tables


def field_refs(node, where="", aliases=None):
    """Yield (kind, entity, property, location, in_filter) for every Column and Measure reference in a document.

    Filter definitions name their tables in a From list and refer to them by alias (SourceRef.Source)."""
    aliases = aliases or {}
    if isinstance(node, dict):
        if isinstance(node.get("From"), list):
            aliases = {**aliases, **{f["Name"]: f["Entity"] for f in node["From"] if "Entity" in f}}
        for kind in ("Column", "Measure"):
            ref = node.get(kind)
            if isinstance(ref, dict) and "Property" in ref:
                source = ref["Expression"]["SourceRef"]
                entity = source.get("Entity") or aliases.get(source.get("Source"))
                yield kind, entity, ref["Property"], where, "filter" in where.lower()
        for key, value in node.items():
            yield from field_refs(value, f"{where}/{key}", aliases)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from field_refs(item, f"{where}[{i}]", aliases)


def documents_with_fields() -> list[Path]:
    return [DEFINITION / "report.json"] + sorted(DEFINITION.glob("pages/*/page.json")) + visual_files()


@pytest.mark.parametrize("path", documents_with_fields(), ids=rel)
def test_fields_exist_in_the_model(path, model):
    problems = []
    for kind, entity, prop, where, in_filter in field_refs(read(path)):
        table = model.get(entity)
        if table is None:
            problems.append(f"{where}: table '{entity}' does not exist")
        elif prop not in table[kind]:
            other = "Measure" if kind == "Column" else "Column"
            hint = f" (it is a {other.lower()})" if prop in table[other] else ""
            problems.append(f"{where}: {kind.lower()} '{entity}'[{prop}] does not exist{hint}")
        elif not in_filter and (table["hidden"] or table[kind][prop]):
            # Hidden keys may drive filters, but a visible binding to a hidden field is a modelling leak.
            problems.append(f"{where}: '{entity}'[{prop}] is hidden but bound visibly")
    assert not problems, "\n".join(problems)


def test_field_reference_walker_resolves_filter_aliases(model):
    """The walker must see filter fields (with From aliases) so a hidden or missing key in a filter is still checked."""
    doc = {"filterConfig": {"filters": [{"filter": {"From": [{"Name": "d", "Entity": "Delivery Stop", "Type": 0}],
                                                   "Where": [{"Condition": {"Comparison": {"Left": {"Column": {
                                                       "Expression": {"SourceRef": {"Source": "d"}},
                                                       "Property": "Branch Key"}}}}}]}}]}}
    refs = [(kind, entity, prop, in_filter) for kind, entity, prop, _, in_filter in field_refs(doc)]
    assert refs == [("Column", "Delivery Stop", "Branch Key", True)]
    assert model["Delivery Stop"]["Column"]["Branch Key"] is True  # hidden, allowed here because it's a filter


@pytest.mark.parametrize("path", visual_files(), ids=rel)
def test_projections_are_consistent(path):
    visual = read(path)["visual"]
    query = visual.get("query", {})
    projected = []
    for role in query.get("queryState", {}).values():
        for p in role["projections"]:
            kind = next(iter(p["field"]))
            ref = p["field"][kind]
            entity = ref["Expression"]["SourceRef"]["Entity"]
            assert p["queryRef"] == f"{entity}.{ref['Property']}"
            assert p["nativeQueryRef"] == p.get("displayName", ref["Property"])
            projected.append(p["field"])
    for s in query.get("sortDefinition", {}).get("sort", []):
        assert s["field"] in projected, "sort on a field the visual does not show"
        assert s["direction"] in {"Ascending", "Descending"}


# ---- (c) pages, content and layout ----


def visuals_by_page() -> dict[str, list[dict]]:
    return {
        name: [read(p) for p in sorted((DEFINITION / "pages" / name / "visuals").glob("*/visual.json"))]
        for name, _ in PAGES
    }


def test_exactly_four_pages_in_order():
    meta = read(DEFINITION / "pages" / "pages.json")
    names = [name for name, _ in PAGES]
    assert meta["pageOrder"] == names
    assert meta["activePageName"] == names[0]
    assert sorted(p.name for p in (DEFINITION / "pages").iterdir() if p.is_dir()) == sorted(names)
    for name, display in PAGES:
        page = read(DEFINITION / "pages" / name / "page.json")
        assert (page["name"], page["displayName"]) == (name, display)
        assert (page["width"], page["height"]) == (1280, 720)


def test_object_names_follow_the_pbir_rule():
    names = []
    for path in visual_files():
        doc = read(path)
        assert doc["name"] == path.parent.name
        names.append(doc["name"])
    for name, _ in PAGES:
        names.append(name)
    assert all(NAME_RULE.match(n) for n in names), [n for n in names if not NAME_RULE.match(n)]
    assert len(names) == len(set(names)), "page and visual names must be unique across the report"


def binding(doc) -> tuple:
    visual = doc["visual"]
    roles = {}
    for role, state in visual["query"]["queryState"].items():
        roles[role] = []
        for p in state["projections"]:
            kind = next(iter(p["field"]))
            ref = p["field"][kind]
            roles[role].append((kind, ref["Expression"]["SourceRef"]["Entity"], ref["Property"]))
    return visual["visualType"], roles


@pytest.mark.parametrize("page", [name for name, _ in PAGES])
def test_page_shows_the_specified_visuals(page):
    visuals = visuals_by_page()[page]
    actual = sorted((binding(v) for v in visuals), key=repr)
    expected = sorted(EXPECTED_VISUALS[page], key=repr)
    assert actual == expected
    for v in visuals:
        if v["visual"]["visualType"] == "slicer":
            mode = v["visual"]["objects"]["data"][0]["properties"]["mode"]["expr"]["Literal"]["Value"]
            assert mode == "'Dropdown'"


@pytest.mark.parametrize("path", visual_files(), ids=rel)
def test_every_visual_has_a_title(path):
    title = read(path)["visual"]["visualContainerObjects"]["title"][0]["properties"]
    assert title["show"]["expr"]["Literal"]["Value"] == "true"
    assert re.fullmatch(r"'.+'", title["text"]["expr"]["Literal"]["Value"])


def layout_problems(visuals: list[dict], width: float, height: float) -> list[str]:
    """Visuals must sit inside the page with a MARGIN px edge, must not overlap, and must keep a MARGIN px gutter."""

    def box(v):
        p = v["position"]
        return p["x"], p["y"], p["x"] + p["width"], p["y"] + p["height"]

    problems = []
    for v in visuals:
        x1, y1, x2, y2 = box(v)
        if not (MARGIN <= x1 < x2 <= width - MARGIN and MARGIN <= y1 < y2 <= height - MARGIN):
            problems.append(f"{v['name']} {box(v)} is outside the page margins")
    for a, b in combinations(visuals, 2):
        ax1, ay1, ax2, ay2 = box(a)
        bx1, by1, bx2, by2 = box(b)
        gap = max(bx1 - ax2, ax1 - bx2, by1 - ay2, ay1 - by2)
        if gap <= 0:
            problems.append(f"{a['name']} overlaps {b['name']}")
        elif gap < MARGIN:
            problems.append(f"{a['name']} and {b['name']} are {gap} px apart, under the {MARGIN} px gutter")
    return problems


@pytest.mark.parametrize("page", [name for name, _ in PAGES])
def test_visuals_fit_the_page_without_overlap(page):
    page_doc = read(DEFINITION / "pages" / page / "page.json")
    problems = layout_problems(visuals_by_page()[page], page_doc["width"], page_doc["height"])
    assert not problems, "\n".join(problems)


def test_layout_check_catches_bad_layouts():
    def v(name, x, y, w, h):
        return {"name": name, "position": {"x": x, "y": y, "width": w, "height": h}}

    assert layout_problems([v("a", 16, 16, 200, 100), v("b", 232, 16, 200, 100)], 1280, 720) == []
    assert "a overlaps b" in layout_problems([v("a", 16, 16, 200, 100), v("b", 200, 100, 200, 100)], 1280, 720)
    assert layout_problems([v("a", 16, 16, 200, 100), v("b", 220, 16, 200, 100)], 1280, 720)  # 4 px gutter
    assert layout_problems([v("a", 1100, 16, 200, 100)], 1280, 720)  # runs off the right edge
