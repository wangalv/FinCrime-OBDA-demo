# Module 1: external knowledge (AML typology, AMLTRIX)

- `typology_adapter.ttl` (here): makes Ontop read a few standard properties (SKOS, Dublin Core) of the typology.
- `amlo.ttl` is NOT here. It stays at `ontology/amlo.ttl` because the older part of the repository refers to that path
  (`scripts/to_jsonld.py`, `scripts/build_abox.py`, `demo/amldemo/ontology.py`, `README.md`). `src/paths.py` (`AMLO`) is the only place the new code names it.
- The typology data itself is the set of published CSV files in `vendor/amltrix/` (not edited). The R2RML mapping that reads them is generated:
  `generated/amltrix.r2rml.ttl`, written by `src/build_amltrix_mapping.py`.

AMLTRIX 1.0-beta.4 by UAB Amlyze (https://framework.amltrix.com), used under the AMLTRIX License Terms. Not endorsed by AMLTRIX.
