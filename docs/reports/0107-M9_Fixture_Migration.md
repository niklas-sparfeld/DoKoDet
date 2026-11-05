# 0107 M9: fixture migration

`lineage_migration_apply` applies a saved M8 inventory to a new staging package. The operator
supplies the same root configuration used for inventory. The command checks every declared root
against the inventory file list, copies each declared file under `evidence/<root-id>/`, and writes a
deterministic resource record for every mapped resource. The resource records retain old and new
identities, content facts, unknown-history state, source file digests, and remapped typed references.

Before publication, the command checks staged byte lengths and SHA-256 digests, resource counts,
resource records, and mapped references. It then renames the complete staging directory into place
and syncs the parent directory. A failed conversion or verification removes the private staging
directory. The source remains read-only. Reapplying the same plan verifies and returns the existing
package. A changed source snapshot or a different existing package is rejected without overwrite.

The package records `activation_ready`, conflicts, uncertainties, and sealed-artifact declarations
from the inventory. Migration can preserve a blocked fixture for diagnosis, but this command has no
activation operation. It does not switch an application root or remove legacy stores. Epic 0108 owns
local cutover and recovery operations. This fixture milestone does not migrate live data.

Create the inventory as described in the [M8 report](0107-M8_Migration_Inventory.md), then apply it:

```sh
mise exec -- uv run --project backend python -m dokodetector_backend.lineage_migration_apply \
  config.json plan.json migrated-fixture
```

Verification: focused migration tests cover byte and resource retention, reference IDs, idempotent
reapplication, source changes, interrupted conversion/verification/publication, and destination
path protection. The inventory suite also passes. Ruff check and format pass for the new module and
tests.
