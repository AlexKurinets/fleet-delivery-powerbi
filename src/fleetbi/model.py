"""Checks and documentation over the compiled semantic model (build/model.bim, written by tools/TmdlCheck).

The best-practice rules are the ones the production team ran on every pull request, written here as
plain Python so they need nothing but the TMSL JSON that Microsoft's TOM library produces from TMDL.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

LARGE_FACTS = {"Delivery Stop": "service_date", "Invoice Line": "posting_date"}
SQL_NAV = re.compile(r'Source\{\[Schema = "(\w+)", Item = "(\w+)"\]\}\[Data\]')
SELECT = re.compile(r"Table\.SelectColumns\(\w+, \{([^}]*)\}\)")


def load_bim(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _expr(value) -> str:
    return "\n".join(value) if isinstance(value, list) else (value or "")


def tables(bim: dict) -> list[dict]:
    return bim["model"]["tables"]


def table(bim: dict, name: str) -> dict:
    return next(t for t in tables(bim) if t["name"] == name)


def partition_source(t: dict) -> tuple[str, str, list[str]] | None:
    """(schema, object, selected columns) of an M partition that reads the warehouse, else None."""
    for p in t.get("partitions", []):
        src = p.get("source", {})
        if src.get("type") != "m":
            continue
        expr = _expr(src.get("expression"))
        nav, sel = SQL_NAV.search(expr), SELECT.search(expr)
        if nav and sel:
            cols = [c.strip().strip('"') for c in sel.group(1).split(",")]
            return nav.group(1), nav.group(2), cols
    return None


def best_practice_violations(bim: dict) -> list[str]:
    m = bim["model"]
    out: list[str] = []
    rels = m.get("relationships", [])
    many_side = {r["fromTable"] for r in rels}
    key_columns = {(r["fromTable"], r["fromColumn"]) for r in rels} | {(r["toTable"], r["toColumn"]) for r in rels}

    if not m.get("discourageImplicitMeasures"):
        out.append("model: discourageImplicitMeasures should be on so every number comes from a measure")
    annotations = {a["name"]: a["value"] for a in m.get("annotations", [])}
    if annotations.get("__PBI_TimeIntelligenceEnabled") != "0":
        out.append("model: auto date/time should be off (it adds a hidden date table per date column)")

    date_tables = [t for t in tables(bim) if t.get("dataCategory") == "Time"]
    if len(date_tables) != 1:
        out.append(f"model: expected exactly one marked date table, found {len(date_tables)}")
    else:
        keys = [c for c in date_tables[0]["columns"] if c.get("isKey")]
        if len(keys) != 1 or keys[0].get("dataType") != "dateTime":
            out.append("Date: the marked date table needs one dateTime key column")

    for r in rels:
        name = f"relationship {r['fromTable']}[{r['fromColumn']}] -> {r['toTable']}[{r['toColumn']}]"
        if r.get("crossFilteringBehavior") == "bothDirections":
            out.append(f"{name}: bidirectional filtering is not allowed")
        if r.get("isActive") is False:
            out.append(f"{name}: inactive relationships need a USERELATIONSHIP measure and a reason; none expected")

    for t in tables(bim):
        tname = t["name"]
        if not t.get("description"):
            out.append(f"{tname}: table has no description")
        for p in t.get("partitions", []):
            if p.get("source", {}).get("type") == "calculated":
                out.append(f"{tname}: calculated tables are not allowed; build the table in the warehouse")
            expr = _expr(p.get("source", {}).get("expression"))
            if p.get("source", {}).get("type") == "m" and "Sql.Database(SqlServer, SqlDatabase)" not in expr:
                out.append(f"{tname}: partition must read through the SqlServer and SqlDatabase parameters")
        for c in t.get("columns", []):
            cname = f"{tname}[{c['name']}]"
            if c.get("type") == "calculated":
                out.append(f"{cname}: calculated columns are not allowed; compute it in SQL")
            if c.get("type") == "calculatedTableColumn":
                continue
            if (tname, c["name"]) in key_columns and not c.get("isHidden"):
                out.append(f"{cname}: relationship key columns must be hidden")
            if c["name"].endswith(" Key") and not c.get("isHidden") and tname != "Security Branch Access":
                out.append(f"{cname}: surrogate keys must be hidden")
            if tname in many_side and c.get("dataType") in ("int64", "double", "decimal") and not c.get("isHidden") \
                    and c.get("summarizeBy", "default") not in ("none",):
                out.append(f"{cname}: numeric fact columns must be hidden or not summarized; expose a measure")
            if "$" in (c.get("formatString") or "") and c.get("dataType") != "decimal":
                out.append(f"{cname}: money columns must use the fixed decimal type")
        for ms in t.get("measures", []):
            mname = f"{tname}[{ms['name']}]"
            for prop in ("description", "formatString", "displayFolder"):
                if not ms.get(prop):
                    out.append(f"{mname}: measure has no {prop}")
            expr = re.sub(r'"[^"]*"', "", _expr(ms.get("expression")))
            if re.search(r"(?<![/*])/(?![/*])", expr):
                out.append(f"{mname}: use DIVIDE instead of the / operator")
            if "IFERROR" in expr.upper():
                out.append(f"{mname}: IFERROR forces cell-by-cell evaluation; use DIVIDE or a guard")

    for name, col in LARGE_FACTS.items():
        try:
            t = table(bim, name)
        except StopIteration:
            out.append(f"{name}: large fact table missing")
            continue
        rp = t.get("refreshPolicy")
        if not rp:
            out.append(f"{name}: large fact tables need an incremental refresh policy")
            continue
        if (rp.get("rollingWindowGranularity"), rp.get("rollingWindowPeriods")) != ("year", 3):
            out.append(f"{name}: refresh policy should keep three years")
        if (rp.get("incrementalGranularity"), rp.get("incrementalPeriods")) != ("day", 10):
            out.append(f"{name}: refresh policy should refresh the last ten days")
        src = _expr(rp.get("sourceExpression"))
        if f"[{col}] >= Date.From(RangeStart)" not in src or f"[{col}] < Date.From(RangeEnd)" not in src:
            out.append(f"{name}: refresh policy must filter {col} on RangeStart (inclusive) and RangeEnd (exclusive)")

    roles = {r["name"]: r for r in m.get("roles", [])}
    bm = roles.get("Branch Manager")
    if not bm:
        out.append("roles: Branch Manager role missing")
    else:
        perms = {p["name"]: p.get("filterExpression", "") for p in bm.get("tablePermissions", [])}
        if "USERPRINCIPALNAME" not in perms.get("Branch", ""):
            out.append("Branch Manager: Branch filter must look up USERPRINCIPALNAME() in the security table")
    try:
        if not table(bim, "Security Branch Access").get("isHidden"):
            out.append("Security Branch Access: the security table must be hidden")
    except StopIteration:
        out.append("Security Branch Access: table missing")
    return out


def data_dictionary(bim: dict) -> str:
    """Markdown data dictionary generated from the model, committed as docs/data-dictionary.md."""
    m = bim["model"]
    # TOM reads the tables and roles folders in file system order, which differs between Windows and
    # Linux; sort everything so the generated file is identical on both.
    ordered = sorted(tables(bim), key=lambda t: t["name"])
    lines = ["# Data dictionary", "",
             "Generated from the semantic model by `fleetbi model docs` (from `build/model.bim`, which "
             "`tools/TmdlCheck` compiles from the TMDL). Do not edit by hand; CI fails if it is out of date.", ""]
    lines += ["## Tables", "", "| Table | Source | Description |", "| --- | --- | --- |"]
    for t in ordered:
        src = partition_source(t)
        where = f"`{src[0]}.{src[1]}`" if src else "calculation group"
        hidden = " (hidden)" if t.get("isHidden") else ""
        lines.append(f"| {t['name']}{hidden} | {where} | {t.get('description', '')} |")
    lines.append("")
    for t in ordered:
        lines += [f"## {t['name']}", "", t.get("description", ""), ""]
        rp = t.get("refreshPolicy")
        if rp:
            lines += [f"Incremental refresh: keep {rp['rollingWindowPeriods']} {rp['rollingWindowGranularity']}s, "
                      f"refresh the last {rp['incrementalPeriods']} {rp['incrementalGranularity']}s.", ""]
        if t.get("calculationGroup"):
            lines += ["| Calculation item | Expression |", "| --- | --- |"]
            for item in t["calculationGroup"]["calculationItems"]:
                expr = " ".join(_expr(item["expression"]).split())
                lines.append(f"| {item['name']} | `{expr}` |")
            lines.append("")
            continue
        measures = sorted(t.get("measures", []), key=lambda x: (x.get("displayFolder", ""), x["name"]))
        if measures:
            lines += ["| Measure | Folder | Format | Description | DAX |", "| --- | --- | --- | --- | --- |"]
            for ms in measures:
                expr = " ".join(_expr(ms["expression"]).split()).replace("|", "\\|")
                fmt = (ms.get("formatString") or "").replace("|", "\\|")
                lines.append(f"| {ms['name']} | {ms.get('displayFolder', '')} | `{fmt}` | "
                             f"{ms.get('description', '')} | `{expr}` |")
            lines.append("")
        lines += ["| Column | Type | Source column | Visible | Description |", "| --- | --- | --- | --- | --- |"]
        for c in t.get("columns", []):
            lines.append(f"| {c['name']} | {c.get('dataType', '')} | `{c.get('sourceColumn', '')}` | "
                         f"{'no' if c.get('isHidden') else 'yes'} | {c.get('description', '')} |")
        lines.append("")
    lines += ["## Relationships", "", "All many-to-one, single direction, active.", "",
              "| From | To |", "| --- | --- |"]
    for r in sorted(m.get("relationships", []), key=lambda r: (r["fromTable"], r["fromColumn"])):
        lines.append(f"| {r['fromTable']}[{r['fromColumn']}] | {r['toTable']}[{r['toColumn']}] |")
    lines += ["", "## Roles", ""]
    for r in sorted(m.get("roles", []), key=lambda r: r["name"]):
        lines += [f"### {r['name']}", "", r.get("description", ""), ""]
        for p in r.get("tablePermissions", []):
            lines.append(f"- {p['name']}: `{' '.join(_expr(p.get('filterExpression')).split())}`")
        if not r.get("tablePermissions"):
            lines.append("- No row filters.")
        lines.append("")
    lines += ["## Parameters", "", "| Name | Default | Description |", "| --- | --- | --- |"]
    for e in sorted(m.get("expressions", []), key=lambda e: e["name"]):
        default = _expr(e["expression"]).split(" meta ")[0]
        lines.append(f"| {e['name']} | `{default}` | {e.get('description', '')} |")
    return "\n".join(lines) + "\n"
