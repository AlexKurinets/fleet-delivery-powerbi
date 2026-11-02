"""The semantic model, as compiled by Microsoft's TOM library from the TMDL (build/model.bim)."""

import copy
from pathlib import Path

import pytest

from fleetbi import db, model

ROOT = Path(__file__).resolve().parents[1]
BIM = ROOT / "build" / "model.bim"
pytestmark = pytest.mark.model


@pytest.fixture(scope="module")
def bim():
    if not BIM.exists():
        pytest.skip("build/model.bim missing; run tools/TmdlCheck first")
    return model.load_bim(BIM)


def test_model_passes_the_best_practice_rules(bim):
    assert model.best_practice_violations(bim) == []


def test_model_shape(bim):
    names = {t["name"] for t in model.tables(bim)}
    assert {"Delivery Stop", "Invoice Line", "Route Trip", "Fuel", "Date", "Branch", "Customer", "Time Calc"} <= names
    measures = [m for t in model.tables(bim) for m in t.get("measures", [])]
    assert len(measures) >= 40
    items = [i["name"] for i in model.table(bim, "Time Calc")["calculationGroup"]["calculationItems"]]
    assert items == ["Current", "MTD", "YTD", "PY", "YoY Change"]


def mutate(bim, fn):
    b = copy.deepcopy(bim)
    fn(b["model"])
    return model.best_practice_violations(b)


def test_each_rule_catches_its_violation(bim):
    def bidi(m):
        m["relationships"][0]["crossFilteringBehavior"] = "bothDirections"

    def unhide_key(m):
        next(c for c in model.table({"model": m}, "Branch")["columns"] if c["name"] == "Branch Key")["isHidden"] = False

    def no_description(m):
        model.table({"model": m}, "Delivery Stop")["measures"][0].pop("description")

    def calc_column(m):
        model.table({"model": m}, "Fuel")["columns"].append(
            {"name": "Price", "type": "calculated", "dataType": "double", "expression": "1", "isHidden": True})

    def slash(m):
        model.table({"model": m}, "Fuel")["measures"][0]["expression"] = "SUM ( Fuel[Fuel Cost] ) / 2"

    def no_policy(m):
        model.table({"model": m}, "Invoice Line").pop("refreshPolicy")

    def hardcoded(m):
        p = model.table({"model": m}, "Truck")["partitions"][0]["source"]
        p["expression"] = [line.replace("Sql.Database(SqlServer, SqlDatabase)", 'Sql.Database("prod-sql", "dw")')
                           for line in p["expression"]]

    def no_rls(m):
        m["roles"] = [r for r in m["roles"] if r["name"] != "Branch Manager"]

    for fn, text in [(bidi, "bidirectional"), (unhide_key, "must be hidden"), (no_description, "no description"),
                     (calc_column, "calculated columns"), (slash, "DIVIDE"), (no_policy, "incremental refresh"),
                     (hardcoded, "SqlServer and SqlDatabase parameters"), (no_rls, "Branch Manager")]:
        problems = mutate(bim, fn)
        assert any(text in p for p in problems), (fn.__name__, problems)


def test_data_dictionary_is_up_to_date(bim):
    committed = (ROOT / "docs" / "data-dictionary.md").read_text(encoding="utf-8")
    assert model.data_dictionary(bim) == committed, "run: fleetbi model docs"


SQL_TYPES = {"int64": {"int", "smallint", "tinyint", "bigint"}, "string": {"varchar", "nvarchar", "char"},
             "decimal": {"decimal"}, "double": {"decimal", "float"}, "dateTime": {"date", "datetime2"},
             "boolean": {"bit"}}


@pytest.mark.db
def test_every_model_column_exists_in_the_warehouse_with_a_compatible_type(bim, loaded):
    """Catches drift between the warehouse and the model before a refresh fails in the service."""
    conn = loaded.conn()
    cols = {(r["s"], r["t"], r["c"]): r["ty"] for r in db.query(conn, """
        SELECT TABLE_SCHEMA AS s, TABLE_NAME AS t, COLUMN_NAME AS c, DATA_TYPE AS ty FROM INFORMATION_SCHEMA.COLUMNS""")}
    checked = 0
    for t in model.tables(bim):
        src = model.partition_source(t)
        if src is None:
            continue
        schema, obj, selected = src
        for name in selected:
            assert (schema, obj, name) in cols, f"{t['name']}: {schema}.{obj}.{name} not in the warehouse"
        for c in t["columns"]:
            assert c["sourceColumn"] in selected, f"{t['name']}[{c['name']}] is not selected by the partition"
            sql_type = cols[(schema, obj, c["sourceColumn"])]
            assert sql_type in SQL_TYPES[c["dataType"]], f"{t['name']}[{c['name']}]: {sql_type} vs {c['dataType']}"
            checked += 1
    assert checked > 100
