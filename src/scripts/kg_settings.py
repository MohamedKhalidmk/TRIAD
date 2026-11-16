#!/usr/bin/env python3
"""Write the knowledge-graph settings for src/scripts/kg.sh, one NAME=value line for each setting.

The values come from the backend config: a variable of the shell, else src/backend/.env, else the default.
The graph IRIs come from infrastructure/rdf/namespaces.py. Thus kg.sh and the app use the same values.
kg.sh reads the lines with "read"; it does not run them as shell code.

Usage:
    python src/scripts/kg_settings.py
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "src" / "backend"


def settings_lines() -> list[str]:
    sys.path.insert(0, str(BACKEND))
    from infrastructure import config  # noqa: E402 - the backend settings, the same as main.py
    from infrastructure.rdf import namespaces  # noqa: E402
    config.load_env_file()
    settings = config.Settings.from_env()
    dba_password = config.env_virtuoso_dba_password()
    values = {
        "KG_HTTP_PORT": str(config.env_kg_http_port()),
        "KG_DIR": str(settings.kg_dir),
        "KG_SEMANTIC_DIR": str(config.SEMANTIC_DIR),
        "KG_QUERY_URL": settings.sparql_query_url,
        "KG_UPDATE_URL": settings.sparql_update_url,
        "KG_SPARQL_USER": settings.sparql_user,
        "KG_SPARQL_PASSWORD": settings.sparql_password,
        "KG_DBA_PASSWORD": dba_password,
        "KG_DBA_PASSWORD_IS_DEFAULT": "yes" if dba_password == config.DEFAULT_VIRTUOSO_DBA_PASSWORD else "no",
        "KG_TBOX": namespaces.TBOX_GRAPH,
        "KG_ABOX": namespaces.ABOX_GRAPH,
        "KG_SCRATCH": namespaces.SCRATCH_GRAPH,
        "KG_META": namespaces.META_GRAPH,
    }
    if any("\n" in value or "\r" in value for value in values.values()):
        raise SystemExit("A knowledge-graph setting (a path, a URL, a user or a password) has a line break. "
                         "Remove it from the shell or from src/backend/.env.")
    return [f"{name}={value}" for name, value in values.items()]


def main() -> None:
    sys.stdout.write("\n".join(settings_lines()) + "\n")


if __name__ == "__main__":
    main()
