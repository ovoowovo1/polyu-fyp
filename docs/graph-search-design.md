# Graph Search Design

The local PostgreSQL path should support graph-style retrieval without requiring Apache AGE or another non-Windows extension.

## Proposed Tables

- `concepts`: canonical concepts extracted from course material, with `id`, `name`, optional `description`, `class_id`, and audit columns.
- `concept_edges`: directed relationships between concepts, with `source_concept_id`, `target_concept_id`, `relationship_type`, `weight`, and optional evidence text.
- `chunk_concepts`: many-to-many mapping between `chunks` and `concepts`, with optional confidence and extraction source.

## Query Shape

- Direct concept lookup uses PostgreSQL full-text/trigram search on `concepts.name` and `description`.
- Relationship traversal uses recursive CTEs over `concept_edges`, bounded by a small max depth.
- RAG retrieval can combine graph results with existing vector and full-text results through the current reciprocal-rank fusion path.

## Security

- Enable RLS on all graph tables.
- `concepts` visibility follows `class_id` access.
- `chunk_concepts` visibility follows the related `chunks` and `documents` access policies.
- `concept_edges` visibility requires access to both connected concepts.
