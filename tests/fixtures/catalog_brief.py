"""Shared SCOPE BRIEF fixture for catalog mini-schema tests."""

BRIEF = """\

## SCOPE BRIEF (authoritative — DO NOT call get_stats ...)

scope:           beer-sample/_default
mode:            auto
nodes_total:     7303      edges_total: 24500      entities_total: 0

## MINI-SCHEMA (per entity_type — derived from the scope's EntityMap)
rule: `find_nodes` `where` is equality-only on these paths.
rule: an `ex:` trailer shows a NON-EXHAUSTIVE sample of that field's stored values.

### Beer  (fields: 8)
  - abv                    number       [gsi]
  - category               display      [none]  -- result-only, NOT filterable
  - ibu                    number       [gsi]
  - description            text_fts     [fts]   -- use fts_search / hybrid_search
  - brewery_id             entity_fk    [gsi]   fk_to=Brewery  ex: coopers_brewery
  - name                   scalar_ent   [gsi]   fk_to=Beer  ex: Coopers Sparkling Ale

### Brewery  (fields: 9)
  - website                display      [none]  -- result-only, NOT filterable
  - city                   scalar_ent   [gsi]   fk_to=City  ex: Arena
  - state                  scalar_ent   [gsi]   fk_to=State  ex: Maine
  inverse_fks:
    \u2190 Beer.brewery_id  (entity_fk)  -- back-walk: find_nodes(entity_type:"Beer", where:{brewery_id:"<this.doc_key>"})

## WALK_PATHS (pre-validated FK chains)
  - Beer \u2192 Brewery                   path=[brewery_id]                             hops=1
"""


def base_chat_req():
    return {
        "_format": "zeus.chat_request.v2",
        "messages": [{"role": "system", "content": "BASE RULES ..." + BRIEF}],
        "guidance": {
            "injections": {"business_logic": []},
            "assembler_hints": {
                "merge_business_logic_into": "Additional Business Rules (injected by middle-man)"
            },
        },
        "verbs": [],
    }