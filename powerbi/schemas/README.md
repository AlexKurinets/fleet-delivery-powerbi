# Vendored PBIR and PBIP JSON schemas

These are unmodified copies of Microsoft's published JSON schemas for the Power BI project files in this folder, taken from [github.com/microsoft/json-schemas](https://github.com/microsoft/json-schemas) at commit `eecc60d35b9ab18b884d35c50abe7d09d2753cdf` (2026-11-02). Each file sits at the same path it has under `https://developer.microsoft.com/json-schemas/`, so a `$schema` URL maps to a local file by dropping that prefix. `tests/test_report.py` validates every report file and `FleetDelivery.pbip` against these copies without network access.

The set is exactly the transitive closure of the `$schema` URLs the report uses. The test fails if a file is missing or if one is no longer referenced.

| Used by | Schema |
| --- | --- |
| `FleetDelivery.pbip` | `fabric/pbip/pbipProperties/1.0.0/schema.json` |
| `definition.pbir` | `fabric/item/report/definitionProperties/2.0.0/schema.json` |
| `definition/version.json` | `fabric/item/report/definition/versionMetadata/1.0.0/schema.json` |
| `definition/report.json` | `fabric/item/report/definition/report/3.3.0/schema.json` |
| `definition/pages/pages.json` | `fabric/item/report/definition/pagesMetadata/1.1.0/schema.json` |
| `page.json` | `fabric/item/report/definition/page/2.1.0/schema.json` |
| `visual.json` | `fabric/item/report/definition/visualContainer/2.13.0/schema.json` |
| referenced by the schemas above | `filterConfiguration/1.3.0/schema-embedded.json`, `formattingObjectDefinitions/1.5.0/schema.json`, `semanticQuery/1.4.0/schema.json`, `visualConfiguration/2.8.0/schema-embedded.json` (all under `fabric/item/report/definition/`) |

To move to newer versions, change the `$schema` URLs in the report as one matched set, download the new closure from the same repository and update the commit SHA above.

## License

The schema files are distributed under the MIT License of the microsoft/json-schemas repository:

```
MIT License

Copyright (c) Microsoft Corporation. All rights reserved.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE
```
