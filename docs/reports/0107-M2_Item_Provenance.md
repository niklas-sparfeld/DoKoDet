# 0107 M2: item provenance

`ItemProvenanceService` stores item provenance with the immutable node revision. The caller supplies
editing IDs, JSON pointers, and explicit insert, delete, replace, split, or merge operations. Each
change records its actor, time, optional evidence, item digests, and exact before and after revisions.
Actors can be people, processors, or explicitly not recorded. Earlier records remain available after
correction, replacement, and deletion. An unchanged copy retains the original records and records
its exact source, creator, time, and optional reason.

The service checks item pointers and digests against content and requires operations to account for
all changes to the supplied items. It does not infer physical-card identity or cross-frame links.
Callers must supply the complete set of items they intend to track. The underlying generic node
store does not enforce that callers use this service; runtime integration must enforce the applicable
content-specific item coverage. Copies here exercise provenance preservation; M3 owns downstream-use
protection, atomic copy-on-edit, and retry semantics. The new services are not connected to existing
processor execution.

Verification: the focused provenance and node tests plus existing pipeline store tests passed
(26 tests). They cover tool creation, human and tool correction, split, merge, deletion, unknown
attribution, unchanged copies, exact revision references, invalid operations, and stale writes.
Ruff check and format passed for the changed Python files.
